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
OWNER_LOGIN = os.getenv("OWNER_LOGIN", "").strip().lower()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "")
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

def ensure_login_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS login_accounts (
            id BIGSERIAL PRIMARY KEY, role TEXT NOT NULL CHECK (role IN ('teacher','student','parent','super_admin')),
            teacher_id BIGINT, student_id BIGINT, parent_chat_id BIGINT,
            username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        cur.execute("ALTER TABLE login_accounts DROP CONSTRAINT IF EXISTS login_accounts_role_check")
        cur.execute("""ALTER TABLE login_accounts ADD CONSTRAINT login_accounts_role_check
            CHECK (role IN ('teacher','student','parent','super_admin'))""")
    if OWNER_LOGIN and OWNER_PASSWORD:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO login_accounts(role,username,password_hash)
                VALUES('super_admin',%s,%s) ON CONFLICT(username) DO NOTHING""",
                (OWNER_LOGIN, make_password_hash(OWNER_PASSWORD)))


def make_password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310000)
    return "pbkdf2_sha256$310000$" + salt.hex() + "$" + digest.hex()

def check_password(password, encoded):
    try:
        scheme, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256": return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(actual.hex(), digest_hex)
    except Exception: return False

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
            if uid < 0:
                cur.execute("SELECT id, teacher_id, subject_id, fio, group_name, s1, s2, s3, davomat, payment_status, teacher_note, last_score_date FROM students WHERE id=%s", (-uid,))
                student = cur.fetchone()
                return (["student"], None, student) if student else ([], None, None)
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


def ensure_journal_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS journal_lessons (
            id BIGSERIAL PRIMARY KEY, teacher_id BIGINT NOT NULL, subject_id BIGINT NOT NULL,
            title TEXT NOT NULL, lesson_date DATE NOT NULL DEFAULT CURRENT_DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        cur.execute("""CREATE TABLE IF NOT EXISTS journal_scores (
            id BIGSERIAL PRIMARY KEY, lesson_id BIGINT NOT NULL REFERENCES journal_lessons(id) ON DELETE CASCADE,
            student_id BIGINT NOT NULL, score SMALLINT CHECK (score BETWEEN 1 AND 5),
            note TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(lesson_id,student_id))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS journal_score_history (
            id BIGSERIAL PRIMARY KEY, lesson_id BIGINT NOT NULL, student_id BIGINT NOT NULL,
            old_score SMALLINT, new_score SMALLINT, changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_lessons_subject_date ON journal_lessons(subject_id,lesson_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_scores_student ON journal_scores(student_id,lesson_id)")


def enforce_teacher_quota(cur, tid, resource):
    field = "subject_limit" if resource == "subjects" else "student_limit"
    cur.execute("""SELECT t.plan_key,t.plan_expires,p.active,p.subject_limit,p.student_limit
        FROM teachers t LEFT JOIN plans p ON p.key=t.plan_key WHERE t.id=%s""",(tid,))
    plan=cur.fetchone()
    if not plan: raise HTTPException(403,"Tarif ma’lumoti topilmadi")
    if plan["active"] is False: raise HTTPException(403,"Tarif hozir faol emas")
    limit=int(plan[field] or 0)
    if limit <= 0: return
    cur.execute("SELECT COUNT(*) AS n FROM "+resource+" WHERE teacher_id=%s",(tid,))
    count=cur.fetchone()["n"]
    if count >= limit:
        raise HTTPException(403,"Tarif limitingiz tugagan. Tarifni yangilang.")

def teacher_id_for(cur, uid):
    cur.execute("SELECT id FROM teachers WHERE chat_id=%s AND active=1 AND verify_status='approved' AND admin_approved=1", (uid,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(403, "O'qituvchi hisobi tasdiqlanmagan")
    return row["id"]

@app.post("/auth/login")
async def password_login(request: Request):
    body = await request.json()
    username = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", ""))
    if not username or not password or len(username) > 80 or len(password) > 256:
        raise HTTPException(400, "Login va parolni kiriting")
    conn = db()
    try:
        ensure_login_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM login_accounts WHERE username=%s AND active=TRUE", (username,))
            account = cur.fetchone()
        if not account or not check_password(password, account["password_hash"]):
            raise HTTPException(401, "Login yoki parol noto‘g‘ri")
        role = account["role"]
        if role == "super_admin": uid = OWNER_ID
        elif role == "teacher":
            with conn.cursor() as cur:
                cur.execute("SELECT chat_id FROM teachers WHERE id=%s AND active=1 AND verify_status=%s AND admin_approved=1", (account["teacher_id"], "approved"))
                row = cur.fetchone()
            if not row: raise HTTPException(403, "O‘qituvchi hisobi hali tasdiqlanmagan")
            uid = int(row[0])
        elif role == "student": uid = -int(account["student_id"])
        else: uid = int(account["parent_chat_id"])
        roles, _, _ = roles_for(uid)
        if role not in roles: raise HTTPException(403, "Bu login uchun kabinet yoki ruxsat topilmadi")
        token = jwt.encode({"sub": str(uid), "role": role, "iat": int(time.time()), "exp": int(time.time()) + JWT_TTL}, JWT_SECRET, algorithm="HS256")
        return {"token": token, "role": role}
    finally: conn.close()

@app.post("/api/admin/login-account")
async def admin_login_account(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"super_admin"})
    if uid != OWNER_ID: raise HTTPException(403, "Faqat loyiha egasi")
    body = await request.json()
    role = str(body.get("role", ""))
    username = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", ""))
    if role not in {"teacher", "student", "parent"}: raise HTTPException(400, "Kabinet turi noto‘g‘ri")
    if len(username)<3 or len(username)>40 or not username.replace("_","").replace(".","").isalnum(): raise HTTPException(400, "Login 3–40 belgi: lotin harfi, raqam, nuqta yoki _")
    if len(password)<8 or len(password)>128: raise HTTPException(400, "Parol kamida 8 belgidan iborat bo‘lsin")
    conn=db()
    try:
        ensure_login_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            teacher_id=None; student_id=None; parent_chat_id=None
            if role=="teacher":
                teacher_id=int(body.get("teacher_id",0))
                cur.execute("SELECT id FROM teachers WHERE id=%s AND active=1 AND verify_status=%s AND admin_approved=1",(teacher_id,"approved"))
                if not cur.fetchone(): raise HTTPException(404, "Tasdiqlangan o‘qituvchi topilmadi")
            elif role=="student":
                student_id=int(body.get("student_id",0)); cur.execute("SELECT id FROM students WHERE id=%s",(student_id,))
                if not cur.fetchone(): raise HTTPException(404, "O‘quvchi topilmadi")
            else:
                parent_chat_id=int(body.get("parent_chat_id",0)); cur.execute("SELECT 1 FROM parent_children WHERE parent_chat_id=%s LIMIT 1",(parent_chat_id,))
                if not cur.fetchone(): raise HTTPException(404, "Bu ota-onaga farzand biriktirilmagan")
            cur.execute("""INSERT INTO login_accounts(role,teacher_id,student_id,parent_chat_id,username,password_hash)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(username) DO UPDATE SET role=EXCLUDED.role,teacher_id=EXCLUDED.teacher_id,
                student_id=EXCLUDED.student_id,parent_chat_id=EXCLUDED.parent_chat_id,password_hash=EXCLUDED.password_hash,active=TRUE,updated_at=NOW()""",
                (role,teacher_id,student_id,parent_chat_id,username,make_password_hash(password)))
        conn.commit(); return {"ok":True,"username":username,"role":role}
    finally: conn.close()

@app.post("/api/teacher/login-account")
async def teacher_login_account(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    body=await request.json()
    role=str(body.get("role","student")); username=str(body.get("username","")).strip().lower(); password=str(body.get("password",""))
    if role not in {"student","parent"}: raise HTTPException(400, "Faqat o‘quvchi yoki ota-ona kabineti yaratiladi")
    if len(username)<3 or len(username)>40 or not username.replace("_","").replace(".","").isalnum(): raise HTTPException(400, "Login 3–40 belgi: lotin harfi, raqam, nuqta yoki _")
    if len(password)<8 or len(password)>128: raise HTTPException(400, "Parol kamida 8 belgidan iborat bo‘lsin")
    conn=db()
    try:
        ensure_login_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid=teacher_id_for(cur,uid); student_id=None; parent_chat_id=None
            if role=="student":
                student_id=int(body.get("student_id",0)); cur.execute("SELECT id FROM students WHERE id=%s AND teacher_id=%s",(student_id,tid))
                if not cur.fetchone(): raise HTTPException(404, "Bu o‘qituvchiga tegishli o‘quvchi topilmadi")
            else:
                parent_chat_id=int(body.get("parent_chat_id",0))
                cur.execute("SELECT 1 FROM parent_children pc JOIN students s ON s.id=pc.student_id WHERE pc.parent_chat_id=%s AND s.teacher_id=%s LIMIT 1",(parent_chat_id,tid))
                if not cur.fetchone(): raise HTTPException(404, "Bu ota-onaga ushbu o‘qituvchining o‘quvchisi biriktirilmagan")
            cur.execute("""INSERT INTO login_accounts(role,teacher_id,student_id,parent_chat_id,username,password_hash)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(username) DO UPDATE SET role=EXCLUDED.role,teacher_id=EXCLUDED.teacher_id,
                student_id=EXCLUDED.student_id,parent_chat_id=EXCLUDED.parent_chat_id,password_hash=EXCLUDED.password_hash,active=TRUE,updated_at=NOW()""",
                (role,tid,student_id,parent_chat_id,username,make_password_hash(password)))
        conn.commit(); return {"ok":True,"username":username,"role":role}
    finally: conn.close()

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
                cur.execute("""SELECT t.first_name,t.last_name,t.plan_key,t.plan_expires,
                    COALESCE(p.student_limit,0) AS student_limit,COALESCE(p.subject_limit,0) AS subject_limit
                    FROM teachers t LEFT JOIN plans p ON p.key=t.plan_key WHERE t.id=%s""", (tid,))
                t = cur.fetchone()
                cur.execute("SELECT COUNT(*) AS total FROM students WHERE teacher_id=%s", (tid,))
                count = cur.fetchone()["total"]
                return {"role": role, "name": (t["first_name"] + " " + (t["last_name"] or "")).strip(), "plan": t["plan_key"], "expires": t["plan_expires"], "student_limit":t["student_limit"],"subject_limit":t["subject_limit"], "subjects": subjects, "student_count": count}
            if role == "student":
                ensure_journal_schema(conn)
                cur.execute("""SELECT s.id,s.fio,s.group_name,s.s1,s.s2,s.s3,s.davomat,s.payment_status,s.teacher_note,s.last_score_date,sub.name AS subject
                    FROM students s LEFT JOIN subjects sub ON sub.id=s.subject_id WHERE s.id=%s""", (student["id"],))
                result=dict(cur.fetchone())
                cur.execute("""SELECT jl.title,TO_CHAR(jl.lesson_date,'DD.MM.YYYY') AS lesson_date,js.score,js.note
                    FROM journal_lessons jl LEFT JOIN journal_scores js ON js.lesson_id=jl.id AND js.student_id=%s
                    WHERE jl.subject_id=%s ORDER BY jl.lesson_date DESC,jl.id DESC LIMIT 40""",(student["id"],student["subject_id"]))
                result["journal_grades"]=cur.fetchall()
                return {"role": role, **result}
            if role == "parent":
                ensure_journal_schema(conn)
                cur.execute("""SELECT s.id,s.fio,s.subject_id,s.group_name,s.s1,s.s2,s.s3,s.davomat,s.payment_status,s.payment_amount,s.payment_date,s.teacher_note,sub.name AS subject
                    FROM parent_children pc JOIN students s ON s.id=pc.student_id
                    JOIN teachers t ON t.id=s.teacher_id LEFT JOIN subjects sub ON sub.id=s.subject_id
                    WHERE pc.parent_chat_id=%s AND t.active=1 AND t.verify_status='approved' AND t.admin_approved=1 ORDER BY s.fio""", (uid,))
                children=cur.fetchall()
                for child in children:
                    cur.execute("""SELECT jl.title,TO_CHAR(jl.lesson_date,'DD.MM.YYYY') AS lesson_date,js.score,js.note
                        FROM journal_lessons jl LEFT JOIN journal_scores js ON js.lesson_id=jl.id AND js.student_id=%s
                        WHERE jl.subject_id=%s ORDER BY jl.lesson_date DESC,jl.id DESC LIMIT 40""",(child["id"],child["subject_id"]))
                    child["journal_grades"]=cur.fetchall()
                return {"role": role, "children": children}
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
            ensure_journal_schema(conn)
            cur.execute("SELECT id,name,label1,label2,label3 FROM subjects WHERE id=%s AND teacher_id=%s", (sid, tid))
            subject = cur.fetchone()
            if not subject:
                raise HTTPException(404, "Fan topilmadi")
            cur.execute("""SELECT id,fio,code,phone,group_name,s1,s2,s3,davomat,payment_status,payment_amount,payment_date,last_score_date,teacher_note,
                (SELECT pc.parent_chat_id FROM parent_children pc WHERE pc.student_id=students.id ORDER BY pc.id LIMIT 1) AS parent_chat_id
                FROM students WHERE teacher_id=%s AND subject_id=%s ORDER BY group_name,fio""", (tid, sid))
            students = cur.fetchall()
            cur.execute("""SELECT group_name,COUNT(*) AS student_count FROM students
                WHERE teacher_id=%s AND subject_id=%s GROUP BY group_name ORDER BY group_name""", (tid, sid))
            groups = cur.fetchall()
            cur.execute("""SELECT id,title,TO_CHAR(lesson_date,'YYYY-MM-DD') AS lesson_date
                FROM journal_lessons WHERE teacher_id=%s AND subject_id=%s
                ORDER BY lesson_date DESC,id DESC LIMIT 20""",(tid,sid))
            lessons = cur.fetchall()
            cur.execute("""SELECT js.lesson_id,js.student_id,js.score,js.note
                FROM journal_scores js JOIN journal_lessons jl ON jl.id=js.lesson_id
                WHERE jl.teacher_id=%s AND jl.subject_id=%s""",(tid,sid))
            scores = cur.fetchall()
            return {"subject": subject, "students": students, "groups": groups, "lessons": lessons, "journal_scores": scores}
    finally:
        conn.close()


@app.get("/api/teacher/subject/{sid}/report")
def journal_period_report(sid:int,period:str="quarter",authorization:str=Header(default="")):
    uid,_=require_role(authorization,{"teacher"})
    if period not in {"quarter","year"}: raise HTTPException(400,"Hisobot davri noto‘g‘ri")
    now=datetime.now()
    if period=="year":
        start=f"{now.year}-01-01"; end=f"{now.year+1}-01-01"
    else:
        q=(now.month-1)//3
        sm=q*3+1
        start=f"{now.year}-{sm:02d}-01"
        if sm==10: end=f"{now.year+1}-01-01"
        else: end=f"{now.year}-{sm+3:02d}-01"
    conn=db()
    try:
        ensure_journal_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid=teacher_id_for(cur,uid)
            cur.execute("SELECT id,name FROM subjects WHERE id=%s AND teacher_id=%s",(sid,tid))
            subject=cur.fetchone()
            if not subject: raise HTTPException(404,"Fan topilmadi")
            cur.execute("""SELECT s.id,s.fio,s.group_name,COUNT(js.score) AS lessons,
                ROUND(AVG(js.score)::numeric,2) AS average_score,
                COUNT(*) FILTER (WHERE js.score=5) AS fives,
                COUNT(*) FILTER (WHERE js.score=4) AS fours,
                COUNT(*) FILTER (WHERE js.score=3) AS threes,
                COUNT(*) FILTER (WHERE js.score=2) AS twos,
                COUNT(*) FILTER (WHERE js.score=1) AS ones
                FROM students s LEFT JOIN journal_lessons jl ON jl.subject_id=s.subject_id
                    AND jl.teacher_id=s.teacher_id AND jl.lesson_date >= %s AND jl.lesson_date < %s
                LEFT JOIN journal_scores js ON js.lesson_id=jl.id AND js.student_id=s.id
                WHERE s.teacher_id=%s AND s.subject_id=%s
                GROUP BY s.id,s.fio,s.group_name ORDER BY s.group_name,s.fio""",(start,end,tid,sid))
            rows=cur.fetchall()
            return {"subject":subject,"period":period,"start":start,"end":end,"students":rows}
    finally: conn.close()

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
            enforce_teacher_quota(cur, tid, "subjects")
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
            enforce_teacher_quota(cur, tid, "students")
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


@app.post("/api/teacher/lesson")
async def add_journal_lesson(request: Request, authorization: str = Header(default="")):
    uid, _ = require_role(authorization, {"teacher"})
    body = await request.json()
    sid = int(body.get("subject_id", 0))
    title = str(body.get("title", "")).strip()[:80]
    lesson_date = str(body.get("lesson_date", datetime.now().strftime("%Y-%m-%d")))
    if len(title) < 2: raise HTTPException(400, "Dars mavzusini kiriting")
    try: datetime.strptime(lesson_date, "%Y-%m-%d")
    except ValueError: raise HTTPException(400, "Sana formati noto‘g‘ri")
    conn=db()
    try:
        ensure_journal_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid=teacher_id_for(cur,uid)
            cur.execute("SELECT id FROM subjects WHERE id=%s AND teacher_id=%s",(sid,tid))
            if not cur.fetchone(): raise HTTPException(404,"Fan topilmadi")
            cur.execute("INSERT INTO journal_lessons(teacher_id,subject_id,title,lesson_date) VALUES(%s,%s,%s,%s) RETURNING id",(tid,sid,title,lesson_date))
            lesson_id=cur.fetchone()["id"]
        conn.commit()
        return {"ok":True,"id":lesson_id}
    finally: conn.close()

@app.post("/api/teacher/journal-score")
async def save_journal_score(request: Request, authorization: str = Header(default="")):
    uid,_=require_role(authorization,{"teacher"})
    body=await request.json()
    lesson_id=int(body.get("lesson_id",0)); student_id=int(body.get("student_id",0))
    raw=body.get("score")
    score=None if raw in (None,"","—") else int(raw)
    note=str(body.get("note","")).strip()[:500]
    if score is not None and score not in (1,2,3,4,5): raise HTTPException(400,"Baho 1 dan 5 gacha bo‘lsin")
    conn=db()
    try:
        ensure_journal_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid=teacher_id_for(cur,uid)
            cur.execute("""SELECT jl.id FROM journal_lessons jl JOIN students s ON s.subject_id=jl.subject_id
                WHERE jl.id=%s AND s.id=%s AND jl.teacher_id=%s AND s.teacher_id=%s""",(lesson_id,student_id,tid,tid))
            if not cur.fetchone(): raise HTTPException(404,"Dars yoki o‘quvchi topilmadi")
            cur.execute("SELECT score FROM journal_scores WHERE lesson_id=%s AND student_id=%s",(lesson_id,student_id))
            old=cur.fetchone()
            old_score=old["score"] if old else None
            if old_score != score:
                cur.execute("INSERT INTO journal_score_history(lesson_id,student_id,old_score,new_score) VALUES(%s,%s,%s,%s)",(lesson_id,student_id,old_score,score))
            cur.execute("""INSERT INTO journal_scores(lesson_id,student_id,score,note)
                VALUES(%s,%s,%s,%s) ON CONFLICT(lesson_id,student_id)
                DO UPDATE SET score=EXCLUDED.score,note=EXCLUDED.note,updated_at=NOW()""",(lesson_id,student_id,score,note))
        conn.commit()
        return {"ok":True,"score":score}
    finally: conn.close()

@app.get("/api/teacher/journal-history/{student_id}")
def journal_history(student_id:int,authorization:str=Header(default="")):
    uid,_=require_role(authorization,{"teacher"})
    conn=db()
    try:
        ensure_journal_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid=teacher_id_for(cur,uid)
            cur.execute("""SELECT jl.title,TO_CHAR(jl.lesson_date,'DD.MM.YYYY') AS lesson_date,
                h.old_score,h.new_score,TO_CHAR(h.changed_at,'DD.MM.YYYY HH24:MI') AS changed_at
                FROM journal_score_history h JOIN journal_lessons jl ON jl.id=h.lesson_id
                JOIN students s ON s.id=h.student_id WHERE h.student_id=%s AND jl.teacher_id=%s
                ORDER BY h.id DESC LIMIT 100""",(student_id,tid))
            return {"history":cur.fetchall()}
    finally: conn.close()

@app.post("/api/teacher/journal/send-parent-reports")
async def send_journal_parent_reports(request:Request,authorization:str=Header(default="")):
    uid,_=require_role(authorization,{"teacher"})
    if not BOT_TOKEN: raise HTTPException(503,"BOT_TOKEN sozlanmagan")
    body=await request.json()
    sid=int(body.get("subject_id",0)); group_name=str(body.get("group_name","")).strip()
    date=str(body.get("date",datetime.now().strftime("%Y-%m-%d")))
    try: datetime.strptime(date,"%Y-%m-%d")
    except ValueError: raise HTTPException(400,"Sana noto‘g‘ri")
    conn=db()
    try:
        ensure_journal_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tid=teacher_id_for(cur,uid)
            cur.execute("""SELECT s.id,s.fio,pc.parent_chat_id,jl.title,js.score,
                TO_CHAR(jl.lesson_date,'DD.MM.YYYY') AS lesson_date
                FROM students s JOIN parent_children pc ON pc.student_id=s.id
                JOIN journal_lessons jl ON jl.subject_id=s.subject_id AND jl.teacher_id=s.teacher_id
                LEFT JOIN journal_scores js ON js.lesson_id=jl.id AND js.student_id=s.id
                WHERE s.teacher_id=%s AND s.subject_id=%s AND s.group_name=%s AND jl.lesson_date=%s
                ORDER BY s.fio,jl.id""",(tid,sid,group_name,date))
            rows=cur.fetchall()
        if not rows: raise HTTPException(404,"Tanlangan guruhda bu sana uchun jurnal baholari topilmadi")
        grouped={}
        for row in rows:
            item=grouped.setdefault((row["id"],row["fio"],row["parent_chat_id"]),[])
            item.append((row["title"],row["score"]))
        sent=0
        async with httpx.AsyncClient(timeout=12) as client:
            for (_,fio,parent_id),items in grouped.items():
                lines=[f"📚 {title}: {'—' if score is None else str(score)}" for title,score in items]
                message="📊 NEURON — kunlik natija\\n👤 "+fio+"\\n\\n"+"\\n".join(lines)+"\\n\\nO‘qituvchingiz yubordi."
                response=await client.post("https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage",json={"chat_id":parent_id,"text":message})
                if response.is_success and response.json().get("ok"): sent+=1
        return {"ok":True,"sent":sent,"children":len(grouped)}
    finally: conn.close()

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
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#172544 0,#0b1020 58%);color:var(--txt);font:15px system-ui,-apple-system,Arial;min-height:100vh}button,input,select{font:inherit}button{cursor:pointer;border:0}.wrap{max-width:900px;margin:auto;padding:18px 15px 90px}.top{display:flex;align-items:center;justify-content:space-between;padding:12px 2px 20px}.brand{font-weight:900;letter-spacing:4px;font-size:22px}.subbrand{color:var(--muted);font-size:10px;letter-spacing:3px}.avatar{width:40px;height:40px;border-radius:14px;background:linear-gradient(135deg,#7187ff,#4bd2c8);display:grid;place-items:center;font-weight:900;color:#07101e}.hero{background:linear-gradient(125deg,#24365d,#182640 65%,#193c4c);border:1px solid #344b70;border-radius:24px;padding:22px;margin-bottom:16px;box-shadow:0 18px 55px #0003}.eyebrow{color:#a9c0ff;font-size:11px;letter-spacing:2px;font-weight:800}.hero h1{font-size:25px;margin:8px 0}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.card{background:linear-gradient(145deg,#17233d,#121b30);border:1px solid var(--line);border-radius:19px;padding:16px;margin:10px 0}.stat{font-size:26px;font-weight:850;margin-top:8px}.label{font-size:12px;color:var(--muted)}.section-title{font-size:18px;font-weight:800;margin:22px 2px 10px}.btn{padding:12px 15px;border-radius:13px;background:var(--blue);color:white;font-weight:750}.btn.secondary{background:#263655;color:#e7edff;border:1px solid #3a4c70}.btn.green{background:#1d765c}.btn.red{background:#803746}.btn.full{width:100%;margin-top:10px}.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.row>*{flex:1}.subject{display:flex;justify-content:space-between;align-items:center;width:100%;padding:16px;border-radius:16px;background:#182641;color:white;border:1px solid #334665;text-align:left;margin:7px 0}.subject{position:relative;overflow:hidden;min-height:104px;padding:20px 18px;background-size:cover;background-position:center}.subject:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(7,13,28,.96),rgba(7,13,28,.58) 65%,rgba(7,13,28,.28));z-index:0}.subject:after{position:absolute;right:14px;bottom:-20px;font-size:84px;opacity:.23;filter:drop-shadow(0 4px 12px #000);pointer-events:none}.subject>*{position:relative;z-index:1}.subject.history{background-image:linear-gradient(120deg,#4b291c,#a66b38 48%,#29354b)}.subject.history:after{content:"🏛️"}.subject.geography{background-image:linear-gradient(120deg,#123a43,#287b73 48%,#183d64)}.subject.geography:after{content:"🌍"}.subject.other{background-image:linear-gradient(120deg,#202c4c,#334c76 55%,#24344d)}.subject.other:after{content:"📚"}.subject-title{font-size:17px;font-weight:800;text-shadow:0 2px 8px #000}.subject-subtitle{display:block;font-size:11px;color:#d8e4f6;margin-top:7px;opacity:.9}.hero-history{background:linear-gradient(120deg,rgba(54,30,22,.97),rgba(130,78,42,.75)),radial-gradient(circle at 85% 20%,#d8a76a55,transparent 38%);border:1px solid #a87950}.hero-geography{background:linear-gradient(120deg,rgba(9,47,56,.97),rgba(25,105,98,.78)),radial-gradient(circle at 85% 20%,#8ee6ce55,transparent 38%);border:1px solid #3b9b8e}.subject-hero{padding:18px;border-radius:18px;margin:10px 0 16px;position:relative;overflow:hidden}.subject-hero:after{position:absolute;right:10px;bottom:-16px;font-size:76px;opacity:.24}.hero-history:after{content:"🏛️"}.hero-geography:after{content:"🌍"}.student{background:#15223a;border:1px solid #2c3e5e;border-radius:17px;padding:14px;margin:10px 0}.journal-scroll{overflow:auto;max-width:100%;border:1px solid var(--line);border-radius:14px;margin:12px 0;background:#111a2d}.journal-table{border-collapse:separate;border-spacing:0;min-width:100%;width:max-content;font-size:13px}.journal-table th,.journal-table td{padding:9px 8px;border-right:1px solid #2b3a58;border-bottom:1px solid #2b3a58;text-align:center;min-width:74px}.journal-table th{background:#1b2a47;color:#dce6ff;position:sticky;top:0;z-index:2}.journal-table th small,.journal-table td small{display:block;color:var(--muted);font-size:10px;margin-top:3px}.journal-table .sticky-col{position:sticky;left:0;z-index:3;min-width:38px;background:#192640}.journal-table .sticky-name{position:sticky;left:38px;z-index:3;text-align:left;min-width:145px;background:#192640}.journal-table th.sticky-name{z-index:4;background:#213354}.grade-cell,.attendance-cell{background:#0d172b;color:#fff;border:1px solid #3b5074;border-radius:8px;padding:8px;min-width:58px}.grade-cell.graded{border-color:#54d69b;background:#173b39}.student-tool{background:#15223a;border:1px solid #2c3e5e;border-radius:13px;padding:12px;margin:8px 0}.student-tool .row{margin-top:8px}.student-tool .btn{font-size:12px;padding:9px}.student h3{margin:0 0 4px;font-size:16px}.groupbar{display:flex;gap:8px;overflow-x:auto;padding:12px 0}.groupchip{white-space:nowrap;border:1px solid #354765;background:#111a2d;color:#cbd7ef;border-radius:999px;padding:10px 14px}.groupchip.active{background:#245bca;color:white;border-color:#4f83ef}.codebox{display:flex;align-items:center;justify-content:space-between;gap:8px;background:#0d172b;border:1px dashed #4b6b9e;border-radius:12px;padding:10px;margin:10px 0;flex-wrap:wrap}.scores{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}.field label{display:block;color:var(--muted);font-size:11px;margin-bottom:5px}.field input,.field select{width:100%;background:#0d172b;border:1px solid #35496c;border-radius:10px;padding:10px;color:white;min-width:0}.pill{display:inline-block;padding:5px 9px;border-radius:30px;background:#263756;color:#cbd8ff;font-size:11px}.ok{color:var(--green)}.warn{color:var(--amber)}.danger{color:var(--red)}.nav{position:fixed;bottom:0;left:0;right:0;background:#0d1528ed;backdrop-filter:blur(16px);border-top:1px solid #293958;display:flex;justify-content:center;gap:8px;padding:10px 12px calc(10px + env(safe-area-inset-bottom));z-index:5}.nav button{background:transparent;color:#9eaccb;padding:8px 13px;border-radius:12px;font-size:12px}.nav button.active{background:#26385c;color:white}.notice{padding:12px 14px;border-radius:13px;background:#392f20;color:#ffdaa0;margin:10px 0}.login{min-height:80vh;display:grid;place-items:center;text-align:center}.loginbox{max-width:390px;padding:30px 22px;background:#15213b;border:1px solid #304365;border-radius:25px}.hidden{display:none!important}.small{font-size:12px}.divider{height:1px;background:#2b3a58;margin:12px 0}.toast{position:fixed;top:12px;left:15px;right:15px;z-index:10;background:#25385a;border:1px solid #526b9a;padding:13px;border-radius:13px;text-align:center;display:none}@media(min-width:650px){.grid{grid-template-columns:repeat(4,minmax(0,1fr))}.student-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.student{margin:0}.wrap{padding-top:28px}}
</style></head><body><div id="toast" class="toast"></div><div class="wrap" id="app"></div><div id="nav" class="nav hidden"></div>
<script>
const app=document.getElementById('app'),nav=document.getElementById('nav');let token=localStorage.getItem('neuron_token')||'',role=localStorage.getItem('neuron_role')||'',me=null,activeSubject=null,subjectData=null,loginCode=new URLSearchParams(location.search).get('code');
const roleNames={teacher:"O‘qituvchi",student:"O‘quvchi",parent:"Ota-ona","super_admin":"Super Admin"};
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(s){let t=document.getElementById('toast');t.textContent=s;t.style.display='block';setTimeout(()=>t.style.display='none',2600)}
async function api(path,opts={}){let r=await fetch(path,{...opts,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token,...(opts.headers||{})}});let d=await r.json().catch(()=>({detail:'Server javobi xato'}));if(!r.ok)throw Error(d.detail||'Xatolik');return d}
function shell(title,sub){app.innerHTML='<div class="top"><div><div class="brand">NEURON</div><div class="subbrand">SMART JOURNAL</div></div><div class="avatar">'+esc((me?.name||roleNames[role]||'N').slice(0,1))+'</div></div><div class="hero"><div class="eyebrow">'+esc(roleNames[role]||'KABINET')+'</div><h1>'+esc(title)+'</h1><div class="muted">'+esc(sub||'Bilim • Natija • Rivojlanish')+'</div></div><div id="content"></div>';nav.classList.remove('hidden');nav.innerHTML='<button class="active" onclick="home()">⌂ Bosh sahifa</button><button onclick="refresh()">↻ Yangilash</button><button onclick="logout()">Chiqish</button>'}
function showLogin(msg){nav.classList.add('hidden');app.innerHTML='<div class="login"><div class="loginbox"><div class="brand">NEURON</div><div class="subbrand">SMART JOURNAL</div><h2>Kabinetga kirish</h2><p class="muted">Login va parolingizni kiriting.</p>'+(msg?'<div class="notice">'+esc(msg)+'</div>':'')+'<form onsubmit="passwordLogin(event)" style="text-align:left;margin-top:18px"><div class="field"><label>LOGIN</label><input id="loginUsername" autocomplete="username" autocapitalize="none" placeholder="Login" required></div><div class="field" style="margin-top:12px"><label>PAROL</label><input id="loginPassword" type="password" autocomplete="current-password" placeholder="Parol" required></div><button class="btn full" type="submit">Kirish</button></form><p class="muted small">Login va parolni administrator yoki o‘qituvchingizdan oling.</p></div></div>'}
async function passwordLogin(event){event.preventDefault();const username=document.getElementById('loginUsername').value.trim(),password=document.getElementById('loginPassword').value;try{const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});const d=await r.json().catch(()=>({detail:'Server javobi xato'}));if(!r.ok)throw Error(d.detail||'Kirish amalga oshmadi');token=d.token;role=d.role;localStorage.setItem('neuron_token',token);localStorage.setItem('neuron_role',role);await load()}catch(e){showLogin(e.message)}}
async function startExchange(code,chosen){try{let d=await api('/auth/exchange',{method:'POST',body:JSON.stringify({code,role:chosen||''})});if(d.choose_role){app.innerHTML='<div class="login"><div class="loginbox"><div class="brand">NEURON</div><h2>Kabinetni tanlang</h2><p class="muted">Ushbu Telegram hisobiga bir nechta rol biriktirilgan.</p>'+d.roles.map(x=>'<button class="btn full" onclick="startExchange('+JSON.stringify(code)+','+JSON.stringify(x)+')">'+esc(roleNames[x]||x)+'</button>').join('')+'</div></div>';return}token=d.token;role=d.role;localStorage.setItem('neuron_token',token);localStorage.setItem('neuron_role',role);history.replaceState({},'','/mobile');await load()}catch(e){showLogin(e.message)}}
async function load(){try{me=await api('/api/me');role=me.role;localStorage.setItem('neuron_role',role);home()}catch(e){logout(false);showLogin(e.message)}}
function logout(show=true){token='';role='';me=null;localStorage.removeItem('neuron_token');localStorage.removeItem('neuron_role');if(show)showLogin('Sessiya yakunlandi')}
async function refresh(){try{me=await api('/api/me');home();toast('Ma’lumotlar yangilandi')}catch(e){toast(e.message)}}
function home(){if(!me){load();return}if(role==='teacher')teacherHome();else if(role==='student')studentHome();else if(role==='parent')parentHome();else adminHome()}
function teacherHome(){shell('Xush kelibsiz, '+(me.name||'ustoz'),'Tarif: '+(me.plan||'—')+' • O‘quvchilar: '+(me.student_count||0));let c=document.getElementById('content');c.innerHTML='<div class="grid"><div class="card"><div class="label">O‘quvchilar</div><div class="stat">'+(me.student_count||0)+'</div></div><div class="card"><div class="label">Fanlar</div><div class="stat">'+me.subjects.length+'</div></div></div><div class="section-title">Fanlar jurnali</div><div id="subjects"></div><button class="btn full" onclick="addSubject()">＋ Yangi fan qo‘shish</button>';let s=document.getElementById('subjects');if(!me.subjects.length)s.innerHTML='<div class="card muted">Hozircha fan qo‘shilmagan.</div>';me.subjects.forEach(x=>{let n=(x.name||'').toLowerCase();let kind=n.includes('tarix')?'history':(n.includes('geograf')?'geography':'other');let sub=kind==='history'?'Tarixiy manbalar va darslar':kind==='geography'?'Xaritalar va geografik bilimlar':'Fan jurnali va o‘quvchilar';s.innerHTML+='<button class="subject '+kind+'" onclick="openSubject('+x.id+')"><span><span class="subject-title">'+esc(x.name)+'</span><span class="subject-subtitle">'+sub+'</span></span><span>›</span></button>'})}
async function openSubject(id){try{activeSubject=id;subjectData=await api('/api/teacher/subject/'+id);let c=document.getElementById('content');let sub=subjectData.subject;let subjectKind=(sub.name||'').toLowerCase().includes('tarix')?'history':((sub.name||'').toLowerCase().includes('geograf')?'geography':'other');let subjectHero=subjectKind==='history'?'hero-history':(subjectKind==='geography'?'hero-geography':'');c.innerHTML='<button class="btn secondary" onclick="teacherHome()">← Fanlar</button><div class="subject-hero '+subjectHero+'"><div class="subject-title">'+esc(sub.name)+'</div><div class="subject-subtitle">NEURON SMART JOURNAL • Elektron jurnal</div></div><div class="muted small">Excel kabi jadval: har bir dars alohida ustun, har bir o‘quvchi alohida satr. Baholar 1–5.</div><div class="row" style="margin-top:12px"><button class="btn" onclick="addJournalLesson('+id+')">＋ Dars ustuni</button><button class="btn secondary" onclick="addStudent('+id+')">＋ O‘quvchi</button></div><div class="row"><button class="btn secondary" onclick="sendParentReports()">Ota-onalarga kunlik hisobot</button><button class="btn secondary" onclick="exportJournalCsv()">Excel/CSV yuklash</button><button class="btn secondary" onclick="showPeriodReport()">Chorak/yil hisoboti</button></div><input id="journalSearch" placeholder="O‘quvchini qidirish..." oninput="renderGroupJournal(window.activeGroup||\'Barchasi\')" style="width:100%;margin-top:12px;background:#0d172b;border:1px solid #35496c;border-radius:12px;padding:12px;color:white"><div class="groupbar" id="groupbar"></div><div id="journalMeta" class="muted small"></div><div class="journal-scroll"><table class="journal-table" id="journalTable"></table></div><div class="section-title">O‘quvchi boshqaruvi</div><div id="studentTools"></div>';renderGroupJournal('Barchasi')}catch(e){toast(e.message)}}

async function showPeriodReport(){let period=prompt('Hisobot davri: quarter — chorak, year — yil','quarter');if(!period)return;if(!['quarter','year'].includes(period)){toast('quarter yoki year deb kiriting');return}try{let d=await api('/api/teacher/subject/'+activeSubject+'/report?period='+period);let c=document.getElementById('content');c.innerHTML='<button class="btn secondary" onclick="openSubject('+activeSubject+')">← Jurnalga qaytish</button><div class="section-title">'+esc(d.subject.name)+' — '+(period==='year'?'Yillik':'Choraklik')+' hisobot</div><div class="muted small">'+esc(d.start)+' — '+esc(d.end)+'</div><div class="journal-scroll"><table class="journal-table"><thead><tr><th>O‘quvchi</th><th>Guruh</th><th>Baholangan dars</th><th>O‘rtacha</th><th>5</th><th>4</th><th>3</th><th>2</th><th>1</th></tr></thead><tbody>'+d.students.map(s=>'<tr><td>'+esc(s.fio)+'</td><td>'+esc(s.group_name||'—')+'</td><td>'+s.lessons+'</td><td><b>'+(s.average_score??'—')+'</b></td><td>'+s.fives+'</td><td>'+s.fours+'</td><td>'+s.threes+'</td><td>'+s.twos+'</td><td>'+s.ones+'</td></tr>').join('')+'</tbody></table></div>'}catch(e){toast(e.message)}}
async function addJournalLesson(sid){let title=prompt('Dars mavzusi yoki ustun nomi:');if(!title)return;let date=prompt('Sana (YYYY-MM-DD):',new Date().toISOString().slice(0,10));if(!date)return;try{await api('/api/teacher/lesson',{method:'POST',body:JSON.stringify({subject_id:sid,title,lesson_date:date})});await openSubject(sid);toast('Jurnalga yangi dars ustuni qo‘shildi')}catch(e){toast(e.message)}}
function journalScore(studentId,lessonId){let x=(subjectData.journal_scores||[]).find(v=>Number(v.student_id)===Number(studentId)&&Number(v.lesson_id)===Number(lessonId));return x&&x.score!==null?String(x.score):''}
async function saveJournalScore(studentId,lessonId,value,el){try{await api('/api/teacher/journal-score',{method:'POST',body:JSON.stringify({student_id:studentId,lesson_id:lessonId,score:value||null})});let x=(subjectData.journal_scores||[]).find(v=>Number(v.student_id)===Number(studentId)&&Number(v.lesson_id)===Number(lessonId));if(x)x.score=value?Number(value):null;else subjectData.journal_scores.push({student_id:studentId,lesson_id:lessonId,score:value?Number(value):null});if(el){el.classList.toggle('graded',!!value)}toast(value?'Baho saqlandi':'Baho tozalandi')}catch(e){toast(e.message);if(el)el.value=''}}
function renderGroupJournal(selected){window.activeGroup=selected;let bar=document.getElementById('groupbar'),table=document.getElementById('journalTable');if(!bar||!table)return;let groups=[...new Set((subjectData.groups||[]).map(x=>x.group_name||'Guruhsiz'))];let opts=['Barchasi',...groups];bar.innerHTML=opts.map(g=>'<button class="groupchip '+(g===selected?'active':'')+'" onclick="renderGroupJournal('+JSON.stringify(g)+')">'+esc(g)+(g==='Barchasi'?'':' · '+((subjectData.groups.find(x=>(x.group_name||'Guruhsiz')===g)||{}).student_count||0))+'</button>').join('');let query=(document.getElementById('journalSearch')?.value||'').toLowerCase();let rows=(subjectData.students||[]).filter(st=>(selected==='Barchasi'||(st.group_name||'Guruhsiz')===selected)&&st.fio.toLowerCase().includes(query));let lessons=(subjectData.lessons||[]).slice().reverse();document.getElementById('journalMeta').textContent=rows.length+' nafar o‘quvchi • '+lessons.length+' ta dars ustuni';let head='<thead><tr><th class="sticky-col">№</th><th class="sticky-name">O‘quvchi</th>'+lessons.map(l=>'<th><div>'+esc(l.title)+'</div><small>'+esc(l.lesson_date)+'</small></th>').join('')+'<th>Davomat</th></tr></thead>';let body=rows.map((st,i)=>'<tr><td class="sticky-col">'+(i+1)+'</td><td class="sticky-name"><b>'+esc(st.fio)+'</b><small>'+esc(st.group_name||'Guruhsiz')+'</small></td>'+lessons.map(l=>{let val=journalScore(st.id,l.id);return '<td><select class="grade-cell '+(val?'graded':'')+'" aria-label="'+esc(st.fio)+' bahosi" onchange="saveJournalScore('+st.id+','+l.id+',this.value,this)"><option value="">—</option>'+[1,2,3,4,5].map(n=>'<option value="'+n+'" '+(val===String(n)?'selected':'')+'>'+n+'</option>').join('')+'</select></td>'}).join('')+'<td><select class="attendance-cell" onchange="saveAttendanceQuick('+st.id+',this.value)">'+['Keldi','Kelmadi','Sababli','Kutilmoqda'].map(x=>'<option '+(st.davomat===x?'selected':'')+'>'+x+'</option>').join('')+'</select></td></tr>').join('');table.innerHTML=head+'<tbody>'+(body||'<tr><td colspan="'+(lessons.length+3)+'">Bu guruhda o‘quvchilar yo‘q.</td></tr>')+'</tbody>';let tools=document.getElementById('studentTools');if(tools)tools.innerHTML=rows.map(st=>'<div class="student-tool"><b>'+esc(st.fio)+'</b><div class="muted small">'+esc(st.group_name||'Guruhsiz')+' • Kod: '+esc(st.code||'—')+'</div><div class="row"><button class="btn secondary" onclick="setStudentLogin('+st.id+')">O‘quvchi login/paroli</button>'+(st.parent_chat_id?'<button class="btn secondary" onclick="setParentLogin('+JSON.stringify(st.parent_chat_id)+')">Ota-ona login/paroli</button>':'')+'<button class="btn secondary" onclick="showJournalHistory('+st.id+')">Baho tarixi</button></div></div>').join('')}
async function saveAttendanceQuick(id,status){try{await api('/api/teacher/attendance',{method:'POST',body:JSON.stringify({student_id:id,status})});let st=subjectData.students.find(x=>x.id===id);if(st)st.davomat=status;toast('Davomat saqlandi')}catch(e){toast(e.message)}}
async function showJournalHistory(id){try{let d=await api('/api/teacher/journal-history/'+id);let rows=d.history||[];alert(rows.length?rows.map(x=>x.changed_at+' • '+x.title+' • '+(x.old_score??'—')+' → '+(x.new_score??'—')).join('\n'):'Baho tarixi hozircha bo‘sh')}catch(e){toast(e.message)}}
async function sendParentReports(){let group=window.activeGroup||'Barchasi';if(group==='Barchasi'){toast('Avval bitta guruhni tanlang');return}if(!confirm(group+' guruhidagi ota-onalarga bugungi baholar yuborilsinmi?'))return;try{let d=await api('/api/teacher/journal/send-parent-reports',{method:'POST',body:JSON.stringify({subject_id:activeSubject,group_name:group,date:new Date().toISOString().slice(0,10)})});toast(d.sent+' ta ota-onaga hisobot yuborildi')}catch(e){toast(e.message)}}
function exportJournalCsv(){let lessons=(subjectData.lessons||[]).slice().reverse(),rows=[['O‘quvchi','Guruh',...lessons.map(x=>x.title),'Davomat']];(subjectData.students||[]).forEach(st=>rows.push([st.fio,st.group_name||'',...lessons.map(l=>journalScore(st.id,l.id)||''),st.davomat||'']));let csv='\uFEFF'+rows.map(r=>r.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(';')).join('\r\n');let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));a.download='NEURON-'+(subjectData.subject.name||'Jurnal')+'.csv';a.click();URL.revokeObjectURL(a.href)}
async function addStudent(sid){let fio=prompt('O‘quvchi F.I.O.:');if(!fio)return;let group=prompt('Qaysi guruhga qo‘shilsin? Masalan: Tarix 1-guruh', '1-guruh')||'Guruhsiz';try{let d=await api('/api/teacher/student',{method:'POST',body:JSON.stringify({subject_id:sid,fio,group_name:group})});alert('O‘quvchi muvaffaqiyatli qo‘shildi!\\n\\nF.I.Sh.: '+fio+'\\nFan-guruh: '+group+'\\nO‘quvchi kodi: '+d.code+'\\n\\nUshbu kodni o‘quvchiga yuboring.');await openSubject(sid)}catch(e){toast(e.message)}}
async function addSubject(){let name=prompt('Fan nomi:');if(!name)return;try{await api('/api/teacher/subject',{method:'POST',body:JSON.stringify({name,labels:['Test','Qo‘shimcha','Uy vazifasi']})});me=await api('/api/me');teacherHome();toast('Fan qo‘shildi')}catch(e){toast(e.message)}}
function studentHome(){shell('Mening natijalarim',me.subject||'O‘quvchi kabineti');let grades=me.journal_grades||[];document.getElementById('content').innerHTML='<div class="card"><div class="label">Fan va guruh</div><h2>'+esc(me.subject||'—')+'</h2><div class="pill">'+esc(me.group_name||'Guruh ko‘rsatilmagan')+'</div><div class="row" style="margin-top:10px"><span class="pill">Davomat: '+esc(me.davomat||'—')+'</span><span class="pill">To‘lov: '+esc(me.payment_status||'—')+'</span></div></div><div class="section-title">Elektron jurnal baholari</div>'+(grades.length?grades.map(g=>'<div class="student-tool"><b>'+esc(g.title)+'</b><div class="muted small">'+esc(g.lesson_date)+'</div><div class="stat">'+(g.score===null?'—':esc(g.score)+'/5')+'</div>'+(g.note?'<p>'+esc(g.note)+'</p>':'')+'</div>').join(''):'<div class="card muted">Hozircha baholar kiritilmagan.</div>')+'<div class="card"><div class="label">O‘qituvchi izohi</div><p>'+esc(me.teacher_note||'Izoh mavjud emas')+'</p></div>'}
function parentHome(){shell('Ota-ona kabineti','Farzandlaringizning natijalari va davomatini kuzating');let c=document.getElementById('content');if(!me.children.length){c.innerHTML='<div class="card muted">Hozircha biriktirilgan farzand topilmadi.</div>';return}c.innerHTML=me.children.map(ch=>'<div class="card"><div class="eyebrow">'+esc(ch.subject||'Fan')+'</div><h2>'+esc(ch.fio)+'</h2><div class="muted small">'+esc(ch.group_name)+'</div><div class="row"><span class="pill">Davomat: '+esc(ch.davomat)+'</span><span class="pill">To‘lov: '+esc(ch.payment_status)+'</span></div><div class="section-title">Jurnal baholari</div>'+(ch.journal_grades||[]).map(g=>'<div class="row"><span>'+esc(g.title)+' <small class="muted">'+esc(g.lesson_date)+'</small></span><b>'+(g.score===null?'—':esc(g.score)+'/5')+'</b></div>').join('')+'<p class="muted small">'+esc(ch.teacher_note||'')+'</p></div>').join('')}
function adminHome(){shell('Boshqaruv markazi','Faqat loyiha egasi uchun • Super Admin');let c=document.getElementById('content');let counts=me.counts||{};c.innerHTML='<div class="grid"><div class="card"><div class="label">O‘qituvchilar</div><div class="stat">'+(counts.teachers||0)+'</div></div><div class="card"><div class="label">O‘quvchilar</div><div class="stat">'+(counts.students||0)+'</div></div><div class="card"><div class="label">Ota-onalar</div><div class="stat">'+(counts.parents||0)+'</div></div></div><div class="section-title">O‘qituvchilar</div><div id="teachers"></div><div class="section-title">Tariflar</div><div id="plans"></div>';let ts=document.getElementById('teachers');(me.teachers||[]).forEach(t=>{let approved=t.verify_status==='approved'&&t.admin_approved;ts.innerHTML+='<div class="card"><b>'+esc((t.first_name||'')+' '+(t.last_name||''))+'</b><div class="muted small">'+esc(t.phone||'')+' • '+esc(t.plan_key||'free')+'</div><div class="pill">'+(approved?'Tasdiqlangan':'Tasdiq kutilmoqda')+'</div>'+(approved?'<button class="btn secondary full" onclick="setTeacherLogin('+t.id+')">Login/parol belgilash</button>':'<button class="btn green full" onclick="approve('+t.id+')">Tasdiqlash</button>')+'</div>'});if(!(me.teachers||[]).length)ts.innerHTML='<div class="muted">O‘qituvchilar topilmadi.</div>';let ps=document.getElementById('plans');(me.plans||[]).forEach(p=>{ps.innerHTML+='<div class="card"><b>'+esc(p.name)+'</b><div class="muted small">'+Number(p.price).toLocaleString('uz-UZ')+' so‘m • '+esc(p.duration_days)+' kun • '+esc(p.student_limit)+' o‘quvchi • '+esc(p.subject_limit)+' fan</div><button class="btn secondary full" onclick="editPlan('+JSON.stringify(p.key)+')">Tarifni tahrirlash</button></div>'})}

async function setTeacherLogin(id){const username=prompt('O‘qituvchi uchun login (3–40 belgi):');if(!username)return;const password=prompt('Parol (kamida 8 belgi):');if(!password)return;try{await api('/api/admin/login-account',{method:'POST',body:JSON.stringify({role:'teacher',teacher_id:id,username,password})});toast('O‘qituvchi login/paroli saqlandi')}catch(e){toast(e.message)}}
async function setStudentLogin(id){const username=prompt('O‘quvchi uchun login (3–40 belgi):');if(!username)return;const password=prompt('Parol (kamida 8 belgi):');if(!password)return;try{await api('/api/teacher/login-account',{method:'POST',body:JSON.stringify({role:'student',student_id:id,username,password})});toast('O‘quvchi login/paroli saqlandi')}catch(e){toast(e.message)}}
async function setParentLogin(parent_chat_id){const username=prompt('Ota-ona uchun login (3–40 belgi):');if(!username)return;const password=prompt('Parol (kamida 8 belgi):');if(!password)return;try{await api('/api/teacher/login-account',{method:'POST',body:JSON.stringify({role:'parent',parent_chat_id,username,password})});toast('Ota-ona login/paroli saqlandi')}catch(e){toast(e.message)}}

async function approve(id){if(!confirm('O‘qituvchini tasdiqlaysizmi?'))return;try{await api('/api/admin/teacher/approve',{method:'POST',body:JSON.stringify({teacher_id:id})});me=await api('/api/me');adminHome();toast('O‘qituvchi tasdiqlandi')}catch(e){toast(e.message)}}
async function editPlan(key){let p=me.plans.find(x=>x.key===key);let price=prompt('Narx (so‘m):',p.price);if(price===null)return;let days=prompt('Muddat (kun):',p.duration_days);if(days===null)return;let limit=prompt('O‘quvchi limiti (0 = cheksiz):',p.student_limit);if(limit===null)return;let subjects=prompt('Fan limiti (0 = cheksiz):',p.subject_limit??0);if(subjects===null)return;try{await api('/api/admin/plan',{method:'POST',body:JSON.stringify({key,price:Number(price),duration_days:Number(days),student_limit:Number(limit),subject_limit:Number(subjects)})});me=await api('/api/me');adminHome();toast('Tarif yangilandi')}catch(e){toast(e.message)}}
if(token)load();else showLogin();
</script></body></html>"""

@app.get("/mobile", response_class=HTMLResponse)
def mobile():
    return HTMLResponse(MOBILE_HTML)
