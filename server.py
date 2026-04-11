from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# --- СТИЛИ ---
STYLE_MODES = {
    "экспертный": "ясно, уверенно, без воды, через инсайты",
    "игривый": "лёгкий, живой, с юмором",
    "дерзкий": "с подколом, прямолинейно, цепляет",
    "мири": "дерзко, провокационно, будто ты читаешь мысли человека",
    "ева": "дорого, спокойно, уверенно, как женщина с высоким стандартом"
}

# --- АРХЕТИПЫ ---
ARCHETYPES = {
    "эстет": "хочет чувствовать себя желанной и красивой",
    "правитель": "хочет контроль, статус и идеальность",
    "опекун": "устала заботиться о всех, хочет чтобы позаботились о ней",
    "бунтарь": "хочет свободы и быть не как все"
}

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
            "temperature": 0.7,
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

    prompt = f"""
Ты пишешь Instagram сторис как живой человек.

Ниша: {niche}
Тема: {topic}
Цель: {goal}
Стиль: {style}

Важно:
— не писать как эксперт из интернета
— не использовать шаблонные фразы
— каждая сторис — как реальная мысль
— допускается ирония, напряжение, узнавание

Структура:
1 сторис — зацепка
2–4 — развитие через ситуацию
финал — инсайт или лёгкий толчок

Формат:
Сторис 1:
...
Сторис 2:
...

Напиши {count} сторис.
"""

    try:
        result = call_deepseek(prompt)
        return jsonify({"result": result})
    except:
        return jsonify({"result": "Ошибка генерации"})


@app.route("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
