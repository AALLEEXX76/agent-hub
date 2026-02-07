# Monitoring Playbook (MVP)

Цель: быстрые проверки "что сломалось" + безопасные фиксы через shortcuts (dryrun→apply) с понятным summary и exit_code.

## Команды (ноутбук, WSL)

### 1) Быстрый статус сервера
./agent_runner.py --json "monitoring: server status"

### 2) Ошибки Caddy за 5 минут
./agent_runner.py --json "monitoring: caddy errors since_seconds=300"

### 3) Статус сайтов
./agent_runner.py --json "monitoring: sites status"

### 4) Общий статус (one-shot)
./agent_runner.py --json "monitoring: all status"

### 5) Общий fix (dryrun / apply)
./agent_runner.py --json "monitoring: all fix"
./agent_runner.py --json "monitoring: all fix apply=1"

### 6) Zabbix
./agent_runner.py --json "monitoring: zabbix quickcheck"
./agent_runner.py --json "monitoring: zabbix agent info"

## Правила
- Любые изменения: `apply=1`
- Опасные изменения: `ALLOW_DANGEROUS=1` + `confirm=TOKEN`

## Критерий OK
- summary содержит OK
- exit_code=0
