from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# --- АРХЕТИПЫ ---
ARCHETYPES = {
    "эстет": "хочет чувствовать себя желанной, красивой, дорогой",
    "правитель": "хочет контроль, статус, безупречность и высокий уровень",
    "опекун": "устала заботиться о других, хочет, чтобы позаботились о ней",
    "бунтарь": "хочет свободы, быть не как все, нарушать правила"
}

# --- СТИЛИ ---
STYLE_MODES = {

    "экспертный": """
уверенно, чётко, через инсайты
без воды
как человек, который уже всё понял
""",

    "игривый": """
живой, лёгкий, с юмором
как будто рассказываешь подруге
""",

    "дерзкий": """
прямо, с подколом
цепляет с первой фразы
не сглаживает углы
""",

    "мири": """
Прямолинейность. Вкус. Высокая планка.
Не для всех.

— бьёт в лоб
— делит людей на “своих” и остальных
— не продаёт, а задаёт уровень
— допускает провокацию
— звучит дорого и уверенно

маркер: статус, уровень, вкус, дешево/дорого
""",

    "ева": """
Мягкая сила. Люкс. Спокойный контроль.

— не давит, а притягивает
— говорит красиво и точно
— ощущение высокого уровня
— через визуал, вайб, атмосферу

маркер: стратегия, визуал, масштаб, уровень
"""
}


def detect_archetype(niche):
    niche = niche.lower()

    if any(x in niche for x in ["эстет", "красот", "lux", "визуал"]):
        return "эстет"
    if any(x in niche for x in ["бизнес", "бренд", "дорог", "премиум"]):
        return "правитель"
    if any(x in niche for x in ["мама", "забота", "уход"]):
        return "опекун"
    if any(x in niche for x in ["тату", "ярк", "креатив", "не как все"]):
        return "бунтарь"

    return "эстет"


def call_deepseek(prompt):
    url = "https://api.deepseek.com/chat/completions"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        url,
        headers=headers,
        json={
            "model": "deepseek-chat",
            "temperature": 0.75,
            "top_p": 0.9,
            "messages": [{"role": "user", "content": prompt}]
        }
    )

    return response.json()["choices"][0]["message"]["content"]


@app.route("/generate", methods=["POST"])
def generate():
    data = request.json

    niche = data.get("niche", "")
    topic = data.get("topic", "")
    goal = data.get("goal", "")
    tone = data.get("tone", "игривый")
    cat = data.get("cat", "life")
    count = data.get("count", 5)

    style = STYLE_MODES.get(tone, STYLE_MODES["игривый"])

    archetype = detect_archetype(niche)
    archetype_desc = ARCHETYPES.get(archetype)

    prompt = f"""
Ты пишешь сторис как живой человек.

Ниша: {niche}
Тема: {topic}
Цель: {goal}

Архетип:
{archetype} — {archetype_desc}

Стиль:
{style}

ВАЖНО:
— не писать как нейросеть
— не использовать шаблонные фразы
— не делать текст плоским
— каждая сторис = живая мысль

СТРУКТУРА:
1 — цепляющая мысль
2–4 — развитие через ситуацию / наблюдение
последняя — инсайт или мягкое действие

ТИП:
{cat}

ФОРМАТ:

Сторис 1:
...

Сторис 2:
...

Сделай текст живым, цепляющим и с характером.

Напиши {count} сторис.
"""

    try:
        result = call_deepseek(prompt)
        return jsonify({"result": result})
    except Exception:
        return jsonify({"result": "Ошибка генерации"})


@app.route("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
