# n8n Playbook (MVP)

Цель: управлять n8n как продуктом (статус/логи/рестарт/деплой воркфлоу через Public API) безопасно и воспроизводимо: CHECK → APPLY + гейты + healthcheck.

## Базовые команды (Brain shortcuts)

### 1) monitoring: n8n status
Проверяет:
- HTTP `/` и `/healthz` (через Caddy)
- контейнеры n8n/postgres (docker_status / compose_ps)
- ошибки Caddy за последние 5 минут

Ожидаемо:
- exit_code=0 если OK
- exit_code=1 если FAIL

### 2) monitoring: n8n logs last=N
Выводит последние N строк compose_logs для `/opt/n8n`.

### 3) monitoring: n8n restart [confirm=TOKEN]
- Без `confirm=`: CHECK (покажет, что нужно confirm)
- С `confirm=`: APPLY через webhook (self-queued), требуется `ALLOW_DANGEROUS=1`

Примечание: если webhook недоступен → использовать recovery-команду (см. ниже).

## Recovery команды (когда webhook/n8n недоступен)

### 4) recovery: n8n restart [confirm=TOKEN]
- Forced SSH fallback (обходит webhook)
- APPLY требует `confirm=` и `ALLOW_DANGEROUS=1`

## Деплой n8n workflow (через Public API)

### Правило
Workflow деплоим **только** через Public API:
- PUT `/api/v1/workflows/{id}` с payload **только** `{name,nodes,connections,settings}`
- затем activate
(Полный JSON workflow с `id` и прочими полями API не принимает.)

### Рекомендуемый пайплайн
1) Сгенерировать `*.put.json` (strip до {name,nodes,connections,settings})
2) PUT через `tools/n8n_deploy_workflow_api.sh`
3) Активировать workflow
4) Healthcheck: `monitoring: n8n status` + (опционально) `tools/remote_healthcheck.sh`

## Гейты безопасности
- Любой `apply` для рестартов: `ALLOW_DANGEROUS=1`
- Любой рестарт: `confirm=TOKEN`

## E2E покрытие (минимум)
См. `docs/e2e_tests.md`:
- наличие smoke-проверок для monitoring/recovery
- после изменений в n8n — прогон `./tools/test_e2e.sh`

## TODO (следующее)
1) Добавить shortcuts:
   - `n8n: workflow list`
   - `n8n: workflow get id=...`
   - `n8n: workflow deploy id=... file=...`
   - `n8n: executions latest workflowId=...`
2) Добавить “n8n deploy playbook” с check/plan/apply:
   - check: validate put.json schema (no id)
   - apply: PUT + activate + healthcheck
