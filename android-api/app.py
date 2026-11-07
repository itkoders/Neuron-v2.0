import os, time, hmac, hashlib, secrets, random
from urllib.parse import urlencode
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, RedirectResponse
import psycopg2
import httpx
from psycopg2.extras import RealDictCursor
import jwt

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "Neuronv2_bot").lstrip("@")
OWNER_ID = 6359925487
JWT_TTL = 60 * 60 * 24 * 7
LOGIN_CODES = {}
app = FastAPI(title="NEURON Android API", docs_url=None, redoc_url=None)

def db():
    if not DATABASE_URL:
        raise HTTPException(503, "DATABASE_URL sozlanmagan")
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=12)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO neuron_bot, public")
    return conn

def verified_user(data):
    if not BOT_TOKEN or not JWT_SECRET:
        raise HTTPException(503, "Telegram login server sozlanmagan")
    values = {k: str(v) for k, v in data.items() if v is not None}
    check_data = dict(values)
    received = check_data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(check_data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(expected, received):
        raise HTTPException(401, "Telegram imzosi noto'g'ri")
    try:
        uid, auth_date = int(check_data["id"]), int(check_data["auth_date"])
    except Exception:
        raise HTTPException(401, "Telegram login ma'lumoti noto'g'ri")
    if auth_date > time.time() + 60 or time.time() - auth_date > 600:
        raise HTTPException(401, "Login muddati tugagan. Qayta kiring.")
    return uid

def roles_for(uid):
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            roles = ["super_admin"] if uid == OWNER_ID else []
            cur.execute("SELECT id, first_name, last_name, active, verify_status, admin_approved, plan_key, plan_expires FROM teachers WHERE chat_id=%s", (uid,))
            teacher = cur.fetchone()
            if teacher and teacher["active"] and teacher["verify_status"] == "approved" and teacher["admin_approved"]:
                roles.append("teacher")
            cur.execute("SELECT student_id FROM student_links WHERE chat_id=%s", (uid,))
            link = cur.fetchone()
            student = None
            if link:
                cur.execute("SELECT id, teacher_id, subject_id, fio, group_name, s1, s2, s3, davomat, payment_status, teacher_note, last_score_date FROM students WHERE id=%s", (link["student_id"],))
                student = cur.fetchone()
                if student:
                    roles.append("student")
            cur.execute("""SELECT 1 FROM parent_children pc
                JOIN students s ON s.id=pc.student_id
                JOIN teachers t ON t.id=s.teacher_id
                WHERE pc.parent_chat_id=%s AND t.active=1 AND t.verify_status='approved' AND t.admin_approved=1 LIMIT 1""", (uid,))
            if cur.fetchone():
                roles.append("parent")
            return roles, teacher, student
    finally:
        conn.close()

def token_uid(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Kirish talab qilinadi")
    if not JWT_SECRET:
        raise HTTPException(503, "JWT_SECRET sozlanmagan")
    try:
        payload = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
        return int(payload["sub"]), payload["role"]
    except Exception:
        raise HTTPException(401, "Sessiya yaroqsiz yoki muddati tugagan")

def require_role(authorization, allowed):
    uid, role = token_uid(authorization)
    if role not in allowed:
        raise HTTPException(403, "Ruxsat yo'q")
    return uid, role


async def notify_score_parents(student_id, idx, value):
    if not BOT_TOKEN:
        return
    conn = None
    try:
        conn = db()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT s.fio, pc.parent_chat_id FROM students s
                JOIN parent_children pc ON pc.student_id=s.id
                WHERE s.id=%s""", (student_id,))
            rows = cur.fetchall()
        async with httpx.AsyncClient(timeout=8) as client:
            for row in rows:
                try:
                    await client.post("https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage", json={
                        "chat_id": row["parent_chat_id"],
                        "text": "📊 Farzandingiz " + row["fio"] + " bugun " + str(value) + " ball oldi. NEURON SMART JOURNAL."
                    })
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

def teacher_id_for(cur, uid):
    cur.execute("SELECT id FROM teachers WHERE chat_id=%s AND active=1 AND verify_status='approved' AND admin_approved=1", (uid,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(403, "O'qituvchi hisobi tasdiqlanmagan")
    return row["id"]

@app.get("/health")
def health():
    return {"ok": True, "service": "neuron-android-api"}

@app.get("/login", response_class=HTMLResponse)
def login(request: Request):
    if not BOT_TOKEN:
        return HTMLResponse("<h3>Server sozlamasi kutilmoqda</h3>", status_code=503)
    auth_url = str(request.base_url).rstrip("/") + "/auth/telegram/callback"
    return HTMLResponse(f"""<!doctype html><html lang="uz"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>NEURON — Kirish</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#0b1020;color:#fff;font:16px Arial;display:grid;place-items:center;min-height:100vh}}main{{padding:24px}}.panel{{text-align:center;background:#151f38;border:1px solid #293958;border-radius:24px;padding:32px;max-width:390px}}h1{{letter-spacing:5px}}p{{color:#b8c6e5;line-height:1.6}}</style>
    <main><div class="panel"><h1>NEURON</h1><p>SMART JOURNAL</p><p>Telegram hisobingiz orqali xavfsiz kiring. Kabinet va ruxsatlar serverda tekshiriladi.</p>
    <script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-login="{BOT_USERNAME}" data-size="large" data-userpic="false" data-request-access="write" data-auth-url="{auth_url}"></script></div></main></html>""")

@app.get("/auth/telegram/callback")
def telegram_callback(request: Request):
    uid = verified_user(dict(request.query_params))
    roles, _, _ = roles_for(uid)
    if not roles:
        raise HTTPException(403, "Bu Telegram hisobiga NEURON kabineti biriktirilmagan")
    code = secrets.token_urlsafe(32)
    LOGIN_CODES[code] = {"uid": uid, "roles": roles, "expires": time.time() + 90}
    return RedirectResponse("neuron://auth?" + urlencode({"code": code}), status_code=302)

@app.post("/auth/exchange")
async def exchange(request: Request):
    body = await request.json()
    code = str(body.get("code", ""))
    item = LOGIN_CODES.get(code)
    if not item or item["expires"] < time.time():
        LOGIN_CODES.pop(code, None)
        raise HTTPException(401, "Kirish kodi eskirgan. Qayta kiring.")
    roles = item["roles"]
    role = str(body.get("role") or "")
    if not role and len(roles) > 1:
        return {"choose_role": True, "roles": roles}
    if not role:
        role = roles[0]
    if role not in roles:
        raise HTTPException(403, "Tanlangan rolga ruxsat yo'q")
    LOGIN_CODES.pop(code, None)
    token = jwt.encode({"sub": str(item["uid"]), "role": role, "iat": int(time.time()), "exp": int(time.time()) + JWT_TTL}, JWT_SECRET, algorithm="HS256")
    return {"token": token, "role": role}

@app.get("/api/me")
def me(authorization: str = Header(default="")):
    uid, role = require_role(authorization, {"teacher", "student", "parent", "super_admin"})
    roles, teacher, student = roles_for(uid)
    if role not in roles:
        raise HTTPException(403, "Rol endi faol emas")
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if role == "teacher":
                tid = teacher_id_for(cur, uid)
                cur.execute("SELECT id,name,label1,label2,label3 FROM subjects WHERE teacher_id=%s ORDER BY id", (tid,))
                subjects = cur.fetchall()
                cur.execute("SELECT first_name,last_name,plan_key,plan_expires FROM teachers WHERE id=%s", (tid,))
                t = cur.fetchone()
                cur.execute("SELECT COUNT(*) AS total FROM students WHERE teacher_id=%s", (tid,))
                count = cur.fetchone()["total"]
                return {"role": role, "name": (t["first_name"] + " " + (t["last_name"] or "")).strip(), "plan": t["plan_key"], "expires": t["plan_expires"], "subjects": subjects, "student_count": count}
            if role == "student":
                cur.execute("""SELECT s.id,s.fio,s.group_name,s.s1,s.s2,s.s3,s.davomat,s.payment_status,s.teacher_note,s.last_score_date,sub.name AS subject
                    FROM students s LEFT JOIN subjects sub ON sub.id=s.subject_id WHERE s.id=%s""", (student["id"],))
                return {"role": role, **dict(cur.fetchone())}
            if role == "parent":
                cur.execute("""SELECT s.id,s.fio,s.group_name,s.s1,s.s2,s.s3,s.davomat,s.payment_status,s.payment_amount,s.payment_date,s.teacher_note,sub.name AS subject
                    FROM parent_children pc JOIN students s ON s.id=pc.student_id
                    JOIN teachers t ON t.id=s.teacher_id LEFT JOIN subjects sub ON sub.id=s.subject_id
                    WHERE pc.parent_chat_id=%s AND t.active=1 AND t.verify_status='approved' AND t.admin_approved=1 ORDER BY s.fio""", (uid,))
                return {"role": role, "children": cur.fetchall()}
            cur.execute("SELECT COUNT(*) AS teachers FROM teachers")
            teachers_count = cur.fetchone()["teachers"]
            cur.execute("SELECT COUNT(*) AS students FROM students")
            students_count = cur.fetchone()["students"]
            cur.execute("SELECT COUNT(*) AS parents FROM (SELECT DISTINCT parent_chat_id FROM parent_children) p")
            parents_count = cur.fetchone()["parents"]
            cur.execute("SELECT key,name,price,duration_days,active,student_limit,subject_limit FROM plans ORDER BY price")
            plans = cur.fetchall()
            cur.execute("""SELECT id,first_name,last_name,phone,plan_key,plan_expires,active,verify_status,admin_approved,created_at
                FROM teachers ORDER BY id DESC LIMIT 100""")
            teacher_rows = cur.fetchall()
            return {"role": role, "counts": {"teachers": teachers_count, "students": students_count, "parents": parents_count}, "plans": plans, "teachers": teacher_rows}
    finally:
        conn.close()

@app.get("/api/teacher/subject/{sid}")
def teacher_subject(sid: int, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid = teacher_id_for(cur, uid)
            cur.execute("SELECT id,name,label1,label2,label3 FROM subjects WHERE id=%s AND teacher_id=%s", (sid, tid))
            subject = cur.fetchone()
            if not subject:
                raise HTTPException(404, "Fan topilmadi")
            cur.execute("""SELECT id,fio,code,phone,group_name,s1,s2,s3,davomat,payment_status,payment_amount,payment_date,last_score_date,teacher_note
                FROM students WHERE teacher_id=%s AND subject_id=%s ORDER BY group_name,fio""", (tid, sid))
            students = cur.fetchall()
            cur.execute("""SELECT group_name,COUNT(*) AS student_count FROM students
                WHERE teacher_id=%s AND subject_id=%s GROUP BY group_name ORDER BY group_name""", (tid, sid))
            groups = cur.fetchall()
            return {"subject": subject, "students": students, "groups": groups}
    finally:
        conn.close()

@app.post("/api/teacher/subject")
async def add_subject(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    body = await request.json()
    name = str(body.get("name", "")).strip()[:60]
    if len(name) < 2:
        raise HTTPException(400, "Fan nomini kiriting")
    labels = [str(x).strip()[:20] for x in body.get("labels", [])[:3]]
    labels += ["Test", "Qo'shimcha", "Uy vazifasi"][len(labels):]
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid = teacher_id_for(cur, uid)
            cur.execute("INSERT INTO subjects(teacher_id,name,label1,label2,label3) VALUES(%s,%s,%s,%s,%s) RETURNING id", (tid, name, labels[0], labels[1], labels[2]))
            sid = cur.fetchone()["id"]
        conn.commit()
        return {"ok": True, "id": sid}
    finally:
        conn.close()

@app.post("/api/teacher/student")
async def add_student(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    body = await request.json()
    fio = str(body.get("fio", "")).strip()[:80]
    group_name = str(body.get("group_name", "Guruhsiz")).strip()[:40] or "Guruhsiz"
    sid = int(body.get("subject_id", 0))
    if len(fio) < 3:
        raise HTTPException(400, "O'quvchi F.I.O. sini kiriting")
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid = teacher_id_for(cur, uid)
            cur.execute("SELECT id FROM subjects WHERE id=%s AND teacher_id=%s", (sid, tid))
            if not cur.fetchone():
                raise HTTPException(404, "Fan topilmadi")
            code = None
            for _ in range(100):
                candidate = str(random.randint(1000, 9999))
                cur.execute("SELECT 1 FROM students WHERE code=%s", (candidate,))
                if not cur.fetchone():
                    code = candidate
                    break
            if not code:
                raise HTTPException(500, "O'quvchi kodi yaratilmadi")
            cur.execute("INSERT INTO students(teacher_id,subject_id,fio,code,group_name) VALUES(%s,%s,%s,%s,%s) RETURNING id", (tid, sid, fio, code, group_name))
            student_id = cur.fetchone()["id"]
        conn.commit()
        return {"ok": True, "id": student_id, "code": code}
    finally:
        conn.close()

@app.post("/api/teacher/score")
async def teacher_score(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    body = await request.json()
    student_id, idx, value = int(body.get("student_id", 0)), int(body.get("idx", 0)), int(body.get("value", -1))
    if idx not in (1, 2, 3) or not 0 <= value <= 100:
        raise HTTPException(400, "Ball 0–100 oralig'ida bo'lishi kerak")
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid = teacher_id_for(cur, uid)
            cur.execute("UPDATE students SET s" + str(idx) + "=%s,last_score_date=%s WHERE id=%s AND teacher_id=%s RETURNING id", (value, datetime.now().strftime("%d.%m.%Y"), student_id, tid))
            if not cur.fetchone():
                raise HTTPException(404, "O'quvchi topilmadi")
            cur.execute("""INSERT INTO attendance_history(student_id,date_str,davomat,s1,s2,s3)
                SELECT id,%s,davomat,s1,s2,s3 FROM students WHERE id=%s""", (datetime.now().strftime("%d.%m.%Y"), student_id))
        conn.commit()
        await notify_score_parents(student_id, idx, value)
        return {"ok": True}
    finally:
        conn.close()

@app.get("/api/teacher/student/{student_id}/history")
def student_history(student_id: int, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid = teacher_id_for(cur, uid)
            cur.execute("""SELECT h.date_str,h.davomat,h.s1,h.s2,h.s3 FROM attendance_history h
                JOIN students s ON s.id=h.student_id WHERE h.student_id=%s AND s.teacher_id=%s
                ORDER BY h.id DESC LIMIT 30""", (student_id, tid))
            return {"history": cur.fetchall()}
    finally:
        conn.close()

@app.post("/api/teacher/attendance")
async def teacher_attendance(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    body = await request.json()
    student_id, status = int(body.get("student_id", 0)), str(body.get("status", ""))
    if status not in {"Keldi", "Kelmadi", "Sababli", "Kutilmoqda"}:
        raise HTTPException(400, "Davomat holati noto'g'ri")
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid = teacher_id_for(cur, uid)
            cur.execute("UPDATE students SET davomat=%s WHERE id=%s AND teacher_id=%s RETURNING id", (status, student_id, tid))
            if not cur.fetchone():
                raise HTTPException(404, "O'quvchi topilmadi")
            cur.execute("""INSERT INTO attendance_history(student_id,date_str,davomat,s1,s2,s3)
                SELECT id,%s,davomat,s1,s2,s3 FROM students WHERE id=%s""", (datetime.now().strftime("%d.%m.%Y"), student_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

@app.post("/api/teacher/payment")
async def teacher_payment(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    body = await request.json()
    student_id, status = int(body.get("student_id", 0)), str(body.get("status", ""))
    if status not in {"To'langan", "To'lanmagan"}:
        raise HTTPException(400, "To'lov holati noto'g'ri")
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid = teacher_id_for(cur, uid)
            date = datetime.now().strftime("%d.%m.%Y") if status == "To'langan" else "-"
            cur.execute("UPDATE students SET payment_status=%s,payment_date=%s WHERE id=%s AND teacher_id=%s RETURNING id", (status, date, student_id, tid))
            if not cur.fetchone():
                raise HTTPException(404, "O'quvchi topilmadi")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

@app.post("/api/admin/teacher/approve")
async def approve_teacher(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"super_admin"})
    if uid != OWNER_ID:
        raise HTTPException(403, "Faqat loyiha egasi")
    body = await request.json()
    tid = int(body.get("teacher_id", 0))
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("UPDATE teachers SET verify_status='approved',admin_approved=1 WHERE id=%s AND active=1 RETURNING id", (tid,))
            if not cur.fetchone():
                raise HTTPException(404, "O'qituvchi topilmadi")
            cur.execute("INSERT INTO audit_log(actor,action,target,details,created_at) VALUES(%s,%s,%s,%s,%s)", (uid, "android_teacher_approve", str(tid), "Super Admin ilovadan tasdiqladi", datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

@app.post("/api/admin/plan")
async def update_plan(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"super_admin"})
    if uid != OWNER_ID:
        raise HTTPException(403, "Faqat loyiha egasi")
    body = await request.json()
    key = str(body.get("key", ""))
    allowed = {"name", "price", "duration_days", "student_limit", "active"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        raise HTTPException(400, "O'zgartirish yo'q")
    conn = db()
    try:
        with conn.cursor() as cur:
            for field, value in updates.items():
                cur.execute("UPDATE plans SET " + field + "=%s WHERE key=%s", (value, key))
            if cur.rowcount == 0:
                raise HTTPException(404, "Tarif topilmadi")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

MOBILE_HTML = r"""<!doctype html>
<html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="theme-color" content="#0b1020"><title>NEURON SMART JOURNAL</title>
<style>
:root{--bg:#0b1020;--panel:#141e35;--panel2:#1b2946;--line:#293958;--txt:#f5f7ff;--muted:#9eaccb;--blue:#7187ff;--cyan:#56d6d0;--green:#54d69b;--red:#ff7584;--amber:#ffc76b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#172544 0,#0b1020 58%);color:var(--txt);font:15px system-ui,-apple-system,Arial;min-height:100vh}button,input,select{font:inherit}button{cursor:pointer;border:0}.wrap{max-width:900px;margin:auto;padding:18px 15px 90px}.top{display:flex;align-items:center;justify-content:space-between;padding:12px 2px 20px}.brand{font-weight:900;letter-spacing:4px;font-size:22px}.subbrand{color:var(--muted);font-size:10px;letter-spacing:3px}.avatar{width:40px;height:40px;border-radius:14px;background:linear-gradient(135deg,#7187ff,#4bd2c8);display:grid;place-items:center;font-weight:900;color:#07101e}.hero{background:linear-gradient(125deg,#24365d,#182640 65%,#193c4c);border:1px solid #344b70;border-radius:24px;padding:22px;margin-bottom:16px;box-shadow:0 18px 55px #0003}.eyebrow{color:#a9c0ff;font-size:11px;letter-spacing:2px;font-weight:800}.hero h1{font-size:25px;margin:8px 0}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.card{background:linear-gradient(145deg,#17233d,#121b30);border:1px solid var(--line);border-radius:19px;padding:16px;margin:10px 0}.stat{font-size:26px;font-weight:850;margin-top:8px}.label{font-size:12px;color:var(--muted)}.section-title{font-size:18px;font-weight:800;margin:22px 2px 10px}.btn{padding:12px 15px;border-radius:13px;background:var(--blue);color:white;font-weight:750}.btn.secondary{background:#263655;color:#e7edff;border:1px solid #3a4c70}.btn.green{background:#1d765c}.btn.red{background:#803746}.btn.full{width:100%;margin-top:10px}.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.row>*{flex:1}.subject{display:flex;justify-content:space-between;align-items:center;width:100%;padding:16px;border-radius:16px;background:#182641;color:white;border:1px solid #334665;text-align:left;margin:7px 0}.student{background:#15223a;border:1px solid #2c3e5e;border-radius:17px;padding:14px;margin:10px 0}.student h3{margin:0 0 4px;font-size:16px}.groupbar{display:flex;gap:8px;overflow-x:auto;padding:12px 0}.groupchip{white-space:nowrap;border:1px solid #354765;background:#111a2d;color:#cbd7ef;border-radius:999px;padding:10px 14px}.groupchip.active{background:#245bca;color:white;border-color:#4f83ef}.codebox{display:flex;align-items:center;justify-content:space-between;gap:8px;background:#0d172b;border:1px dashed #4b6b9e;border-radius:12px;padding:10px;margin:10px 0;flex-wrap:wrap}.scores{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}.field label{display:block;color:var(--muted);font-size:11px;margin-bottom:5px}.field input,.field select{width:100%;background:#0d172b;border:1px solid #35496c;border-radius:10px;padding:10px;color:white;min-width:0}.pill{display:inline-block;padding:5px 9px;border-radius:30px;background:#263756;color:#cbd8ff;font-size:11px}.ok{color:var(--green)}.warn{color:var(--amber)}.danger{color:var(--red)}.nav{position:fixed;bottom:0;left:0;right:0;background:#0d1528ed;backdrop-filter:blur(16px);border-top:1px solid #293958;display:flex;justify-content:center;gap:8px;padding:10px 12px calc(10px + env(safe-area-inset-bottom));z-index:5}.nav button{background:transparent;color:#9eaccb;padding:8px 13px;border-radius:12px;font-size:12px}.nav button.active{background:#26385c;color:white}.notice{padding:12px 14px;border-radius:13px;background:#392f20;color:#ffdaa0;margin:10px 0}.login{min-height:80vh;display:grid;place-items:center;text-align:center}.loginbox{max-width:390px;padding:30px 22px;background:#15213b;border:1px solid #304365;border-radius:25px}.hidden{display:none!important}.small{font-size:12px}.divider{height:1px;background:#2b3a58;margin:12px 0}.toast{position:fixed;top:12px;left:15px;right:15px;z-index:10;background:#25385a;border:1px solid #526b9a;padding:13px;border-radius:13px;text-align:center;display:none}@media(min-width:650px){.grid{grid-template-columns:repeat(4,minmax(0,1fr))}.student-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.student{margin:0}.wrap{padding-top:28px}}
</style></head><body><div id="toast" class="toast"></div><div class="wrap" id="app"></div><div id="nav" class="nav hidden"></div>
<script>
const app=document.getElementById('app'),nav=document.getElementById('nav');let token=localStorage.getItem('neuron_token')||'',role=localStorage.getItem('neuron_role')||'',me=null,activeSubject=null,subjectData=null,loginCode=new URLSearchParams(location.search).get('code');
const roleNames={teacher:"O‘qituvchi",student:"O‘quvchi",parent:"Ota-ona","super_admin":"Super Admin"};
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(s){let t=document.getElementById('toast');t.textContent=s;t.style.display='block';setTimeout(()=>t.style.display='none',2600)}
async function api(path,opts={}){let r=await fetch(path,{...opts,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token,...(opts.headers||{})}});let d=await r.json().catch(()=>({detail:'Server javobi xato'}));if(!r.ok)throw Error(d.detail||'Xatolik');return d}
function shell(title,sub){app.innerHTML='<div class="top"><div><div class="brand">NEURON</div><div class="subbrand">SMART JOURNAL</div></div><div class="avatar">'+esc((me?.name||roleNames[role]||'N').slice(0,1))+'</div></div><div class="hero"><div class="eyebrow">'+esc(roleNames[role]||'KABINET')+'</div><h1>'+esc(title)+'</h1><div class="muted">'+esc(sub||'Bilim • Natija • Rivojlanish')+'</div></div><div id="content"></div>';nav.classList.remove('hidden');nav.innerHTML='<button class="active" onclick="home()">⌂ Bosh sahifa</button><button onclick="refresh()">↻ Yangilash</button><button onclick="logout()">Chiqish</button>'}
function showLogin(msg){nav.classList.add('hidden');app.innerHTML='<div class="login"><div class="loginbox"><div class="brand">NEURON</div><div class="subbrand">SMART JOURNAL</div><h2>Bilim sari yangi qadam</h2><p class="muted">Kabinetga Telegram hisobingiz orqali xavfsiz kiring.</p>'+(msg?'<div class="notice">'+esc(msg)+'</div>':'')+'<a class="btn" style="display:inline-block;text-decoration:none;margin-top:12px" href="/login">Telegram orqali kirish</a><p class="muted small">Faqat tizimga biriktirilgan hisoblar kira oladi.</p></div></div>'}
async function startExchange(code,chosen){try{let d=await api('/auth/exchange',{method:'POST',body:JSON.stringify({code,role:chosen||''})});if(d.choose_role){app.innerHTML='<div class="login"><div class="loginbox"><div class="brand">NEURON</div><h2>Kabinetni tanlang</h2><p class="muted">Ushbu Telegram hisobiga bir nechta rol biriktirilgan.</p>'+d.roles.map(x=>'<button class="btn full" onclick="startExchange('+JSON.stringify(code)+','+JSON.stringify(x)+')">'+esc(roleNames[x]||x)+'</button>').join('')+'</div></div>';return}token=d.token;role=d.role;localStorage.setItem('neuron_token',token);localStorage.setItem('neuron_role',role);history.replaceState({},'','/mobile');await load()}catch(e){showLogin(e.message)}}
async function load(){try{me=await api('/api/me');role=me.role;localStorage.setItem('neuron_role',role);home()}catch(e){logout(false);showLogin(e.message)}}
function logout(show=true){token='';role='';me=null;localStorage.removeItem('neuron_token');localStorage.removeItem('neuron_role');if(show)showLogin('Sessiya yakunlandi')}
async function refresh(){try{me=await api('/api/me');home();toast('Ma’lumotlar yangilandi')}catch(e){toast(e.message)}}
function home(){if(!me){load();return}if(role==='teacher')teacherHome();else if(role==='student')studentHome();else if(role==='parent')parentHome();else adminHome()}
function teacherHome(){shell('Xush kelibsiz, '+(me.name||'ustoz'),'Tarif: '+(me.plan||'—')+' • O‘quvchilar: '+(me.student_count||0));let c=document.getElementById('content');c.innerHTML='<div class="grid"><div class="card"><div class="label">O‘quvchilar</div><div class="stat">'+(me.student_count||0)+'</div></div><div class="card"><div class="label">Fanlar</div><div class="stat">'+me.subjects.length+'</div></div></div><div class="section-title">Fanlar jurnali</div><div id="subjects"></div><button class="btn full" onclick="addSubject()">＋ Yangi fan qo‘shish</button>';let s=document.getElementById('subjects');if(!me.subjects.length)s.innerHTML='<div class="card muted">Hozircha fan qo‘shilmagan.</div>';me.subjects.forEach(x=>{s.innerHTML+='<button class="subject" onclick="openSubject('+x.id+')"><span>📘 '+esc(x.name)+'</span><span>›</span></button>'})}
async function openSubject(id){try{activeSubject=id;subjectData=await api('/api/teacher/subject/'+id);let c=document.getElementById('content');let sub=subjectData.subject;c.innerHTML='<button class="btn secondary" onclick="teacherHome()">← Fanlar</button><div class="section-title">'+esc(sub.name)+' — guruhlar jurnali</div><div class="muted small">Har bir guruhda faqat shu guruh o‘quvchilari ko‘rinadi.</div><button class="btn full" onclick="addStudent('+id+')">＋ O‘quvchi qo‘shish</button><div class="groupbar" id="groupbar"></div><div class="student-list" id="students"></div>';renderGroupJournal('Barchasi')}catch(e){toast(e.message)}}
function studentEditor(st,sub){let id=st.id;return '<div class="student"><h3>'+esc(st.fio)+'</h3><div class="muted small">'+esc(st.group_name)+' • ID: '+id+'</div><div class="codebox"><b>O‘quvchi kodi: '+esc(st.code||'—')+'</b><button class="btn secondary" onclick="copyStudentCode('+JSON.stringify(st.code||'')+')">Nusxalash</button></div><div class="scores">'+[1,2,3].map(i=>'<div class="field"><label>'+esc(sub['label'+i]||('Ball '+i))+'</label><input id="s'+id+'_'+i+'" type="number" min="0" max="100" value="'+(st['s'+i]||0)+'"></div>').join('')+'</div><button class="btn full" onclick="saveScores('+id+')">Ballarni saqlash</button><button class="btn secondary full" onclick="showHistory('+id+')">Jurnal tarixi</button><div class="divider"></div><div class="row"><div class="field"><label>Davomat</label><select id="a'+id+'">'+['Keldi','Kelmadi','Sababli','Kutilmoqda'].map(x=>'<option '+(st.davomat===x?'selected':'')+'>'+x+'</option>').join('')+'</select></div><div class="field"><label>To‘lov</label><select id="p'+id+'">'+["To'langan","To'lanmagan"].map(x=>'<option '+(st.payment_status===x?'selected':'')+'>'+x+'</option>').join('')+'</select></div></div><div class="row"><button class="btn secondary" onclick="saveAttendance('+id+')">Davomat</button><button class="btn secondary" onclick="savePayment('+id+')">To‘lov</button></div><div class="muted small" style="margin-top:9px">Oxirgi ball: '+esc(st.last_score_date||'—')+' • '+esc(st.payment_date||'')+'</div></div>'}
async function saveScores(id){try{for(let i=1;i<=3;i++){let value=Number(document.getElementById('s'+id+'_'+i).value);if(!Number.isInteger(value)||value<0||value>100)throw Error('Ball 0 dan 100 gacha bo‘lsin');await api('/api/teacher/score',{method:'POST',body:JSON.stringify({student_id:id,idx:i,value})})}toast('Ballar saqlandi')}catch(e){toast(e.message)}}
async function showHistory(id){try{let d=await api('/api/teacher/student/'+id+'/history');let rows=d.history||[];let txt=rows.map(x=>x.date_str+' • '+x.davomat+' • '+[x.s1,x.s2,x.s3].join(' / ')).join('\\n');alert(rows.length?txt:'Hali tarix yo‘q')}catch(e){toast(e.message)}}
async function saveAttendance(id){try{await api('/api/teacher/attendance',{method:'POST',body:JSON.stringify({student_id:id,status:document.getElementById('a'+id).value})});toast('Davomat saqlandi')}catch(e){toast(e.message)}}
async function savePayment(id){try{await api('/api/teacher/payment',{method:'POST',body:JSON.stringify({student_id:id,status:document.getElementById('p'+id).value})});toast('To‘lov holati saqlandi')}catch(e){toast(e.message)}}
function copyStudentCode(code){if(!code)return;if(navigator.clipboard?.writeText){navigator.clipboard.writeText(code).then(()=>toast('O‘quvchi kodi nusxalandi')).catch(()=>prompt('O‘quvchi kodini nusxalang:',code))}else prompt('O‘quvchi kodini nusxalang:',code)}
function renderGroupJournal(selected){let bar=document.getElementById('groupbar'),list=document.getElementById('students');if(!bar||!list)return;let groups=(subjectData.groups||[]).map(x=>x.group_name||'Guruhsiz');let opts=['Barchasi',...groups];bar.innerHTML=opts.map(g=>'<button class="groupchip '+(g===selected?'active':'')+'" onclick="renderGroupJournal('+JSON.stringify(g)+')">'+esc(g)+(g==='Barchasi'?'':' · '+((subjectData.groups.find(x=>x.group_name===g)||{}).student_count||0))+'</button>').join('');let rows=subjectData.students.filter(st=>selected==='Barchasi'||(st.group_name||'Guruhsiz')===selected);list.innerHTML=rows.length?rows.map(st=>studentEditor(st,subjectData.subject)).join(''):'<div class="card muted">Bu guruhda o‘quvchilar yo‘q.</div>'}
async function addStudent(sid){let fio=prompt('O‘quvchi F.I.O.:');if(!fio)return;let group=prompt('Qaysi guruhga qo‘shilsin? Masalan: Tarix 1-guruh', '1-guruh')||'Guruhsiz';try{let d=await api('/api/teacher/student',{method:'POST',body:JSON.stringify({subject_id:sid,fio,group_name:group})});alert('O‘quvchi muvaffaqiyatli qo‘shildi!\\n\\nF.I.Sh.: '+fio+'\\nFan-guruh: '+group+'\\nO‘quvchi kodi: '+d.code+'\\n\\nUshbu kodni o‘quvchiga yuboring.');await openSubject(sid)}catch(e){toast(e.message)}}
async function addSubject(){let name=prompt('Fan nomi:');if(!name)return;try{await api('/api/teacher/subject',{method:'POST',body:JSON.stringify({name,labels:['Test','Qo‘shimcha','Uy vazifasi']})});me=await api('/api/me');teacherHome();toast('Fan qo‘shildi')}catch(e){toast(e.message)}}
function studentHome(){shell('Mening natijalarim',me.subject||'O‘quvchi kabineti');let vals=[me.s1,me.s2,me.s3];document.getElementById('content').innerHTML='<div class="grid">'+vals.map((v,i)=>'<div class="card"><div class="label">Ball '+(i+1)+'</div><div class="stat">'+(v||0)+'/100</div></div>').join('')+'</div><div class="card"><div class="label">Guruh</div><h2>'+esc(me.group_name||'—')+'</h2><div class="row"><span class="pill">Davomat: '+esc(me.davomat||'—')+'</span><span class="pill">To‘lov: '+esc(me.payment_status||'—')+'</span></div><div class="divider"></div><div class="label">O‘qituvchi izohi</div><p>'+esc(me.teacher_note||'Izoh mavjud emas')+'</p><div class="muted small">Oxirgi yangilanish: '+esc(me.last_score_date||'—')+'</div></div>'}
function parentHome(){shell('Ota-ona kabineti','Farzandlaringizning natijalari va davomatini kuzating');let c=document.getElementById('content');if(!me.children.length){c.innerHTML='<div class="card muted">Hozircha biriktirilgan farzand topilmadi.</div>';return}c.innerHTML=me.children.map(ch=>'<div class="card"><div class="eyebrow">'+esc(ch.subject||'Fan')+'</div><h2>'+esc(ch.fio)+'</h2><div class="muted small">'+esc(ch.group_name)+'</div><div class="scores">'+[ch.s1,ch.s2,ch.s3].map((v,i)=>'<div class="card"><div class="label">Ball '+(i+1)+'</div><b>'+esc(v||0)+'/100</b></div>').join('')+'</div><div class="row"><span class="pill">Davomat: '+esc(ch.davomat)+'</span><span class="pill">To‘lov: '+esc(ch.payment_status)+'</span></div><p class="muted small">'+esc(ch.teacher_note||'')+'</p></div>').join('')}
function adminHome(){shell('Boshqaruv markazi','Faqat loyiha egasi uchun • Super Admin');let c=document.getElementById('content');let counts=me.counts||{};c.innerHTML='<div class="grid"><div class="card"><div class="label">O‘qituvchilar</div><div class="stat">'+(counts.teachers||0)+'</div></div><div class="card"><div class="label">O‘quvchilar</div><div class="stat">'+(counts.students||0)+'</div></div><div class="card"><div class="label">Ota-onalar</div><div class="stat">'+(counts.parents||0)+'</div></div></div><div class="section-title">O‘qituvchilar</div><div id="teachers"></div><div class="section-title">Tariflar</div><div id="plans"></div>';let ts=document.getElementById('teachers');(me.teachers||[]).forEach(t=>{let approved=t.verify_status==='approved'&&t.admin_approved;ts.innerHTML+='<div class="card"><b>'+esc((t.first_name||'')+' '+(t.last_name||''))+'</b><div class="muted small">'+esc(t.phone||'')+' • '+esc(t.plan_key||'free')+'</div><div class="pill">'+(approved?'Tasdiqlangan':'Tasdiq kutilmoqda')+'</div>'+(approved?'':'<button class="btn green full" onclick="approve('+t.id+')">Tasdiqlash</button>')+'</div>'});if(!(me.teachers||[]).length)ts.innerHTML='<div class="muted">O‘qituvchilar topilmadi.</div>';let ps=document.getElementById('plans');(me.plans||[]).forEach(p=>{ps.innerHTML+='<div class="card"><b>'+esc(p.name)+'</b><div class="muted small">'+Number(p.price).toLocaleString('uz-UZ')+' so‘m • '+esc(p.duration_days)+' kun • '+esc(p.student_limit)+' o‘quvchi</div><button class="btn secondary full" onclick="editPlan('+JSON.stringify(p.key)+')">Tarifni tahrirlash</button></div>'})}
async function approve(id){if(!confirm('O‘qituvchini tasdiqlaysizmi?'))return;try{await api('/api/admin/teacher/approve',{method:'POST',body:JSON.stringify({teacher_id:id})});me=await api('/api/me');adminHome();toast('O‘qituvchi tasdiqlandi')}catch(e){toast(e.message)}}
async function editPlan(key){let p=me.plans.find(x=>x.key===key);let price=prompt('Narx (so‘m):',p.price);if(price===null)return;let days=prompt('Muddat (kun):',p.duration_days);if(days===null)return;let limit=prompt('O‘quvchi limiti (0 = cheksiz):',p.student_limit);if(limit===null)return;try{await api('/api/admin/plan',{method:'POST',body:JSON.stringify({key,price:Number(price),duration_days:Number(days),student_limit:Number(limit)})});me=await api('/api/me');adminHome();toast('Tarif yangilandi')}catch(e){toast(e.message)}}
if(loginCode)startExchange(loginCode);else if(token)load();else showLogin();
</script></body></html>"""

@app.get("/mobile", response_class=HTMLResponse)
def mobile():
    return HTMLResponse(MOBILE_HTML)
