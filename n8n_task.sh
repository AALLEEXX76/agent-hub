#!/usr/bin/env bash
set -euo pipefail

# 1) Забрать задание из n8n (Agent Task API)
PAYLOAD=$(curl -fsS https://ii-bot-nout.ru/webhook/agent-task)

# 2) Отдать JSON агенту Claude через CLI
# Предполагаем, что команда "claude" уже установлена и настроена с твоим API-ключом.
printf '%s\n' "$PAYLOAD" | claude -p "Тебе на stdin приходит JSON payload от n8n.
В нём есть поля:
- task (строка с подробным ТЗ)
- n8n.baseUrl и n8n.apiKey (для доступа к REST API n8n)
- server.ip и server.domain
- telegram.allowedAdmins (список Telegram ID админов).

Твоя задача:
1) Прочитать JSON из stdin.
2) Вытащить из него эти поля.
3) Выполнить то, что описано в поле task:
   - через REST API n8n по адресу baseUrl с apiKey
   - создать или обновить workflow 'II-BOT Executor v1 (Telegram → SSH)'
   - активировать его.
4) Внутри workflow реализовать логику:
   - Telegram Trigger с allowlist по admin IDs
   - парсер команд (/status, /ping, /health, /backup, /restart, /confirm RESTART_N8N, caddy logs)
   - опасная команда restart_n8n только после /confirm RESTART_N8N
   - SSH-вызов sudo /usr/local/sbin/iibot {action} для разрешённых действий
   - ответ в Telegram с stdout/stderr.
5) Работать в своём режиме Claude Code:
   - генерировать и при необходимости выполнять curl-запросы к n8n API.
6) В конце выдать человеку краткий отчёт:
   - что именно сделал в n8n
   - какие HTTP-запросы использовал
   - как протестировать: /status, /backup, /restart + /confirm RESTART_N8N."
