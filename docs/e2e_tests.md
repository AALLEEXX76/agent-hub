# E2E tests (Brain + Runner)

## Что это
E2E = end-to-end: проверяем, что Brain + Runner + Hand v2 реально работают вместе.

## Набор тестов
- sites fix
- monitoring: all fix
- recovery: all fix (проверка гейта)

## Термины
- "Запустить всё" = один скрипт прогоняет весь набор.
- "Отдельный тест" = запуск одного конкретного скрипта (одной проверки).

## Команды
Запустить всё:
- ./tools/test_e2e.sh

Отдельно:
- ./tools/test_sites_fix.sh
- ./tools/test_all_fix.sh
- ./tools/test_recovery_all_fix.sh

## Гейты
- recovery: all fix apply=1 без ALLOW_DANGEROUS=1 → BLOCKED + exit_code=1 (это ожидаемо).

## Exit codes
- `./agent_runner.py --json ...` теперь выходит с `exit_code` из `brain_report` (например, BLOCKED → rc=1).
- `./tools/test_e2e.sh` в целом должен завершаться с rc=0 (даже если внутри есть ожидаемый BLOCKED-тест).

## Extra: n8n workflow SHA guard

Проверяем, что workflow `XC7hfkwDAPoa2t9L` не изменился (dry-run SHA256):

- `tools/test_n8n_sha_guard.sh` — делает `n8n: workflows_get_dryrun` и сравнивает sha256 с ожидаемым.
- Этот тест включён в общий прогон `tools/test_e2e.sh`.
