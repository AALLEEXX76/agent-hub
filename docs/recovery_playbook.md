# Recovery / Self-Ops Playbook (MVP)

Цель: уметь проверять и лечить сервер, даже если webhook/n8n недоступен (SSH fallback).

## Команды
- recovery: ssh fallback status
- recovery: all fix
- recovery: all fix apply=1   (только с ALLOW_DANGEROUS=1)
- recovery: n8n restart
- recovery: n8n restart apply=1 (только с ALLOW_DANGEROUS=1 + confirm если попросит)

## MVP DONE
- status OK
- dryrun OK
- apply корректно гейтится/выполняется
