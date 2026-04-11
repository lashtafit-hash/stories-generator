# Генератор сторис — dark pink версия

## Что внутри
- `index.html` — твой обновлённый фронтенд
- `server.py` — Flask API для DeepSeek
- `requirements.txt` — зависимости
- `Procfile` — команда запуска для Railway
- `.env.example` — пример переменных окружения

## Как запустить через Railway
1. Создай новый GitHub-репозиторий.
2. Загрузи туда все файлы из этого архива.
3. В Railway нажми **New Project** → **Deploy from GitHub Repo**.
4. Выбери свой репозиторий.
5. В Railway открой **Variables** и добавь:
   - `DEEPSEEK_API_KEY` = твой ключ DeepSeek
   - `DEEPSEEK_MODEL` = `deepseek-chat`
6. После деплоя Railway даст URL.
7. Открой `index.html` и замени:
   - `https://REPLACE-WITH-YOUR-RAILWAY-URL.up.railway.app`
   на свой настоящий Railway URL.
8. После этого залей `index.html` на сайт или в HTML-блок.

## Проверка
После деплоя можно открыть:
- `/`
- `/health`

Если видишь JSON, всё поднялось.

## Локальный тест
```bash
pip install -r requirements.txt
python server.py
```
