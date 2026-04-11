from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import json
import re

app = Flask(__name__)

# Можно ограничить домены через env ALLOWED_ORIGINS, если понадобится.
CORS(app)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_URL = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
PORT = int(os.environ.get("PORT", 5000))


def call_deepseek(prompt: str, max_tokens: int = 1000) -> str:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("Не задан DEEPSEEK_API_KEY в переменных окружения")

    response = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": DEEPSEEK_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"Неожиданный ответ API: {json.dumps(data, ensure_ascii=False)[:500]}")


@app.get("/")
def home():
    return jsonify({
        "ok": True,
        "service": "story-generator-api",
        "model": DEEPSEEK_MODEL,
    })


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/analyze")
def analyze():
    body = request.get_json(silent=True) or {}
    niche = (body.get("niche") or "").strip()

    if not niche:
        return jsonify({"error": "Поле niche обязательно"}), 400

    prompt = f'''Определи целевую аудиторию и стиль общения для блогера/специалиста: "{niche}".
Ответь ТОЛЬКО в формате JSON без лишнего текста:
{{"ca":["аудитория1","аудитория2","аудитория3"],"tone":["тон1","тон2"],"auto_tone":"один короткий тон"}}'''

    try:
        result = call_deepseek(prompt, max_tokens=300)
        clean = re.sub(r"```json|```", "", result).strip()
        return jsonify(json.loads(clean))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/generate")
def generate():
    body = request.get_json(silent=True) or {}
    niche = (body.get("niche") or "").strip()
    topic = (body.get("topic") or "").strip()
    goal = (body.get("goal") or "").strip()
    count = int(body.get("count", 5) or 5)
    tone = (body.get("tone") or "дружелюбный").strip()
    ca = (body.get("ca") or "широкая аудитория").strip()
    cat = (body.get("cat") or "life").strip()

    if not niche:
        return jsonify({"error": "Поле niche обязательно"}), 400
    if not topic:
        return jsonify({"error": "Поле topic обязательно"}), 400

    cat_prompts = {
        "sell": f"Напиши {count} продающих сторис по формуле AIDA или Звезда-Цепь-Крюк.{f' Цель: {goal}.' if goal else ''} Каждая сторис ведёт к действию.",
        "warmup": f"Напиши {count} прогревающих сторис. Схема: контекст → интерес → желание.{f' Цель прогрева: {goal}.' if goal else ''}",
        "life": f"Напиши {count} лайф-сторис — живо, по-человечески, закулисье.{f' Аккуратно вплети: {goal}.' if goal else ' Без явных продаж.'}",
        "expert": f"Напиши {count} экспертных сторис по схеме: проблема → взгляд эксперта → практическая польза.{f' Финал: {goal}.' if goal else ''}",
    }

    prompt = f'''Ты пишешь сторис Instagram для: {niche}
ЦА: {ca}
Тон: {tone}
Тема: {topic}

{cat_prompts.get(cat, cat_prompts["life"])}

Формат: каждую сторис обозначь "Сторис 1", "Сторис 2" и т.д.
Пиши живо, как голос автора. Только готовый текст, без пояснений.'''

    try:
        result = call_deepseek(prompt, max_tokens=1200)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
