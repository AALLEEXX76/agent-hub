# Playbooks Framework (MVP)

Цель: единый формат команд и единые правила check→plan→apply для всех плейбуков.

## Единый формат команды
- `area: command [key=value ...]`

## Правила безопасности
- По умолчанию: DRYRUN/plan
- Любое изменение = `apply=1`
- Опасные изменения требуют `ALLOW_DANGEROUS=1`
- Confirm-токен всегда только top-level (не в args)

## Единый вывод
- Всегда печатаем `summary` (человеку)
- Всегда пишем machine-friendly JSON в artifacts/*_report.json
- exit_code=0 OK, exit_code=1 FAIL/BLOCKED

## Пример шаблона
- `monitoring: all status`
- `monitoring: all fix` (dryrun)
- `monitoring: all fix apply=1` (apply)
