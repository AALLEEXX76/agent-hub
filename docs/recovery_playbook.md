# Recovery / Self-Ops Playbook (MVP)

Цель: чтобы агент мог **восстанавливаться и чинить критичные вещи**, даже если webhook/n8n временно недоступен (SSH fallback + жёсткие гейты).

## Принципы

- По умолчанию: **check / dryrun** (без изменений).
- Любой **apply**: только явно + гейты.
- При падении webhook: Brain использует **SSH fallback** (только allowlist действий).

## Команды (human)

### 1) Общий recovery-fix

- Dry-run:
  - `recovery: all fix`
  - ожидаем: `... DRYRUN ...` (что *было бы* сделано)

- Apply:
  - `recovery: all fix apply=1 confirm=<TOKEN>`
  - ожидаем: если нет гейтов → `BLOCKED`, если гейты включены → выполнит fix и даст итоговый статус

### 2) Recovery: n8n restart

- Check:
  - `recovery: n8n restart`
  - ожидаем: OK (без рестарта, только проверка/план)

- Apply:
  - `recovery: n8n restart apply=1 confirm=<TOKEN>`
  - ожидаем: если нет гейтов → `BLOCKED`, если гейты включены → рестарт и post-apply healthcheck

## Гейты и безопасность

- Любой `apply=1` в recovery требует:
  - `ALLOW_DANGEROUS=1`
  - `confirm=<TOKEN>` (явное подтверждение)

## Definition of Done (MVP)

1) `tools/test_e2e.sh` проходит (есть проверки на BLOCKED-гейты для recovery apply).
2) SSH fallback работает только для allowlist действий (RECOVERY_SSH_ACTIONS).
3) После успешного apply выполняется post-apply remote_healthcheck и пишет результат в artifacts report.
