from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import requests, os, random, hashlib, jwt, datetime, psycopg2
import psycopg2.extras, uuid
from functools import wraps

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
DATABASE_URL      = os.environ.get("DATABASE_URL", "")
JWT_SECRET        = os.environ.get("JWT_SECRET", "change-me-please-123")
YUKASSA_SHOP_ID   = os.environ.get("YUKASSA_SHOP_ID", "")
YUKASSA_SECRET    = os.environ.get("YUKASSA_SECRET", "")
SITE_URL          = os.environ.get("SITE_URL", "https://daring-smm.ru")
GOOGLE_CLIENT_ID  = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
FREE_LIMIT        = 10
DEEPSEEK_URL      = "https://api.deepseek.com/v1/chat/completions"
GOOGLE_REDIRECT   = "https://web-production-3a26.up.railway.app/auth/google/callback"


# ── БД ───────────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def init_db():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            google_id TEXT,
            name TEXT,
            avatar TEXT,
            free_left INTEGER DEFAULT 10,
            is_paid BOOLEAN DEFAULT FALSE,
            paid_until TIMESTAMP,
            total_generated INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            yukassa_id TEXT,
            amount NUMERIC,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            niche TEXT,
            archetype TEXT,
            cat TEXT,
            tone TEXT,
            topic TEXT,
            result TEXT,
            strategy TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit(); cur.close(); conn.close()

try:
    init_db()
except Exception as e:
    print(f"DB init: {e}")


# ── AUTH HELPERS ──────────────────────────────────────────────────────────────

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def make_token(uid, email):
    return jwt.encode({
        "user_id": str(uid), "email": email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=30)
    }, JWT_SECRET, algorithm="HS256")

def require_auth(f):
    @wraps(f)
    def wrap(*a, **kw):
        token = request.headers.get("Authorization","").replace("Bearer ","").strip()
        if not token:
            return jsonify({"error":"Нужна авторизация"}), 401
        try:
            p = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.user_id = p["user_id"]
            request.user_email = p["email"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error":"Сессия истекла, войди снова"}), 401
        except:
            return jsonify({"error":"Неверный токен"}), 401
        return f(*a, **kw)
    return wrap

def get_user(uid):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    u = cur.fetchone(); cur.close(); conn.close()
    return u

def check_access(user):
    now = datetime.datetime.utcnow()
    if user["is_paid"] and user["paid_until"] and user["paid_until"] > now:
        return True, None
    if user["free_left"] > 0:
        return True, None
    return False, "free_limit"


# ── EMAIL AUTH ────────────────────────────────────────────────────────────────

@app.route("/register", methods=["POST"])
def register():
    d = request.json or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""
    if not email or "@" not in email:
        return jsonify({"error":"Введи корректный email"}), 400
    if len(pw) < 6:
        return jsonify({"error":"Пароль минимум 6 символов"}), 400
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email,password_hash) VALUES (%s,%s) RETURNING id,email,free_left,is_paid",
            (email, hash_pw(pw))
        )
        u = cur.fetchone(); conn.commit()
        return jsonify({"token": make_token(u["id"],u["email"]),
                        "email": u["email"], "free_left": u["free_left"],
                        "is_paid": False, "name": None, "avatar": None})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"error":"Этот email уже зарегистрирован"}), 409
    finally:
        cur.close(); conn.close()


@app.route("/login", methods=["POST"])
def login():
    d = request.json or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email=%s", (email,))
    u = cur.fetchone(); cur.close(); conn.close()
    if not u or not u["password_hash"] or u["password_hash"] != hash_pw(pw):
        return jsonify({"error":"Неверный email или пароль"}), 401
    return jsonify({
        "token":      make_token(u["id"], u["email"]),
        "email":      u["email"],
        "free_left":  u["free_left"],
        "is_paid":    u["is_paid"],
        "name":       u["name"],
        "avatar":     u["avatar"],
        "paid_until": u["paid_until"].isoformat() if u["paid_until"] else None
    })


# ── GOOGLE OAUTH ──────────────────────────────────────────────────────────────

@app.route("/auth/google")
def google_login():
    params = (
        f"client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@app.route("/auth/google/callback")
def google_callback():
    code = request.args.get("code")
    if not code:
        return redirect(f"{SITE_URL}?error=no_code")

    # Меняем code на токен
    token_resp = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT,
        "grant_type": "authorization_code"
    })
    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return redirect(f"{SITE_URL}?error=no_token")

    # Получаем данные пользователя
    user_resp = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                             headers={"Authorization": f"Bearer {access_token}"})
    guser = user_resp.json()
    google_id = guser.get("id")
    email     = guser.get("email", "").lower()
    name      = guser.get("name")
    avatar    = guser.get("picture")

    if not email:
        return redirect(f"{SITE_URL}?error=no_email")

    conn = get_db(); cur = conn.cursor()
    # Ищем существующего пользователя по email или google_id
    cur.execute("SELECT * FROM users WHERE email=%s OR google_id=%s", (email, google_id))
    u = cur.fetchone()

    if u:
        # Обновляем google данные если вошли впервые через Google
        cur.execute(
            "UPDATE users SET google_id=%s, name=%s, avatar=%s WHERE id=%s RETURNING id,email,free_left,is_paid,paid_until",
            (google_id, name, avatar, u["id"])
        )
        u = cur.fetchone()
    else:
        # Создаём нового пользователя
        cur.execute(
            "INSERT INTO users (email,google_id,name,avatar) VALUES (%s,%s,%s,%s) RETURNING id,email,free_left,is_paid,paid_until",
            (email, google_id, name, avatar)
        )
        u = cur.fetchone()

    conn.commit(); cur.close(); conn.close()

    jwt_token = make_token(u["id"], u["email"])
    # Редиректим на сайт с токеном в URL
    return redirect(f"{SITE_URL}?token={jwt_token}&email={email}&name={name or ''}&avatar={avatar or ''}&free_left={u['free_left']}&is_paid={u['is_paid']}")


# ── ME & HISTORY ──────────────────────────────────────────────────────────────

@app.route("/me", methods=["GET"])
@require_auth
def me():
    u = get_user(request.user_id)
    if not u: return jsonify({"error":"Не найден"}), 404
    return jsonify({
        "email":           u["email"],
        "name":            u["name"],
        "avatar":          u["avatar"],
        "free_left":       u["free_left"],
        "is_paid":         u["is_paid"],
        "paid_until":      u["paid_until"].isoformat() if u["paid_until"] else None,
        "total_generated": u["total_generated"]
    })


@app.route("/history", methods=["GET"])
@require_auth
def history():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT id, niche, archetype, cat, tone, topic, strategy, created_at
        FROM generations WHERE user_id=%s
        ORDER BY created_at DESC LIMIT 20
    """, (request.user_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return jsonify([{
        "id": str(r["id"]), "niche": r["niche"], "archetype": r["archetype"],
        "cat": r["cat"], "tone": r["tone"], "topic": r["topic"],
        "strategy": r["strategy"],
        "created_at": r["created_at"].strftime("%d.%m.%Y %H:%M")
    } for r in rows])


# ── PAYMENT ───────────────────────────────────────────────────────────────────

@app.route("/create-payment", methods=["POST"])
@require_auth
def create_payment():
    idempotence = str(uuid.uuid4())
    payload = {
        "amount": {"value": "490.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": SITE_URL},
        "capture": True,
        "description": "Подписка на 1 месяц — ME•CODE Stories",
        "metadata": {"user_id": request.user_id}
    }
    try:
        resp = requests.post(
            "https://api.yookassa.ru/v3/payments",
            json=payload,
            auth=(YUKASSA_SHOP_ID, YUKASSA_SECRET),
            headers={"Idempotence-Key": idempotence}
        )
        r = resp.json()
        pay_id  = r.get("id")
        pay_url = r.get("confirmation", {}).get("confirmation_url")
        conn = get_db(); cur = conn.cursor()
        cur.execute("INSERT INTO payments (user_id,yukassa_id,amount) VALUES (%s,%s,%s)",
                    (request.user_id, pay_id, "490.00"))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"payment_url": pay_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/yukassa-webhook", methods=["POST"])
def yukassa_webhook():
    data  = request.json or {}
    event = data.get("event")
    obj   = data.get("object", {})
    if event != "payment.succeeded":
        return jsonify({"ok": True})
    pay_id  = obj.get("id")
    user_id = obj.get("metadata", {}).get("user_id")
    if not user_id: return jsonify({"ok": True})
    now = datetime.datetime.utcnow()
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT paid_until, is_paid FROM users WHERE id=%s", (user_id,))
    u = cur.fetchone()
    if u and u["is_paid"] and u["paid_until"] and u["paid_until"] > now:
        new_until = u["paid_until"] + datetime.timedelta(days=30)
    else:
        new_until = now + datetime.timedelta(days=30)
    cur.execute("UPDATE users SET is_paid=TRUE, paid_until=%s WHERE id=%s", (new_until, user_id))
    cur.execute("UPDATE payments SET status='succeeded' WHERE yukassa_id=%s", (pay_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"ok": True})


# ── DEEPSEEK ──────────────────────────────────────────────────────────────────

def call_deepseek(system_prompt, user_prompt, max_tokens=1600):
    r = requests.post(DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        json={"model":"deepseek-chat","max_tokens":max_tokens,
              "messages":[{"role":"system","content":system_prompt},
                          {"role":"user","content":user_prompt}]},
        timeout=45)
    return r.json()["choices"][0]["message"]["content"]


ARCHETYPE_SYSTEM = """Ты — ведущий бренд-стратег и эксперт по психологии влияния. Используй систему архетипов для анализа ЦА.
8 АРХЕТИПОВ: Правитель, Эстет, Опекун, Искатель, Невинный, Бунтарь, Мудрец, Славный малый.
ФОРМАТ — строго JSON без лишнего текста:
{"archetype":"...","why":"...","deep_need":"...","shadow_fear":"...","visual_code":"...","hook_phrase":"...","content_vector":"..."}
Без демографии. Хлёстко, без воды."""


GENERATOR_SYSTEM = """Ты — элитный сценарист сторителлинга для Instagram Stories. Пишешь как эксперт с 10-летним стажем в нише клиента.

━━━ МОДУЛЬ: ПРОФЕССИОНАЛЬНАЯ МИМИКРИЯ ━━━
Перед генерацией выполни «Словарь Профи»: определи 3-5 профессиональных терминов для ниши. Используй их естественно.
Термины вместо общих слов: Пекарь→«ферментация,клейковина», Фитнес→«нейромышечная связь,гипертрофия», Таролог→«сигнификатор,теневой аспект», Косметолог→«ТЭПВ,pH-баланс».
Метафора только внутри ниши. Никакой литературщины.

━━━ СТИЛИ ━━━
МИРИ (Energy Explosion): горит на 200%, честный эксперт, драйв, разъеб. Прямо, живо, энергия сносит экран. Запрет: сопли, скука. Смайл только 🔥
ЕВА (Aquarius Icon): надменная, исключительная, она — стандарт. Констатирует превосходство, не заигрывает. Запрет: мягкость, оправдания, «тишина».
ИГРИВЫЙ: самоирония, мемы, трикстер. Серьёзное через шутку.
ЭКСПЕРТНЫЙ: логика, факты, система. Никакой воды.
ДРУЖЕЛЮБНЫЙ: тепло, эмпатия, близкая подруга.

━━━ ТИПЫ ━━━
ЛАЙФ: 0% продаж / ПРОГРЕВ: жизнь+продукт / ПРОДАЮЩИЙ: прямой оффер / ЭКСПЕРТНЫЙ: знания

━━━ СТРАТЕГИИ (случайно) ━━━
X-Ray Vision / The Price of Error / Internal Dialog / Myth Buster

━━━ ФОРМАТ ━━━
СТРАТЕГИЯ: [название]
HOOK: [одна фраза]
СТОРИС 1:\n[текст]\nСТОРИС 2:\n[текст]...
ПОСТ:\n[текст]
CTA:\n[текст]
ТОЛЬКО текст для экрана. Никаких описаний визуала и скобок."""


@app.route("/analyze", methods=["POST"])
@require_auth
def analyze():
    niche = (request.json or {}).get("niche","")
    if not niche: return jsonify({"error":"Ниша не указана"}), 400
    try:
        import re as _re, json as _json
        result = call_deepseek(ARCHETYPE_SYSTEM, f"Определи архетип ЦА: {niche}", 600)
        clean  = _re.sub(r"```json|```","",result).strip()
        return jsonify(_json.loads(clean))
    except Exception as e:
        return jsonify({"error":str(e)}), 500


@app.route("/generate", methods=["POST"])
@require_auth
def generate():
    u = get_user(request.user_id)
    if not u: return jsonify({"error":"Пользователь не найден"}), 404
    ok, reason = check_access(u)
    if not ok:
        return jsonify({"error": reason, "need_payment": True}), 402

    body = request.json or {}
    strategies = ["X-Ray Vision","The Price of Error","Internal Dialog","Myth Buster"]
    chosen = random.choice(strategies)
    cat_map = {"sell":"ПРОДАЮЩИЙ","warmup":"ПРОГРЕВ","life":"ЛАЙФ","expert":"ЭКСПЕРТНЫЙ"}
    ad = body.get("archetype_data", {})
    count = body.get("count", 5)

    prompt = f"""Ниша: {body.get('niche','')}
Архетип ЦА: {body.get('archetype','')}
Потребность: {ad.get('deep_need','')}
Страх: {ad.get('shadow_fear','')}
Тип: {cat_map.get(body.get('cat','life'),'ЛАЙФ')}
Тональность: {body.get('tone','ДРУЖЕЛЮБНЫЙ')}
Ситуация: {body.get('topic','')}
Цель: {body.get('goal','вовлечённость')}
Количество сторис: {count}
Стратегия: {chosen}
Напиши {count} сторис. Только текст для экрана."""

    try:
        result = call_deepseek(GENERATOR_SYSTEM, prompt, 1600)
        conn = get_db(); cur = conn.cursor()
        now = datetime.datetime.utcnow()
        if not u["is_paid"] or not u["paid_until"] or u["paid_until"] <= now:
            cur.execute("UPDATE users SET free_left=free_left-1, total_generated=total_generated+1 WHERE id=%s", (request.user_id,))
        else:
            cur.execute("UPDATE users SET total_generated=total_generated+1 WHERE id=%s", (request.user_id,))
        cur.execute("""INSERT INTO generations (user_id,niche,archetype,cat,tone,topic,result,strategy)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (request.user_id, body.get('niche',''), body.get('archetype',''),
             body.get('cat',''), body.get('tone',''), body.get('topic',''), result, chosen))
        conn.commit(); cur.close(); conn.close()
        u2 = get_user(request.user_id)
        return jsonify({"result": result, "strategy": chosen,
                        "free_left": u2["free_left"], "is_paid": u2["is_paid"],
                        "paid_until": u2["paid_until"].isoformat() if u2["paid_until"] else None})
    except Exception as e:
        return jsonify({"error":str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
