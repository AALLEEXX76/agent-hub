# Monitoring Playbook (MVP)

Цель: быстрые статусы + диагностика + безопасные автофиксы через Brain shortcuts.

## Команды (как пользоваться)

Статусы (SAFE):
- monitoring: server status
- monitoring: caddy errors since_seconds=300
- monitoring: all status
- monitoring: sites status

Автофикс:
- monitoring: all fix            (dryrun)
- monitoring: all fix apply=1    (только с ALLOW_DANGEROUS=1)

E2E:
- tools/test_e2e.sh

Снапшот:
- MAKE_IIBOT_SNAPSHOT=1 tools/remote_healthcheck.sh

## Критерий “MVP DONE”
- Все shortcuts работают
- E2E зелёный
- Этот файл в git без мусора heredoc
