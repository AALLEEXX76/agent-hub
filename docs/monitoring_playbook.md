# Monitoring Playbook (MVP)

Цель: один “человеческий” вход → понятный статус (OK/FAIL) + минимальная диагностика + безопасные фиксы (DRYRUN/APPLY) с гейтами.

## Команды (Brain shortcuts)

### 1) monitoring: all status
Проверяет “всё одним выстрелом”:
- server: docker_status + healthz + caddy error logs (5m) + HTTP / и /healthz
- sites: discovery по контейнерам `<name>-web-1` + HTTP HEAD `/<name>/` и классификация up/blocked/down/other
- n8n: наличие контейнера + HTTP / и /healthz + caddy errors
- disk: disk_quickcheck (через webhook, fallback ssh→iibotv2 если gateway “не понял”)

Ожидаемый результат:
- exit_code=0 если всё OK
- exit_code=1 если FAIL

### 2) monitoring: all fix [apply=1]
DRYRUN (по умолчанию):
- запускает `sites: fix` (dryrun), затем `monitoring: all status`
APPLY:
- требует `ALLOW_DANGEROUS=1`
- запускает `sites: fix apply=1`, затем `monitoring: all status`
Код выхода:
- exit_code=0 если финальный all status OK
- exit_code=1 если BLOCKED/FAIL

## Гейты безопасности
- `ALLOW_DANGEROUS=1` обязателен для любого `apply=1` в “фиксах”.

## E2E покрытие
См. `docs/e2e_tests.md`:
- `tools/test_all_fix.sh` проверяет:
  - DRYRUN при blocked site
  - APPLY снимает блокировку и возвращает OK

## TODO (следующее улучшение)
1) Добавить `monitoring: all status --json/--short` (короткий и полный режимы вывода).
2) Добавить причины FAIL:
   - server: какой именно чек провалился (root/healthz/docker/healthz-json/caddy errors)
   - sites: список down/other с http_code
   - disk: краткий итог по df (use% / free)
3) Добавить “авто-фикс n8n” в `monitoring: all fix` (не сейчас): только через recovery playbook и confirm.
