import os, json, time, hmac, hashlib, secrets, sqlite3, random
from datetime import datetime, timezone
from urllib.parse import parse_qsl
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

APP_SECRET = os.getenv("APP_SECRET", "CHANGE_THIS_TO_A_LONG_RANDOM_SECRET")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "tổ ayeuem")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
DB_PATH = os.getenv("DATABASE_PATH", "rau_ma_3636.db")
COOKIE_NAME = "rau_ma_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14
PROMO_CODE = "TEST"
PROMO_AMOUNT = 1_000_000
ADMIN_START_BALANCE = 2_000_000
ROUND_SECONDS = 80
BETTING_SECONDS = 60

app = FastAPI(title="Rau Má 3636 API")
app.mount("/static", StaticFiles(directory="static"), name="static")
serializer = URLSafeTimedSerializer(APP_SECRET, salt="rau-ma-session")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          telegram_id TEXT UNIQUE NOT NULL,
          telegram_name TEXT NOT NULL DEFAULT '',
          balance INTEGER NOT NULL DEFAULT 1000,
          is_admin INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL,
          last_daily INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS promo_uses(
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          code TEXT NOT NULL,
          used_at INTEGER NOT NULL,
          PRIMARY KEY(user_id, code)
        );
        CREATE TABLE IF NOT EXISTS bets(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          round_id INTEGER NOT NULL,
          side TEXT NOT NULL CHECK(side IN ('tai','xiu')),
          amount INTEGER NOT NULL,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rounds(
          round_id INTEGER PRIMARY KEY,
          dice TEXT NOT NULL,
          result TEXT NOT NULL,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          amount INTEGER NOT NULL,
          reason TEXT NOT NULL,
          created_at INTEGER NOT NULL
        );
        """)
init_db()

def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 250_000).hex()
    return f"{salt}${digest}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 250_000).hex()
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def verify_telegram_init_data(init_data: str) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(503, "Máy chủ chưa cấu hình TELEGRAM_BOT_TOKEN.")
    if not init_data:
        raise HTTPException(401, "Hãy mở Mini App từ bot Telegram.")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    supplied_hash = pairs.pop("hash", None)
    if not supplied_hash:
        raise HTTPException(401, "Telegram initData không hợp lệ.")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, supplied_hash):
        raise HTTPException(401, "Không xác minh được tài khoản Telegram.")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
        if abs(int(time.time()) - auth_date) > 86400:
            raise HTTPException(401, "Phiên Telegram đã hết hạn. Hãy mở lại Mini App.")
        user = json.loads(pairs.get("user", "{}"))
        if not user.get("id"):
            raise ValueError()
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Không đọc được thông tin Telegram.")

def session_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE id=?", (data.get("uid"),)).fetchone()
        return dict(row) if row else None

def require_user(request: Request):
    user = session_user(request)
    if not user:
        raise HTTPException(401, "Hãy đăng nhập trước.")
    return user

def require_admin(request: Request):
    user = require_user(request)
    if not user["is_admin"]:
        raise HTTPException(403, "Chỉ admin mới được sử dụng chức năng này.")
    return user

def current_round():
    now = int(time.time())
    rid = now // ROUND_SECONDS
    elapsed = now % ROUND_SECONDS
    phase = "betting" if elapsed < BETTING_SECONDS else "reveal"
    return rid, elapsed, phase, now

def ensure_round(round_id: int):
    with db() as con:
        exists = con.execute("SELECT round_id FROM rounds WHERE round_id=?", (round_id,)).fetchone()
        if exists:
            return
        # One shared result per round, generated server-side.
        dice = [random.randint(1, 6) for _ in range(3)]
        total = sum(dice)
        result = "tai" if total >= 11 else "xiu"
        con.execute("INSERT OR IGNORE INTO rounds(round_id,dice,result,created_at) VALUES(?,?,?,?)",
                    (round_id, json.dumps(dice), result, int(time.time())))
        # Settle bets once. Ties are not possible in this simple 3-dice rule.
        bets = con.execute("SELECT user_id, SUM(amount) AS total FROM bets WHERE round_id=? AND side=? GROUP BY user_id",
                           (round_id, result)).fetchall()
        for bet in bets:
            payout = int(bet["total"]) * 2
            con.execute("UPDATE users SET balance=balance+? WHERE id=?", (payout, bet["user_id"]))
            con.execute("INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)",
                        (bet["user_id"], payout, f"Thắng ván {round_id}", int(time.time())))

def public_user(u):
    return {
        "id": u["id"], "username": u["username"], "telegram_id": u["telegram_id"],
        "telegram_name": u["telegram_name"], "balance": u["balance"],
        "is_admin": bool(u["is_admin"]), "created_at": u["created_at"]
    }

class AuthBody(BaseModel):
    initData: str = ""
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

class BetBody(BaseModel):
    side: str
    amount: int = Field(gt=0, le=10_000_000)

class PromoBody(BaseModel):
    code: str

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse("static/index.html")

@app.get("/api/health")
def health():
    return {"ok": True, "app": "Rau Má 3636"}

@app.post("/api/register")
def register(body: AuthBody, response: Response):
    tg = verify_telegram_init_data(body.initData)
    username = body.username.strip()
    if not username or username.lower() == "admin":
        raise HTTPException(400, "Tên tài khoản không hợp lệ.")
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Máy chủ chưa đặt ADMIN_PASSWORD.")
    tg_id = str(tg["id"])
    tg_name = " ".join(x for x in [tg.get("first_name", ""), tg.get("last_name", "")] if x).strip() or tg.get("username", "")
    is_admin = int(username == ADMIN_USERNAME and verify_password(body.password, hash_password(ADMIN_PASSWORD, "admin-fixed-salt")))
    # Use the configured admin credentials only for the admin username.
    if username == ADMIN_USERNAME:
        if not verify_password(body.password, hash_password(ADMIN_PASSWORD, "admin-fixed-salt")):
            raise HTTPException(403, "Thông tin admin không đúng.")
        is_admin = 1
        starting_balance = ADMIN_START_BALANCE
    else:
        is_admin = 0
        starting_balance = 1000
    with db() as con:
        try:
            cur = con.execute("""INSERT INTO users(username,password_hash,telegram_id,telegram_name,balance,is_admin,created_at)
                                 VALUES(?,?,?,?,?,?,?)""",
                              (username, hash_password(body.password), tg_id, tg_name, starting_balance, is_admin, int(time.time())))
            uid = cur.lastrowid
            con.execute("INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)",
                        (uid, starting_balance, "Số dư khởi tạo", int(time.time())))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Tên tài khoản hoặc Telegram ID đã được đăng ký.")
    response.set_cookie(COOKIE_NAME, serializer.dumps({"uid": uid}), httponly=True, secure=True, samesite="none", max_age=SESSION_MAX_AGE)
    with db() as con:
        user = dict(con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return {"user": public_user(user)}

@app.post("/api/login")
def login(body: AuthBody, response: Response):
    tg = verify_telegram_init_data(body.initData)
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (body.username.strip(),)).fetchone()
        if not row or not verify_password(body.password, row["password_hash"]):
            raise HTTPException(401, "Sai tên tài khoản hoặc mật khẩu.")
        if str(row["telegram_id"]) != str(tg["id"]):
            raise HTTPException(403, "Tài khoản này được liên kết với Telegram ID khác.")
        tg_name = " ".join(x for x in [tg.get("first_name", ""), tg.get("last_name", "")] if x).strip() or tg.get("username", "")
        con.execute("UPDATE users SET telegram_name=? WHERE id=?", (tg_name, row["id"]))
    response.set_cookie(COOKIE_NAME, serializer.dumps({"uid": row["id"]}), httponly=True, secure=True, samesite="none", max_age=SESSION_MAX_AGE)
    return {"user": public_user(dict(row))}

@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, secure=True, samesite="none")
    return {"ok": True}

@app.get("/api/me")
def me(request: Request):
    user = session_user(request)
    return {"user": public_user(user) if user else None}

@app.post("/api/daily")
def daily(request: Request):
    user = require_user(request)
    now = int(time.time())
    with db() as con:
        row = con.execute("SELECT last_daily FROM users WHERE id=?", (user["id"],)).fetchone()
        if now - row["last_daily"] < 86400:
            raise HTTPException(400, "Hôm nay m đã nhận thưởng rồi.")
        con.execute("UPDATE users SET balance=balance+100,last_daily=? WHERE id=?", (now, user["id"]))
        con.execute("INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)",
                    (user["id"], 100, "Thưởng hằng ngày", now))
    return {"ok": True, "amount": 100}

@app.post("/api/promo")
def promo(body: PromoBody, request: Request):
    user = require_user(request)
    if body.code.strip().upper() != PROMO_CODE:
        raise HTTPException(400, "Mã khuyến mãi không đúng.")
    now = int(time.time())
    with db() as con:
        try:
            con.execute("INSERT INTO promo_uses(user_id,code,used_at) VALUES(?,?,?)", (user["id"], PROMO_CODE, now))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "M đã dùng mã này rồi.")
        con.execute("UPDATE users SET balance=balance+? WHERE id=?", (PROMO_AMOUNT, user["id"]))
        con.execute("INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)",
                    (user["id"], PROMO_AMOUNT, "Mã khuyến mãi TEST", now))
    return {"ok": True, "amount": PROMO_AMOUNT}

@app.get("/api/game/state")
def game_state(request: Request):
    user = require_user(request)
    rid, elapsed, phase, now = current_round()
    # Ensure the previous round has a settled result; current result only exists after betting closes.
    if phase == "reveal":
        ensure_round(rid)
    else:
        # Settle the previous round even if nobody opened the app during its reveal window.
        ensure_round(rid - 1)
    with db() as con:
        balance = con.execute("SELECT balance FROM users WHERE id=?", (user["id"],)).fetchone()["balance"]
        sums = con.execute("SELECT side,COALESCE(SUM(amount),0) AS amount FROM bets WHERE round_id=? GROUP BY side", (rid,)).fetchall()
        totals = {"tai": 0, "xiu": 0}
        for row in sums: totals[row["side"]] = row["amount"]
        my = con.execute("SELECT side,COALESCE(SUM(amount),0) AS amount FROM bets WHERE round_id=? AND user_id=? GROUP BY side",
                         (rid, user["id"])).fetchall()
        mybets = {"tai": 0, "xiu": 0}
        for row in my: mybets[row["side"]] = row["amount"]
        hist = con.execute("SELECT round_id,result,dice FROM rounds ORDER BY round_id DESC LIMIT 30").fetchall()
        result = con.execute("SELECT result,dice FROM rounds WHERE round_id=?", (rid,)).fetchone() if phase == "reveal" else None
    return {
        "round_id": rid, "phase": phase, "seconds_left": (BETTING_SECONDS-elapsed if phase=="betting" else ROUND_SECONDS-elapsed),
        "balance": balance, "totals": totals, "my_bets": mybets,
        "history": [{"round_id":r["round_id"],"result":r["result"],"dice":json.loads(r["dice"])} for r in hist],
        "result": ({"side":result["result"],"dice":json.loads(result["dice"])} if result else None),
        "rules": "Tài: tổng 11–18; Xỉu: tổng 3–10. Tiền ảo, không có nạp/rút tiền thật."
    }

@app.post("/api/game/bet")
def place_bet(body: BetBody, request: Request):
    user = require_user(request)
    side = body.side.lower()
    if side not in ("tai", "xiu"):
        raise HTTPException(400, "Chỉ chọn Tài hoặc Xỉu.")
    rid, elapsed, phase, now = current_round()
    if phase != "betting":
        raise HTTPException(400, "Đã hết thời gian đặt cược của ván này.")
    with db() as con:
        row = con.execute("SELECT balance FROM users WHERE id=?", (user["id"],)).fetchone()
        if body.amount > row["balance"]:
            raise HTTPException(400, "Số dư không đủ.")
        con.execute("UPDATE users SET balance=balance-? WHERE id=?", (body.amount, user["id"]))
        con.execute("INSERT INTO bets(user_id,round_id,side,amount,created_at) VALUES(?,?,?,?,?)",
                    (user["id"], rid, side, body.amount, now))
        con.execute("INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)",
                    (user["id"], -body.amount, f"Cược {side.upper()} ván {rid}", now))
    return {"ok": True}

@app.get("/api/admin/overview")
def admin_overview(request: Request):
    require_admin(request)
    with db() as con:
        count = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        total = con.execute("SELECT COALESCE(SUM(balance),0) AS n FROM users").fetchone()["n"]
        users = con.execute("SELECT id,username,telegram_id,telegram_name,balance,is_admin,created_at FROM users ORDER BY created_at DESC LIMIT 500").fetchall()
    return {"user_count": count, "total_balance": total, "users": [dict(u) for u in users]}

@app.get("/api/admin/user/{user_id}/transactions")
def admin_transactions(user_id: int, request: Request):
    require_admin(request)
    with db() as con:
        rows = con.execute("SELECT amount,reason,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)).fetchall()
    return {"transactions": [dict(r) for r in rows]}

@app.post("/api/admin/user/{user_id}/balance")
async def admin_balance(user_id: int, request: Request):
    require_admin(request)
    data = await request.json()
    amount = int(data.get("amount", 0))
    if amount == 0 or abs(amount) > 100_000_000:
        raise HTTPException(400, "Số tiền điều chỉnh không hợp lệ.")
    with db() as con:
        row = con.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not row: raise HTTPException(404, "Không tìm thấy người chơi.")
        con.execute("UPDATE users SET balance=MAX(0,balance+?) WHERE id=?", (amount, user_id))
        con.execute("INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)",
                    (user_id, amount, "Admin điều chỉnh số dư", int(time.time())))
    return {"ok": True}

@app.get("/api/admin/transactions")
def admin_all_transactions(request: Request):
    require_admin(request)
    with db() as con:
        rows = con.execute("""SELECT t.id,t.user_id,u.username,t.amount,t.reason,t.created_at
                              FROM transactions t JOIN users u ON u.id=t.user_id
                              ORDER BY t.id DESC LIMIT 200""").fetchall()
    return {"transactions": [dict(r) for r in rows]}
