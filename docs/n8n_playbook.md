# n8n Playbook (MVP)

Цель: безопасный деплой workflow через Public API без рестарта + healthcheck.

## Команды (ноутбук, WSL)

### 1) Dry-run sha guard
./agent_runner.py --json "n8n: workflow sha guard workflow_id=XC7hfkwDAPoa2t9L"

### 2) Deploy workflow (только через PUT payload {name,nodes,connections,settings})
./tools/n8n_deploy_workflow_api.sh XC7hfkwDAPoa2t9L

### 3) Healthcheck после деплоя
./tools/remote_healthcheck.sh

## Критерий OK
- webhook /webhook/agent-exec отвечает
- list_actions OK
- audit.jsonl содержит запись по request_id
