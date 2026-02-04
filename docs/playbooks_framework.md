# Playbooks Framework (MVP)

Цель: единый “каркас” для всех плейбуков (Site/Monitoring/Recovery/n8n/…):
одинаковые правила безопасности, одинаковый формат команд, одинаковые критерии “готово”.

---

## 1) Общие принципы

- **По умолчанию безопасно:** status/check/dryrun — без изменений.
- **Изменения только явно:** `apply=1` или `mode=apply` и всегда с **confirm** (где нужно).
- **Гейты:**
  - `ALLOW_DANGEROUS=1` — для опасных операций (restart/up/down/pull и т.п.).
  - `N8N_ALLOW_WRITE=1` — для записи через Public API n8n (deploy/activate).
- **Fallback:** если webhook временно недоступен — Brain использует **SSH fallback** только для allowlist `RECOVERY_SSH_ACTIONS`.

---

## 2) Единый формат human-команд

- Статусы:
  - `monitoring: ... status`
  - `site: ...`
- Fix:
  - dryrun по умолчанию: `... fix`
  - apply только явно: `... fix apply=1`
- Опасные действия:
  - всегда требуют `confirm=<TOKEN>` и (если HIGH) `ALLOW_DANGEROUS=1`.

---

## 3) Confirm tokens (правила)

- Токен должен быть **явным и одноразово осмысленным**: `ROUTE_DEMO6`, `RESTART_N8N`, `DOWN_<SITE>`, и т.д.
- Не используем “YES/OK/123” — токен должен защищать от случайного apply.

---

## 4) Где что находится

### На ноутбуке (WSL) — source of truth (git)
- `~/agent-hub/agent_runner.py` — запускает Brain, пишет artifacts, post-apply healthcheck.
- `~/agent-hub/agent_brain.py` — парсинг human-команд → вызовы webhook/ssh fallback.
- `~/agent-hub/tools/` — утилиты (e2e, print_report, remote_healthcheck, n8n deploy tools).
- `~/agent-hub/docs/` — плейбуки/доки.
- `~/agent-hub/snapshots/INDEX.txt` — индекс снапшотов (tgz/sha256 в git НЕ храним).

### На сервере — исполнение (Hand v2 + сервисы)
- Hand v2: `/usr/local/sbin/iibotv2`, `/usr/local/lib/iibot/` (actions + manifests), audit: `/var/log/iibot/audit.jsonl`
- n8n: `/opt/n8n` (docker compose)
- сайты: `/opt/sites/<name>` (docker compose)
- Caddy: `/etc/caddy/Caddyfile`

---

## 5) Артефакты и отчёты

- Каждый запуск runner создаёт: `artifacts/YYYYMMDD-HHMMSS_report.json`
- Для apply: runner добавляет `post_apply_healthcheck` (remote_healthcheck stdout + RID/audit match).

---

## 6) E2E тесты (MVP)

- `tools/test_e2e.sh` должен стабильно возвращать `RC=0`.
- Включает проверки:
  - site block/unblock + sites fix
  - monitoring all status/fix
  - recovery gates (BLOCKED без ALLOW_DANGEROUS)
  - n8n sha guard

---

## 7) Как добавлять новый плейбук/команду (шаблон)

1) Документируем в `docs/<playbook>.md`:
   - команды
   - гейты/confirm
   - definition of done
2) Реализуем shortcut в `agent_brain.py`
3) Добавляем/обновляем e2e тесты
4) Прогоняем: `python3 -m py_compile ...` + `tools/test_e2e.sh`
5) Коммит + push

