# Recovery / Self-Ops Playbook (MVP)

Цель: восстановление управления, когда n8n/webhook недоступен, и безопасные “само-операции” через SSH fallback.

## Команды (Brain shortcuts)

### 1) recovery: n8n restart [confirm=TOKEN]
- Без `confirm=` работает в режиме CHECK (показывает, что нужно confirm).
- С `confirm=TOKEN` выполняет APPLY через **forced SSH fallback** (обходит webhook/n8n).
- Для APPLY дополнительно требуется `ALLOW_DANGEROUS=1` (гейт среды).

Ожидаемый результат:
- CHECK без confirm: exit_code=1 (blocked/need confirm)
- APPLY с confirm (+ALLOW_DANGEROUS=1): exit_code=0 при успехе

### 2) recovery: all fix [apply=1] [confirm=TOKEN]
Логика:
1) Сначала `monitoring: all status`
2) DRYRUN (по умолчанию): печатает, что бы сделал (sites fix apply=1; n8n restart confirm=TOKEN)
3) APPLY:
   - требует `ALLOW_DANGEROUS=1`
   - если есть blocked sites → выполняет `sites: fix apply=1`
   - если n8n не OK и есть confirm → делает n8n restart через forced SSH fallback
   - затем повторно `monitoring: all status`

Коды выхода:
- DRYRUN: exit_code = 0/1 по результату initial all status
- APPLY без `ALLOW_DANGEROUS=1`: exit_code=1 (BLOCKED)
- APPLY: exit_code=0 если финальный all status OK, иначе 1

## Гейты безопасности
- Любой APPLY требует `ALLOW_DANGEROUS=1`.
- Рестарт n8n в APPLY требует `confirm=TOKEN`.

## E2E покрытие
См. `docs/e2e_tests.md`:
- `tools/test_recovery_all_fix.sh` проверяет:
  - DRYRUN OK
  - APPLY без ALLOW_DANGEROUS=1 → ожидаемый BLOCKED + exit_code=1

## TODO (следующее улучшение)
1) Добавить `recovery: n8n up` (если n8n был down, поднять compose_up через SSH fallback).
2) Добавить “webhook down detector” в Runner: авто-fallback на SSH для выбранных self-ops.
3) Добавить нормализованный `reason` при BLOCKED/FAIL (один код, одна причина).
