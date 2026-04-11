from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
import re
from typing import Any, Dict

import requests

app = Flask(__name__)
CORS(app)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


def clean_json_block(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"```json|```", "", text, flags=re.IGNORECASE).strip()
    return json.loads(cleaned)


def call_deepseek(prompt: str, max_tokens: int = 1200, temperature: float = 1.0) -> str:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("Не задан DEEPSEEK_API_KEY в переменных окружения Railway.")

    response = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": DEEPSEEK_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты сильный русскоязычный маркетинговый копирайтер. "
                        "Пишешь остро, точно, без воды, с хорошим вкусом и ритмом."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        },
        timeout=60,
    )

    response.raise_for_status()
    data = response.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Неожиданный ответ DeepSeek: {data}") from exc


@app.route("/", methods=["GET"])
def root():
    return jsonify({"ok": True, "service": "stories-generator-api"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/analyze", methods=["POST"])
def analyze():
    niche = (request.json or {}).get("niche", "").strip()
    if not niche:
        return jsonify({"error": "Пустое описание ниши"}), 400

    prompt = f'''
Определи целевую аудиторию и стиль общения для проекта: "{niche}".

Нужен маркетинговый, а не абстрактный ответ.
Не пиши общие фразы вроде "широкая аудитория", "все женщины", "дружелюбный стиль".

Правила:
— сегменты ЦА должны быть конкретными и узнаваемыми
— тон должен звучать как реальный стиль контента, а не учебник
— auto_tone должен быть коротким, ярким и удобным для дальнейшей генерации

Верни ТОЛЬКО JSON без пояснений:
{{
  "ca": ["сегмент 1", "сегмент 2", "сегмент 3"],
  "tone": ["характер подачи 1", "характер подачи 2"],
  "auto_tone": "короткое описание стиля"
}}
'''

    try:
        result = call_deepseek(prompt, max_tokens=350, temperature=0.8)
        parsed = clean_json_block(result)

        ca = parsed.get("ca") or ["заинтересованная аудитория", "люди, которым нужен понятный результат", "те, кто выбирают по ощущению и доверию"]
        tone = parsed.get("tone") or ["живой", "с характером"]
        auto_tone = parsed.get("auto_tone") or "живой и уверенный"

        return jsonify({
            "ca": ca[:3],
            "tone": tone[:3],
            "auto_tone": auto_tone,
        })
    except Exception:
        return jsonify({
            "ca": [
                "люди, которым нужен красивый и понятный контент",
                "аудитория, реагирующая на стиль и уверенную подачу",
                "клиенты, которые покупают через доверие и ощущение качества",
            ],
            "tone": ["живой", "острый", "профессиональный"],
            "auto_tone": "дерзко и по делу",
        })


@app.route("/generate", methods=["POST"])
def generate():
    body = request.json or {}

    niche = body.get("niche", "").strip()
    topic = body.get("topic", "").strip()
    goal = body.get("goal", "").strip()
    tone = body.get("tone", "дерзко и по делу").strip()
    ca = body.get("ca", "аудитория, которая покупает через доверие и стиль").strip()
    cat = body.get("cat", "life").strip()

    try:
        count = int(body.get("count", 5))
    except (ValueError, TypeError):
        count = 5

    count = max(3, min(count, 10))

    if not topic:
        return jsonify({"error": "Не указана тема сторис"}), 400

    cat_prompts = {
        "sell": f'''
Сделай {count} продающих сторис.
Логика: сильный крючок → узнаваемая боль/желание → напряжение → решение → действие.
Без прямолинейного "купи срочно".
Нужно вызывать желание и ощущение: "мне это надо".
Цель: {goal or "довести до заявки, записи или интереса"}
''',
        "warmup": f'''
Сделай {count} сторис-прогрев.
Логика: наблюдение → узнавание → внутренний щелчок → подводка к нужной мысли.
Человек должен сам дойти до вывода.
Цель: {goal or "разогреть интерес и подготовить к следующему шагу"}
''',
        "life": f'''
Сделай {count} лайф-сторис.
Нужна живая подача, характер, юмор, ощущение настоящего человека.
Без пустого пересказа дня. Каждая сторис должна либо цеплять, либо раскрывать личность.
{f"Мягко вплети цель: {goal}" if goal else "Без явной продажи, но с ощущением ценности автора."}
''',
        "expert": f'''
Сделай {count} экспертных сторис.
Не нуди и не обучай как в вебинаре.
Показывай мышление: "все думают X, а на деле Y".
Нужны плотные инсайты, которые дают авторитет с одной-двух фраз.
{f"Финал подведи к цели: {goal}" if goal else "Финал должен усиливать доверие к автору."}
''',
    }

    prompt = f'''
Ты пишешь Instagram сторис в стиле Мири и Евы.

Это стиль:
— дерзко, умно, вкусно
— с юмором, но без клоунады
— профессионально, но не сухо
— без воды, банальностей и инфоцыганских интонаций
— каждая фраза короткая, плотная и с характером
— текст должен сбивать с ног одной формулировкой, а не растекаться объяснениями

Контекст:
Ниша: {niche}
ЦА: {ca}
Тон: {tone}
Тема: {topic}

Тип сторис:
{cat_prompts.get(cat, cat_prompts["life"])}

Критически важно:
— никаких шаблонов типа "сегодня хочу рассказать", "важно понимать", "давайте поговорим"
— никаких длинных вступлений
— никаких канцеляризмов
— никаких пустых мотивационных фраз
— минимум слов, максимум попадания
— каждая сторис должна логично вести к следующей
— допускаются контраст, самоирония, точные наблюдения, острые формулировки

Требования к качеству:
— пиши так, будто это контент сильного агентства, у которого есть вкус и яйца
— вместо объяснения используй сильное наблюдение
— вместо воды используй точный вывод
— вместо банального CTA используй формулировку, которая вызывает импульс

Формат:
Сторис 1:
текст

Сторис 2:
текст

И так далее до Сторис {count}.

Ограничения:
— каждая сторис: максимум 1–3 короткие фразы
— итог должен быть готовым для публикации
— не добавляй комментарии, пояснения, варианты, подводки от себя

Пиши только итоговый текст сторис.
'''

    try:
        result = call_deepseek(prompt, max_tokens=1600, temperature=1.05)
        return jsonify({"result": result})
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text if exc.response is not None else str(exc)
        return jsonify({"error": f"Ошибка DeepSeek API: {detail}"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
