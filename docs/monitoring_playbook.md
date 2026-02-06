# Monitoring Playbook (MVP)

Цель: быстрый статус -> безопасный dry-run fix -> apply fix (с гейтами).

## Команды

### 1) Общий статус
./agent_runner.py --json "monitoring: all status"

### 2) Общий dry-run fix (ничего не меняет)
./agent_runner.py --json "monitoring: all fix"

### 3) Общий apply fix (меняет, требует гейтов/confirm там где нужно)
./agent_runner.py --json "monitoring: all fix apply=1"

### 4) Статус сайтов
./agent_runner.py --json "monitoring: sites status"

### 5) Статус сервера
./agent_runner.py --json "monitoring: server status"

## Правило
Всегда делай: status -> fix (dryrun) -> fix apply=1 (если нужно).
