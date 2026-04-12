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
SITE_URL          = os.environ.get("SITE_URL", "https://daring-smm.ru/stories-generator/")
DEEPSEEK_URL      = "https://api.deepseek.com/v1/chat/completions"


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
            free_left INTEGER DEFAULT 3,
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


# ── AUTH ─────────────────────────────────────────────────────────────────────

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


# ── AUTH ROUTES ───────────────────────────────────────────────────────────────

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
                        "email": u["email"], "free_left": u["free_left"], "is_paid": False})
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
        "paid_until": u["paid_until"].isoformat() if u["paid_until"] else None
    })

@app.route("/me", methods=["GET"])
@require_auth
def me():
    u = get_user(request.user_id)
    if not u: return jsonify({"error":"Не найден"}), 404
    return jsonify({
        "email":           u["email"],
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
        "amount": {"value": "199.00", "currency": "RUB"},
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
                    (request.user_id, pay_id, "199.00"))
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

def call_deepseek(system_prompt, user_prompt, max_tokens=1200):
    r = requests.post(DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "max_tokens": max_tokens,
            "temperature": 0.9,
            "top_p": 0.95,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ]
        },
        timeout=45)
    return r.json()["choices"][0]["message"]["content"]


# ── СЦЕНАРИИ ПО КАТЕГОРИЯМ ────────────────────────────────────────────────────

SCENARIOS = {
    "life": [
        {
            "name": "POV: Напряжение",
            "instruction": "Используй ситуацию юзера как декорацию. Найди в ней микро-конфликт: очередь, чья-то реакция, сервис, случайная деталь. Свяжи это с тем, как люди привыкли терпеть дискомфорт вместо того, чтобы менять систему. Структура: Сцена — Конфликт — Вывод. Мири уколет, Ева покажет, что её уровень выше этого хаоса."
        },
        {
            "name": "Внутренняя кухня мысли",
            "instruction": "Преврати ситуацию в метафору. Магазин — это метафора выбора. Дом — метафора ресурса. Сделай список из 3 честных правил жизни, которые ты осознала прямо сейчас. Фразы короткие, хлёсткие, без 'успешного успеха'. Это репостовый контент — сторис, которую пересылают с комментом 'жиза'."
        },
        {
            "name": "Слом фасада",
            "instruction": "Начни с идеальной картинки (что должно быть), потом покажи что происходит на самом деле (ситуация юзера). Создай напряжение между 'как надо' и 'как есть'. Структура: Ожидание — Реальность — Мысль почему это нормально. Мири самоиронично смеётся над собой, Ева признаёт что даже у богинь бывают дни хаоса, и это часть её силы."
        },
        {
            "name": "Список Анти-дел",
            "instruction": "Возьми ситуацию юзера. Составь список из 3 пунктов: 'Что я больше не делаю'. Заголовок-крючок + нумерованный список с коротким пояснением почему. Это должно быть дерзко и про ценности. Мири — через жёсткий отбор, Ева — через высокие стандарты. Призыв сохранить в конце."
        },
        {
            "name": "Чит-код дня",
            "instruction": "Найди в ситуации юзера полезную деталь. Как сделать это быстрее/лучше/красивее? Дай один чёткий совет, который можно применить сегодня же. Текст — как короткая заметка в телефоне. Прикладной, конкретный, без воды."
        },
        {
            "name": "За vs Против",
            "instruction": "Столкни два варианта в ситуации юзера. Выведи это в философию — почему ты выбираешь комфорт или движение. Дай честные плюсы и минусы каждого, но в конце — свой безапелляционный выбор. Люди любят спорить в комментах под такими темами."
        },
        {
            "name": "Эстетика момента",
            "instruction": "Опиши ситуацию через запахи, звуки и детали. Никаких поучений. Просто заставь зрителя почувствовать момент. Ева звучит как богиня эстетики, Мири — как женщина, которая смакует жизнь. Чистый лайфстайл с сильным вайбом."
        }
    ],
    "warmup": [
        {
            "name": "AIDA: Взлом внимания",
            "instruction": "Начни с резкого стоп-кадра из ситуации юзера (Attention). Перейди к проблеме, которую этот момент подсвечивает (Interest). Покажи продукт как единственный способ превратить хаос в результат (Desire). Прямой призыв (Action). Никакой воды: Сцена — Боль — Решение — CTA."
        },
        {
            "name": "PAS: Соль на рану",
            "instruction": "Найди в ситуации юзера намёк на усталость или рутину (Problem). Раздуй конфликт — покажи что будет если оставить всё как есть: слитые бюджеты, отсутствие жизни (Agitation). Дай продукт как спасательный круг (Solution). Мири дожимает, Ева показывает выход в статусную жизнь."
        },
        {
            "name": "До vs После",
            "instruction": "Используй ситуацию как пример 'старой жизни'. Расскажи как раньше ты бы тратила на это часы, а сейчас система делает всё за тебя. Акцент не на функции, а на свободе и контроле. Никакой 'новой искренности' — только честный контраст двух реальностей."
        },
        {
            "name": "Скрытая выгода",
            "instruction": "Сделай список из 3 преимуществ продукта, которые не очевидны. Свяжи с ситуацией. Например: 'Пока я выбираю вино, система продаёт за меня'. Репостовый лайфхак про автоматизацию жизни. Структура: Неочевидный плюс + Почему это меняет игру."
        },
        {
            "name": "Фильтр для своих",
            "instruction": "Используй ситуацию чтобы показать свой уровень. Напиши кому точно НЕ подойдёт продукт. Эффект закрытого клуба. Мири дерзко: 'Если любишь ныть — мимо'. Ева статусно: 'Я выбираю тех, кто готов к масштабу'. Структура: Кто ты — Кому не подходит — Кто свой."
        },
        {
            "name": "Цена бездействия",
            "instruction": "Жёсткий сценарий. Покажи на примере ситуации юзера, сколько времени/денег клиент теряет прямо сейчас пока думает. Разложи на цифрах если возможно. Текст создаёт жгучее желание действовать здесь и сейчас. Структура: Сцена — Потери — Решение."
        },
        {
            "name": "Миф и Реальность",
            "instruction": "Возьми популярное мнение о продукте или нише. Разнеси его в щепки, используя ситуацию как доказательство. Структура: Популярный миф — Почему это ложь — Реальный результат. Не магия, а технология с предсказуемым результатом."
        }
    ],
    "sell": [
        {
            "name": "Последний вагон",
            "instruction": "Используй ситуацию юзера чтобы показать: пока ты занимаешься этим делом, чьё-то место улетает. Структура: Сцена — Факт ограничения — Прямой призыв. Никаких 'может быть', только 'забирай или забудь'. FOMO на максимум."
        },
        {
            "name": "Математика выгоды",
            "instruction": "Разложи на цифрах в контексте ситуации. 'Ты тратишь 2 часа на этот пост. Твой час стоит X. Продукт стоит Y. Ты уже в минусе'. Список с расчётом. Холодная логика. Ева звучит как финансовый директор твоей жизни."
        },
        {
            "name": "Ожидание vs Результат",
            "instruction": "Покажи контраст: ситуация сейчас (рутина) и ситуация через 15 минут после покупки. Акцент на мгновенном облегчении. Мири подаёт как хак который освобождает руки не завтра, а прямо сейчас. Структура: Сейчас — Через 15 минут — CTA."
        },
        {
            "name": "Отработка последнего НЕТ",
            "instruction": "Найди в ситуации оправдание которое обычно придумывает клиент. Разнеси его в щепки. 'Нет времени? Именно поэтому тебе это нужно'. Текст короткий, как пощёчина приводящая в чувство. Одно возражение — один удар — CTA."
        },
        {
            "name": "Инвестиция в статус",
            "instruction": "Используй ситуацию чтобы показать эстетику того, кто уже владеет системой. Ева — главный герой. Продукт как маркер что ты 'в обойме'. Либо ты с нами в топе, либо смотришь сторис тех кто в топе. Структура: Картинка статуса — Что за ней стоит — Как войти."
        },
        {
            "name": "Твёрдый результат",
            "instruction": "Свяжи текущий момент с успехом клиента. 'Пока я здесь [ситуация], мой клиент получил [результат] через 15 минут'. Прямая связка: Инструмент = Результат. Конкретика без воды, цифры если есть."
        },
        {
            "name": "Проверка на прочность",
            "instruction": "Самый жёсткий сценарий Мири. Вызов аудитории: 'Ты можешь пролистать и завтра проснуться в той же точке. А можешь нажать кнопку. Твой выбор — это твой диагноз'. Давление на амбиции и гордость. Никакой мягкости."
        }
    ],
    "expert": [
        {
            "name": "Честный Хит-парад",
            "instruction": "Возьми ситуацию юзера как повод для списка. Топ 3-5 вещей в нише (ошибки, правила, инструменты). Структура: Заголовок-крючок + Нумерованный список (первый — база, последний — шок-деталь с пояснением почему важно) + Призыв сохранить. Репосты обеспечены."
        },
        {
            "name": "Битва Титанов",
            "instruction": "Используй ситуацию как декорацию для сравнения. Столкни два варианта (Дорого vs Дёшево, Быстро vs Качественно). Плюсы и минусы каждого, в конце — безапелляционный вердикт. Структура: Тезис — За А — Против А — За Б — Против Б — Мой вердикт. Мири добивает проигравший вариант, Ева выбирает лучшее."
        },
        {
            "name": "Экспертный Лайфхак",
            "instruction": "Сначала покажи сложный путь которым идут все. Потом дай профессиональный секрет который решает проблему за 15 минут. Структура: Как все делают — Мой чит-код — Результат. Прикладной и короткий как заметка которую нужно заскринить."
        },
        {
            "name": "Разбор Дичи",
            "instruction": "Найди в ситуации пример того как делать НЕ надо. Объясни на пальцах почему это вредно. Структура: Популярный совет/практика — Почему это ошибка — Как правильно. Напряжение между 'так принято' и 'как правильно'. Заверши фразой которая заставляет задуматься."
        },
        {
            "name": "Анатомия Качества",
            "instruction": "Опиши ситуацию через микро-детали которые видит только профи. На что ты смотришь первым делом как эксперт? Насмотренность через детали. Структура: Что видят все — Что вижу я — Почему это важно. Ева как эстет, Мири как рентген который видит фальшь."
        },
        {
            "name": "Мои стандарты",
            "instruction": "Свяжи ситуацию с твоим отношением к делу. Почему ты никогда не согласишься на меньшее? Манифест ценностей через отрицание дешёвого подхода. Структура: Что я вижу вокруг — Мой стандарт — Почему это не обсуждается. Никаких оправданий, только позиция силы."
        },
        {
            "name": "Прогноз",
            "instruction": "Используй момент здесь и сейчас чтобы предсказать что будет в нише через полгода. Покажи что те кто делает по-старому скоро останутся за бортом. Структура: Что происходит сейчас — Куда это ведёт — Что нужно делать уже сегодня. Интеллектуальное превосходство через видение."
        }
    ]
}


ARCHETYPE_SYSTEM = """Ты — ведущий бренд-стратег и эксперт по психологии влияния. Используй систему архетипов для анализа ЦА.
8 АРХЕТИПОВ: Правитель, Эстет, Опекун, Искатель, Невинный, Бунтарь, Мудрец, Славный малый.
ФОРМАТ — строго JSON без лишнего текста:
{"archetype":"...","why":"...","deep_need":"...","shadow_fear":"...","visual_code":"...","hook_phrase":"...","content_vector":"..."}
Без демографии. Хлёстко, без воды."""


GENERATOR_SYSTEM = """Ты — сценарист с мышлением сильного автора. Твоя задача — писать так, чтобы контент невозможно было пролистать.

━━━ КРИТИЧЕСКИЙ АЛГОРИТМ (ВЫПОЛНЯТЬ ПЕРЕД ТЕКСТОМ) ━━━

Этап 1 — ГЛУБОКОЕ ПОГРУЖЕНИЕ:
Изучи нишу и найди в ней реальный конфликт или ошибку которую совершают 99% людей.
Текст строится вокруг СЦЕНЫ и НАПРЯЖЕНИЯ, а не просто типа контента.

Этап 2 — ФИЛЬТР УНИКАЛЬНОСТИ:
Если получившийся текст можно использовать в любой другой нише заменив пару слов — это плохой текст.
Каждая сторис должна содержать наблюдение характерное только для этой ниши.
Если текст звучит "правильно" — перепиши. Нам нужно "опасно".

Этап 3 — ПРИМЕНЕНИЕ ДНК ПЕРСОНАЖА:
Выбранный стиль — это не тон, это личность. Пропусти весь текст через неё.

━━━ ДНК ПЕРСОНАЖЕЙ ━━━

МИРИ (Energy Explosion):
Умная, дерзкая, живая. Внутренняя сила + тонкая провокация. Пишет с ритмом, любит подтекст.
Флирт без прямолинейности. Не учит — вскрывает боли. Честные иногда жёсткие мысли.
Вместо "правильных советов" — "Смотрю на это и думаю... какого черта вы вообще делаете".
Смайл только 🔥. Запрет: сопли, скука, розовые советы, агрессивный продажник.

ЕВА (Aquarius Icon):
Взрослая, эффектная, харизматичная. Действует через присутствие и телесную уверенность.
Спокойная уверенность что на неё и так посмотрят. Статусная и безупречная.
Она не заигрывает — констатирует превосходство. Не советует — показывает стандарт.
Смайлы минимум только по делу. Запрет: мягкость, оправдания, дешёвые призывы.

ИГРИВЫЙ (The Provocateur):
Трикстер. Самоирония, мемы, лёгкая провокация. Самое серьёзное объясняет через шутку.
Дерзкий, смешной, расслабленный. Запрет: занудство, нравоучения.

ЭКСПЕРТНЫЙ (The Rational Mind):
Аналитик. Мир как система причин и следствий. Логика, факты, структура.
Без воды и общих слов. Запрет: эмоциональность без доказательств.

ДРУЖЕЛЮБНЫЙ (The Support):
Эмпат. Всегда на стороне клиента. Тепло, понимание, минимум дистанции.
Запрет: холодность, давление, пафос.

━━━ КРИТИЧЕСКИЕ ТРЕБОВАНИЯ К ТЕКСТУ ━━━
— ЗАПРЕЩЕНЫ клише: "ошибка которая стоит вам денег", "я работала 48 часов", "успешный успех"
— ЗАПРЕЩЕНЫ: инженерные термины вместо живого языка, канцелярщина
— Профессиональный сленг ниши — только если уместно и органично, не как отчёт
— Ситуация юзера — это ДЕКОРАЦИЯ и СЦЕНА. Интегрируй её в текст органично
— Сценарий — это СТРУКТУРА. Следуй ей но через личность персонажа
— Тип контента (лайф/прогрев) — это РАМКА, не суть. Суть — сценарий и конфликт
— Каждая сторис цепляет, создаёт напряжение и ведёт к следующей
— ТОЛЬКО текст для экрана. Никаких описаний визуала, скобок с кадрами, [крупный план]

━━━ ФОРМАТ ВЫДАЧИ ━━━

СТРАТЕГИЯ: [название сценария]

HOOK: [одна фраза-удар в нерв]

СТОРИС 1:
[текст]

СТОРИС 2:
[текст]

СТОРИС 3:
[текст]

СТОРИС 4:
[текст]

СТОРИС 5:
[текст]

ПОСТ:
[текст]

CTA:
[призыв органичный для стиля персонажа]"""


@app.route("/analyze", methods=["POST"])
def analyze():
    niche = (request.json or {}).get("niche","")
    if not niche: return jsonify({"error":"Ниша не указана"}), 400
    try:
        import re as _re, json as _json
        result = call_deepseek(ARCHETYPE_SYSTEM, f"Определи архетип ЦА: {niche}", 400)
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
    cat  = body.get("cat", "life")
    ad   = body.get("archetype_data", {})
    count = body.get("count", 5)

    # Выбираем сценарий рандомно из категории — каждый раз новый
    cat_scenarios = SCENARIOS.get(cat, SCENARIOS["life"])
    chosen = random.choice(cat_scenarios)

    cat_map = {"sell":"ПРОДАЖИ","warmup":"ПРОГРЕВ","life":"ЛАЙФ","expert":"ЭКСПЕРТНЫЙ"}

    prompt = f"""ВХОДНЫЕ ДАННЫЕ:
Ниша: {body.get('niche','')}
Архетип ЦА: {body.get('archetype','')}
Глубинная потребность ЦА: {ad.get('deep_need','')}
Теневой страх ЦА: {ad.get('shadow_fear','')}
Тип контента: {cat_map.get(cat,'ЛАЙФ')} (это рамка, не суть)
Стиль/Персонаж: {body.get('tone','ДРУЖЕЛЮБНЫЙ')}
Ситуация юзера (используй как декорацию/сцену): {body.get('topic','')}
Цель: {body.get('goal','вовлечённость')}
Количество сторис: {count}

СЦЕНАРИЙ ДЛЯ ЭТОЙ ГЕНЕРАЦИИ: {chosen['name']}
ИНСТРУКЦИЯ ПО СЦЕНАРИЮ: {chosen['instruction']}

АЛГОРИТМ:
1. Найди конфликт или ошибку которую совершают 99% людей в нише "{body.get('niche','')}"
2. Проверь: если текст подойдёт для любой другой ниши — перепиши
3. Пропусти всё через личность персонажа {body.get('tone','')}
4. Напиши {count} сторис по структуре сценария "{chosen['name']}"

Только текст для экрана. Никаких описаний визуала."""

    try:
        result = call_deepseek(GENERATOR_SYSTEM, prompt, 1200)

        conn = get_db(); cur = conn.cursor()
        now = datetime.datetime.utcnow()
        if not u["is_paid"] or not u["paid_until"] or u["paid_until"] <= now:
            cur.execute(
                "UPDATE users SET free_left=free_left-1, total_generated=total_generated+1 WHERE id=%s",
                (request.user_id,)
            )
        else:
            cur.execute(
                "UPDATE users SET total_generated=total_generated+1 WHERE id=%s",
                (request.user_id,)
            )
        cur.execute("""INSERT INTO generations (user_id,niche,archetype,cat,tone,topic,result,strategy)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (request.user_id, body.get('niche',''), body.get('archetype',''),
             cat, body.get('tone',''), body.get('topic',''), result, chosen['name']))
        conn.commit(); cur.close(); conn.close()

        u2 = get_user(request.user_id)
        return jsonify({
            "result": result,
            "strategy": chosen['name'],
            "free_left": u2["free_left"],
            "is_paid": u2["is_paid"],
            "paid_until": u2["paid_until"].isoformat() if u2["paid_until"] else None
        })
    except Exception as e:
        return jsonify({"error":str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
