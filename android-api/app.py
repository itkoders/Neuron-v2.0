import os, time, hmac, hashlib, json, secrets
from urllib.parse import urlencode
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import jwt
import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
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
    data = {k: str(v) for k, v in data.items() if k != "hash" and v is not None}
    received = str(data.get("hash", ""))
    # Telegram Login Widget HMAC verification
    check_data = dict(data)
    received = check_data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k,v in sorted(check_data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(expected, received):
        raise HTTPException(401, "Telegram imzosi noto'g'ri")
    try:
        uid = int(check_data["id"])
        auth_date = int(check_data["auth_date"])
    except Exception:
        raise HTTPException(401, "Telegram login ma'lumoti noto'g'ri")
    if auth_date > time.time() + 60 or time.time() - auth_date > 600:
        raise HTTPException(401, "Login muddati tugagan. Qayta kiring.")
    return uid, check_data

def roles_for(uid):
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            roles = []
            if uid == OWNER_ID:
                roles.append("super_admin")
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
                if student: roles.append("student")
            cur.execute("SELECT 1 FROM parent_children WHERE parent_chat_id=%s LIMIT 1", (uid,))
            if cur.fetchone(): roles.append("parent")
            return roles, teacher, student
    finally:
        conn.close()

def token_uid(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Kirish talab qilinadi")
    try:
        p = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
        return int(p["sub"]), p["role"]
    except Exception:
        raise HTTPException(401, "Sessiya yaroqsiz yoki muddati tugagan")

def require_role(authorization, allowed):
    uid, role = token_uid(authorization)
    if role not in allowed: raise HTTPException(403, "Ruxsat yo'q")
    return uid, role

@app.get("/health")
def health():
    return {"ok": True, "service": "neuron-android-api"}

@app.get("/login", response_class=HTMLResponse)
def login():
    if not BOT_TOKEN:
        return HTMLResponse("<h3>Server sozlamasi kutilmoqda</h3>", status_code=503)
    username = os.getenv("BOT_USERNAME", "Neuronv2_bot").lstrip("@")
    return HTMLResponse(f"""<!doctype html><html lang="uz"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>NEURON — Kirish</title><style>body{{margin:0;background:#0c1226;color:white;font:16px Arial;display:grid;place-items:center;min-height:100vh}}main{{text-align:center;padding:28px}}h1{{letter-spacing:5px}}p{{color:#bac5e3;line-height:1.6}}.panel{{background:#182342;border:1px solid #34446d;border-radius:22px;padding:28px;max-width:340px}}</style>
    <main><div class="panel"><h1>NEURON</h1><p>SMART JOURNAL</p><p>Telegram hisobingiz orqali xavfsiz kiring. Rol va ruxsatlar serverda tekshiriladi.</p>
    <script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-login="{username}" data-size="large" data-userpic="false" data-request-access="write" data-auth-url="/auth/telegram/callback"></script></div></main></html>""")

@app.get("/auth/telegram/callback")
async def telegram_callback(request: Request):
    data = dict(request.query_params)
    uid, _ = verified_user(data)
    roles, teacher, student = roles_for(uid)
    if not roles:
        raise HTTPException(403, "Bu Telegram hisobiga NEURON kabineti biriktirilmagan")
    code = secrets.token_urlsafe(32)
    LOGIN_CODES[code] = {"uid": uid, "roles": roles, "expires": time.time()+90}
    return RedirectResponse("neuron://auth?"+urlencode({"code":code}), status_code=302)

@app.post("/auth/exchange")
async def exchange(request: Request):
    body = await request.json()
    code = str(body.get("code", ""))
    item = LOGIN_CODES.pop(code, None)
    if not item or item["expires"] < time.time():
        raise HTTPException(401, "Kirish kodi eskirgan")
    roles = item["roles"]
    role = str(body.get("role") or (roles[0] if len(roles)==1 else ""))
    if role not in roles:
        raise HTTPException(403, "Tanlangan rolga ruxsat yo'q")
    token = jwt.encode({"sub":str(item["uid"]), "role":role, "iat":int(time.time()), "exp":int(time.time())+JWT_TTL}, JWT_SECRET, algorithm="HS256")
    return {"token":token, "role":role}

@app.get("/api/me")
def me(authorization: str = Header(default="")):
    uid, role = require_role(authorization, {"teacher","student","parent","super_admin"})
    roles, teacher, student = roles_for(uid)
    if role not in roles: raise HTTPException(403, "Rol endi faol emas")
    conn = db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if role == "teacher":
                cur.execute("SELECT id, name, label1, label2, label3 FROM subjects WHERE teacher_id=(SELECT id FROM teachers WHERE chat_id=%s) ORDER BY id", (uid,))
                subjects=cur.fetchall()
                cur.execute("SELECT first_name,last_name,plan_key,plan_expires FROM teachers WHERE chat_id=%s",(uid,))
                t=cur.fetchone()
                return {"role":role,"name":(t["first_name"]+" "+(t["last_name"] or "")).strip(),"plan":t["plan_key"],"expires":t["plan_expires"],"subjects":subjects}
            if role == "student":
                cur.execute("SELECT s.fio,s.group_name,s.s1,s.s2,s.s3,s.davomat,s.payment_status,s.teacher_note,s.last_score_date,sub.name AS subject FROM students s LEFT JOIN subjects sub ON sub.id=s.subject_id WHERE s.id=%s",(student["id"],))
                return {"role":role,**dict(cur.fetchone())}
            if role == "parent":
                cur.execute("SELECT s.id,s.fio,s.group_name,s.s1,s.s2,s.s3,s.davomat,s.payment_status,s.payment_amount,s.payment_date,s.teacher_note,sub.name AS subject FROM parent_children pc JOIN students s ON s.id=pc.student_id LEFT JOIN subjects sub ON sub.id=s.subject_id WHERE pc.parent_chat_id=%s ORDER BY s.fio",(uid,))
                return {"role":role,"children":cur.fetchall()}
            cur.execute("SELECT COUNT(*) AS teachers FROM teachers")
            counts=cur.fetchone()
            cur.execute("SELECT key,name,price,duration_days,active FROM plans ORDER BY price")
            plans=cur.fetchall()
            return {"role":role,"counts":counts,"plans":plans}
    finally:
        conn.close()

@app.get("/api/teacher/subject/{sid}")
def teacher_subject(sid:int, authorization:str=Header(default="")):
    uid,_=require_role(authorization,{"teacher"})
    conn=db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM teachers WHERE chat_id=%s",(uid,)); t=cur.fetchone()
            cur.execute("SELECT id,name,label1,label2,label3 FROM subjects WHERE id=%s AND teacher_id=%s",(sid,t["id"]))
            subject=cur.fetchone()
            if not subject: raise HTTPException(404,"Fan topilmadi")
            cur.execute("SELECT id,fio,group_name,s1,s2,s3,davomat,last_score_date FROM students WHERE teacher_id=%s AND subject_id=%s ORDER BY fio",(t["id"],sid))
            return {"subject":subject,"students":cur.fetchall()}
    finally: conn.close()

@app.post("/api/teacher/score")
async def teacher_score(request:Request, authorization:str=Header(default="")):
    uid,_=require_role(authorization,{"teacher"})
    b=await request.json()
    sid=int(b.get("student_id",0)); idx=int(b.get("idx",0)); value=int(b.get("value",-1))
    if idx not in (1,2,3) or not 0<=value<=100: raise HTTPException(400,"Ball 0–100 oralig'ida bo'lishi kerak")
    conn=db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM teachers WHERE chat_id=%s",(uid,)); t=cur.fetchone()
            cur.execute("SELECT id FROM students WHERE id=%s AND teacher_id=%s",(sid,t["id"]))
            if not cur.fetchone(): raise HTTPException(404,"O'quvchi topilmadi")
            cur.execute(f"UPDATE students SET s{idx}=%s,last_score_date=%s WHERE id=%s",(value,datetime.now().strftime("%d.%m.%Y"),sid))
        conn.commit()
        return {"ok":True}
    finally: conn.close()

@app.post("/api/teacher/attendance")
async def teacher_attendance(request:Request, authorization:str=Header(default="")):
    uid,_=require_role(authorization,{"teacher"})
    b=await request.json(); sid=int(b.get("student_id",0)); status=str(b.get("status",""))
    if status not in {"Keldi","Kelmadi","Sababli","Kutilmoqda"}: raise HTTPException(400,"Davomat holati noto'g'ri")
    conn=db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM teachers WHERE chat_id=%s",(uid,)); t=cur.fetchone()
            cur.execute("SELECT id FROM students WHERE id=%s AND teacher_id=%s",(sid,t["id"]))
            if not cur.fetchone(): raise HTTPException(404,"O'quvchi topilmadi")
            cur.execute("UPDATE students SET davomat=%s WHERE id=%s",(status,sid))
            cur.execute("INSERT INTO attendance_history(student_id,date_str,davomat,s1,s2,s3) SELECT id,%s,%s,s1,s2,s3 FROM students WHERE id=%s",(datetime.now().strftime("%d.%m.%Y"),status,sid))
        conn.commit(); return {"ok":True}
    finally: conn.close()
