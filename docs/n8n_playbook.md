# n8n Playbook (MVP)

Цель: управлять n8n **предсказуемо и безопасно**: проверять состояние, смотреть логи/исполнения, деплоить workflow через Public API, активировать, и иметь sha-guard от “тихих” изменений.

## Принципы

- По умолчанию: read-only проверки.
- Любой деплой/активация — только явным действием и с gate `N8N_ALLOW_WRITE=1`.
- Для критичных workflow используем sha-guard (dryrun по умолчанию).

## Команды (human)

### 1) Статус n8n
- `monitoring: n8n status`
  - проверяет: `/` + `/healthz` + `compose_ps /opt/n8n` + ошибки Caddy
  - ожидаем: OK (HTTP 200/200, контейнеры up)

### 2) Логи n8n
- `monitoring: n8n logs last=N`
  - вызывает: `compose_logs /opt/n8n` (последние N строк)
  - ожидаем: OK + хвост логов

### 3) Рестарт n8n (опасно)
- `monitoring: n8n restart confirm=<TOKEN>`
  - без confirm → только check/plan
  - с confirm → `compose_restart /opt/n8n` (HIGH)
  - gate: `ALLOW_DANGEROUS=1` + `confirm=<TOKEN>`

## Деплой workflow (Public API)

### Истина (как деплоим правильно)
- PUT `/api/v1/workflows/{id}` только с payload:
  - `{name, nodes, connections, settings}`
- Затем activate:
  - POST `/api/v1/workflows/{id}/activate`

В repo есть скрипты:
- `tools/n8n_workflow_put_payload.py` — делает `*.put.json` из полного workflow json
- `tools/n8n_deploy_workflow_api.sh` — выполняет PUT + activate (при `N8N_ALLOW_WRITE=1`)

### 4) SHA guard (защита от “тихих” изменений)
- (extra) `n8n sha guard` (dryrun)
  - ожидаем: sha matches для workflow `XC7hfkwDAPoa2t9L`

## Gate’ы

- read-only (status/logs/sha-guard dryrun): SAFE
- write (deploy/activate): требует `N8N_ALLOW_WRITE=1`
- restart (compose_restart): требует `ALLOW_DANGEROUS=1` + `confirm=<TOKEN>`

## Definition of Done (MVP)

1) `monitoring: n8n status` стабильно OK.
2) `monitoring: n8n logs last=50` возвращает хвост логов.
3) Деплой через Public API работает только через `{name,nodes,connections,settings}` + activate.
4) SHA guard для `XC7hfkwDAPoa2t9L` проходит и ловит несовпадение sha (если подменить).
