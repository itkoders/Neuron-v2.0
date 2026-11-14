"""NEYRON teacher-owned SIM SMS bridge.

Only paired, enabled teacher devices can fetch tasks. The Android app must obtain
SEND_SMS permission from the device owner and sends through that device's SIM.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta


def _hash(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def init_sms_bridge(run):
    run("""CREATE TABLE IF NOT EXISTS sms_devices (
        teacher_id INTEGER PRIMARY KEY,
        token_hash TEXT UNIQUE NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        device_name TEXT DEFAULT '',
        phone_hint TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        last_seen TEXT DEFAULT ''
    )""")
    run("""CREATE TABLE IF NOT EXISTS sms_pair_codes (
        code_hash TEXT PRIMARY KEY,
        teacher_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    run("""CREATE TABLE IF NOT EXISTS sms_queue (
        id TEXT PRIMARY KEY,
        teacher_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        phone TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        idempotency_key TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL,
        claimed_at TEXT DEFAULT '',
        sent_at TEXT DEFAULT '',
        error TEXT DEFAULT ''
    )""")


def make_pair_code(run, teacher_id, now_iso):
    run("DELETE FROM sms_pair_codes WHERE expires_at < ?", (now_iso,))
    for _ in range(8):
        code = f"{secrets.randbelow(1000000):06d}"
        digest = _hash(code)
        exists = run("SELECT code_hash FROM sms_pair_codes WHERE code_hash=?", (digest,), fetch="one")
        if not exists:
            expires = (datetime.fromisoformat(now_iso) + timedelta(minutes=10)).isoformat()
            run("INSERT INTO sms_pair_codes (code_hash,teacher_id,expires_at,created_at) VALUES (?,?,?,?)",
                (digest, int(teacher_id), expires, now_iso))
            return code
    raise RuntimeError("pair_code_generation_failed")


def pair_device(run, code, device_name, phone_hint, now_iso):
    code = str(code or "").strip()
    if len(code) != 6 or not code.isdigit():
        return None
    row = run("SELECT teacher_id,expires_at FROM sms_pair_codes WHERE code_hash=?",
              (_hash(code),), fetch="one")
    if not row or str(row[1]) < now_iso:
        return None
    teacher_id = int(row[0])
    run("DELETE FROM sms_pair_codes WHERE code_hash=?", (_hash(code),))
    token = secrets.token_urlsafe(40)
    run("""INSERT INTO sms_devices
        (teacher_id,token_hash,enabled,device_name,phone_hint,created_at,last_seen)
        VALUES (?,?,1,?,?,?,?)
        ON CONFLICT(teacher_id) DO UPDATE SET
        token_hash=excluded.token_hash, enabled=1,
        device_name=excluded.device_name, phone_hint=excluded.phone_hint,
        created_at=excluded.created_at, last_seen=excluded.last_seen""",
        (teacher_id, _hash(token), str(device_name or "Android")[:80],
         str(phone_hint or "")[:30], now_iso, now_iso))
    return {"teacher_id": teacher_id, "device_token": token}


def device_from_request(run, request, now_iso):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if len(token) < 32:
        return None
    row = run("SELECT teacher_id,enabled FROM sms_devices WHERE token_hash=?",
              (_hash(token),), fetch="one")
    if not row or not int(row[1] or 0):
        return None
    run("UPDATE sms_devices SET last_seen=? WHERE teacher_id=?", (now_iso, int(row[0])))
    return int(row[0])


def disable_device(run, teacher_id):
    run("UPDATE sms_devices SET enabled=0 WHERE teacher_id=?", (int(teacher_id),))


def enqueue_score_sms(run, teacher_id, student, subject, label, value, now_iso):
    device = run("SELECT enabled FROM sms_devices WHERE teacher_id=?", (int(teacher_id),), fetch="one")
    if not device or not int(device[0] or 0):
        return False
    phone = str(student.get("phone") or "").strip()
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 9 or phone.lower() in {"kiritilmagan", "yo'q", "yoq", "-"}:
        return False
    if digits.startswith("998"):
        phone = "+" + digits
    elif len(digits) == 9:
        phone = "+998" + digits
    else:
        phone = "+" + digits
    value = int(value)
    date_text = datetime.fromisoformat(now_iso).strftime("%d.%m.%Y")
    if value < 60:
        body = (f"NEYRON — JIDDIY OGOHLANTIRISH. {student.get('fio','O‘quvchi')}: "
                f"{subject.get('name','Fan')} fanidan {label}: {value}/100 ball. "
                "Farzandingizning o‘qishiga e’tibor qaratishingizni so‘raymiz. Sana: " + date_text)
    else:
        body = (f"NEYRON — YANGI NATIJA. {student.get('fio','O‘quvchi')}: "
                f"{subject.get('name','Fan')} fanidan {label}: {value}/100 ball. Sana: " + date_text)
    idx_key = f"{int(student['id'])}:{str(label)[:40]}:{date_text}:{value}"
    run("""INSERT INTO sms_queue
        (id,teacher_id,student_id,phone,body,status,idempotency_key,created_at)
        VALUES (?,?,?,?,?,'pending',?,?)
        ON CONFLICT(idempotency_key) DO NOTHING""",
        (str(uuid.uuid4()), int(teacher_id), int(student["id"]), phone, body, idx_key, now_iso))
    return True


def claim_tasks(run, teacher_id, now_iso, limit=5):
    # Eski navbatlar kechikib yuborilmasin: 24 soatdan eski pending xabarlar tugatiladi.
    expired = (datetime.fromisoformat(now_iso) - timedelta(hours=24)).isoformat()
    run("UPDATE sms_queue SET status='expired' WHERE teacher_id=? AND status='pending' AND created_at < ?",
        (teacher_id, expired))
    # Stale claims are retried if the Android app closed before reporting.
    stale = (datetime.fromisoformat(now_iso) - timedelta(minutes=3)).isoformat()
    run("""UPDATE sms_queue SET status='pending',claimed_at=''
        WHERE teacher_id=? AND status='sending' AND claimed_at < ?""", (teacher_id, stale))
    rows = run("""SELECT id,phone,body FROM sms_queue
        WHERE teacher_id=? AND status='pending' ORDER BY created_at LIMIT ?""",
        (teacher_id, int(limit)), fetch="all")
    tasks = []
    for row in rows:
        changed = run("""UPDATE sms_queue SET status='sending',claimed_at=?
            WHERE id=? AND teacher_id=? AND status='pending'""",
            (now_iso, row[0], teacher_id))
        tasks.append({"id": row[0], "phone": row[1], "body": row[2]})
    return tasks


def report_task(run, teacher_id, task_id, status, error, now_iso):
    if status not in {"sent", "failed"}:
        return False
    row = run("SELECT id FROM sms_queue WHERE id=? AND teacher_id=?",
              (str(task_id), int(teacher_id)), fetch="one")
    if not row:
        return False
    run("""UPDATE sms_queue SET status=?,sent_at=?,error=?
        WHERE id=? AND teacher_id=?""",
        (status, now_iso if status == "sent" else "", str(error or "")[:240],
         str(task_id), int(teacher_id)))
    return True
