# Playbooks Framework (MVP)

Цель: единый каркас для всех “человеческих” команд агента, чтобы любой playbook работал одинаково:
CHECK → PLAN → APPLY, с гейтами (ALLOW_DANGEROUS + confirm), понятным итогом (OK/FAIL), стабильным JSON для runner, и post-apply healthcheck.

## Стандарт результата (для Runner)
Любая команда должна возвращать:
- `ok: true|false`
- `exit_code: 0|1`
- `summary: "..."`
- `report: "artifacts/..._report.json"`

Внутри `*_report.json`:
- `status: OK|FAIL|BLOCKED`
- `reason` (только если FAIL/BLOCKED)
- `results[]` (сырьё: какие проверки/действия выполнены)
- `next_cmd` (если есть “следующий правильный шаг”)

## Единая политика безопасности
1) Любое изменение = только через `apply`.
2) Любой `apply` требует:
   - `ALLOW_DANGEROUS=1` (если операция mutating/HIGH)
   - `confirm=TOKEN` (для точечных опасных действий)
3) Если гейт не выполнен → `BLOCKED` и `exit_code=1`.

## Единые режимы
### CHECK
- только чтение/диагностика
- формирует “что не так” и “что можно сделать”
- `exit_code=0` если OK, иначе `1`

### PLAN
- строит план действий (без выполнения)
- возвращает список шагов и confirm tokens (если нужны)
- по умолчанию `exit_code=0`, но может быть `1` если уже видно, что выполнить нельзя (например, нет доступа)

### APPLY
- выполняет действия строго по плану
- после успеха обязателен post-apply healthcheck (уже встроен в runner)
- при любой ошибке → `ok=false`, `exit_code=1`

## Confirm tokens
- короткие, уникальные, человекочитаемые (пример: `ROUTE_DEMO6`, `RESTART_N8N`)
- в отчёте должны быть подсказки:
  - `next_cmd: "... confirm=TOKEN"`

## Стандарты именования команд
- `monitoring: ...`
- `recovery: ...`
- `site: ...`
- `n8n: ...`
- `vpn: ...`

## Standard fallbacks
Если gateway/webhook недоступен:
- для read-only можно fallback на SSH (если действие есть в Hand v2)
- для self-ops (restart/up/down) — только recovery playbook (forced SSH fallback)

## Требования к playbook-докам
Каждый `docs/*_playbook.md` содержит:
1) цель
2) список команд (shortcuts)
3) какие Hand v2 actions нужны (SAFE/HIGH)
4) гейты
5) healthchecks
6) минимальные E2E тесты + где они лежат

## TODO (следующее)
1) Добавить единый раздел “Policy” в CLAUDE.md:
   - гейты, confirm, exit codes, report schema
2) Добавить `docs/report_schema.md` (минимальная спецификация структуры report.json)
3) Добавить шаблон playbook: `docs/_template_playbook.md`
