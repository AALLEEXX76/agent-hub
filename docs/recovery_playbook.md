# Recovery Playbook (MVP)

Цель: восстановление, когда webhook/n8n недоступен, и быстрые проверки после фикса.

## Команды (ноутбук, WSL)

### 1) Dry-run общий recovery
./agent_runner.py --json "recovery: all fix"

### 2) Apply recovery (опасно: требует ALLOW_DANGEROUS=1)
ALLOW_DANGEROUS=1 ./agent_runner.py --json "recovery: all fix apply=1"

### 3) Перезапуск n8n (проверка / apply)
./agent_runner.py --json "recovery: n8n restart"
ALLOW_DANGEROUS=1 ./agent_runner.py --json "recovery: n8n restart apply=1"

## Если webhook лежит (502)
Brain должен уйти в SSH fallback (allowlist) и выполнить восстановление по SSH.

## Критерий OK
- https://ii-bot-nout.ru/ -> 200
- webhook list_actions отвечает
- в /var/log/iibot/audit.jsonl есть запись по request_id

## Проверки (быстро)
- `./agent_runner.py --json "monitoring: server status"`
- `./agent_runner.py --json "monitoring: all status"`
- `./agent_runner.py --json "recovery: all fix"`

## Типовые сценарии
### 1) webhook 502 / n8n лежит
Ожидаем: Brain уходит в SSH fallback (allowlist) и выполняет восстановление.

### 2) apply заблокирован
Если `apply=1` без `ALLOW_DANGEROUS=1` — должен быть BLOCKED и exit_code=1.


### Проверка SSH fallback (эмуляция webhook 502)
AGENT_EXEC_URL=https://ii-bot-nout.ru/webhook/agent-exec__bad ./agent_runner.py --json "recovery: all fix"

Ожидаем: request_id вида `rq_sshfb_...` в отчёте.
