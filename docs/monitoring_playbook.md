# Monitoring Playbook (MVP)

Цель: единые human-команды для статусов/диагностики/фиксов с безопасными гейтами (check/dryrun по умолчанию, apply только явно).

## Команды (human)

### 1) Общий статус
- `monitoring: all status`
  - ожидаем: `all status OK (sites total=N up=N blocked=0 down=0 other=0)`

### 2) Сервер
- `monitoring: server status`
  - проверяет: `/` + `/healthz` + docker_status + ошибки Caddy за 5м

### 3) Сайты
- `monitoring: sites status`
  - список сайтов + up/blocked/down/other (HTTP probe + docker контейнеры)

### 4) Диск
- `monitoring: disk quickcheck`
  - `df -h /` + `df -i /`

## Fix (авто-исправления)

### 5) Общий fix
- Dry-run:
  - `monitoring: all fix`
  - ожидаем: `... DRYRUN ... (would run: site: unblock name=<site> confirm=ROUTE_<SITE>) ...`
- Apply:
  - `monitoring: all fix apply=1`
  - ожидаем: `all fix APPLY ... then all status OK ...`

## Гейты и безопасность

- Все статусы: SAFE, без confirm.
- Любой apply, который меняет состояние (route/unblock/up/down/restart) — требует confirm токен (и где нужно — `ALLOW_DANGEROUS=1`).

## Definition of Done (MVP)

1) `tools/test_e2e.sh` стабильно проходит (RC=0).
2) `monitoring: all status` стабильно OK на “здоровом” сервере.
3) `monitoring: all fix` dryrun показывает корректные “would run …”.
4) `monitoring: all fix apply=1` реально чинит и затем `monitoring: all status` = OK.
5) После apply выполняется post-apply remote_healthcheck и пишет результат в artifacts report.
