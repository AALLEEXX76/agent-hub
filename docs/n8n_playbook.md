# n8n Playbook (MVP)

Цель: управлять n8n как продуктом: деплой workflow через Public API, активация, проверки.

## Команды/скрипты (локально, WSL)
- tools/test_n8n_sha_guard.sh
- tools/n8n_workflow_put_payload.py
- tools/n8n_deploy_workflow_api.sh

## MVP DONE
- sha guard OK
- умеем: pull workflow → сделать *.put.json → PUT → activate
