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
