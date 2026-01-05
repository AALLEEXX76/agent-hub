#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "[agent_runner] Запрашиваю задание из n8n..."
PAYLOAD=$(curl -fsS https://ii-bot-nout.ru/webhook/agent-task)

# Сохраним payload для отладки
printf '%s\n' "$PAYLOAD" > agent_payload.json

echo "[agent_runner] Отправляю задание Claude для построения плана..."

# Забираем stdout+stderr Claude, чтобы ничего не потерять
PLAN=$(printf '%s\n' "$PAYLOAD" | claude -p "Тебе на stdin приходит один JSON-объект.
Он имеет ключи: task, n8n, server, telegram.
task содержит текст задания, другие поля содержат параметры (baseUrl, apiKey и т.д.).

Ты действуешь как планировщик для n8n.
Твоя задача: на основе task составить список HTTP-запросов к REST API n8n,
которые создадут или обновят и активируют workflow 'II-BOT Executor v1 (Telegram → SSH)'.

ВАЖНО:
- НИЧЕГО не выполняй, только план.
- НЕ выводи никакого текста, кроме ОДНОГО JSON-объекта.
- Без markdown, без комментариев, без пояснений снаружи JSON.

Структура выходного JSON строго такая:
{
  \"http\": [
    {
      \"description\": \"краткое описание шага\",
      \"method\": \"GET\" или \"POST\" или \"PUT\" или \"PATCH\" или \"DELETE\",
      \"endpoint\": \"/api/v1/...\",\"
      \"body\": объект JSON или null
    }
  ],
  \"comment\": \"краткое описание плана на русском\"
}

Требования:
- В поле endpoint используй ТОЛЬКО относительные пути, начинающиеся с /api/v1/.
  Пример: \"/api/v1/workflows\" или \"/api/v1/credentials\".
  НЕ добавляй домен, протокол и т.п.
- В поле body клади JSON-объект (для тела запроса) или null, если тело не нужно.
- НЕ включай в вывод apiKey или baseUrl. Исполнитель их уже знает из исходного payload.
- Убедись, что результат строго валидный JSON и соответствует схеме выше.
- Если запросов не требуется, верни \"http\": [].

Верни ТОЛЬКО этот JSON, без лишних строк." 2>&1)

# Сохраняем ответ как есть (и успех, и ошибка) для анализа
printf '%s\n' "$PLAN" > agent_plan.json

echo "[agent_runner] Выполняю HTTP-шаги плана через n8n API..."

python3 - << 'PY'
import json, subprocess, sys

# Загружаем исходный payload от n8n
with open("agent_payload.json", "r", encoding="utf-8") as f:
    payload = json.load(f)

# Загружаем план от Claude как сырой текст
with open("agent_plan.json", "r", encoding="utf-8") as f:
    raw = f.read()

if not raw.strip():
    print("[agent_runner] ОШИБКА: Claude вернул пустой ответ (agent_plan.json пустой).")
    sys.exit(1)

raw_stripped = raw.strip()

# Снимаем Markdown-обёртку 
