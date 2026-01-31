# VPN Playbook (MVP)

Цель: поднять VPN на отдельном сервере (или на текущем, если нужно для теста) безопасно и воспроизводимо: CHECK → APPLY + гейты + healthcheck.

## Scope MVP
- 1 сервер = 1 VPN-инстанс
- доступ к VPN должен проверяться автоматом (порт/сервис/конфиг)
- все изменения через action(ы) Hand v2 + manifests + audit + post-apply healthcheck

## Команды (планируемые Brain shortcuts)
### 1) vpn: status
Проверяет:
- сервис VPN активен (systemd/compose)
- порты слушаются (ss)
- firewall/ufw правила на нужные порты
- базовый self-test (например, health endpoint / simple handshake check)

Ожидаемо:
- exit_code=0 если OK
- exit_code=1 если FAIL

### 2) vpn: logs last=N
Выводит последние N строк логов VPN (journal/compose_logs).

### 3) vpn: setup [apply=1] [confirm=TOKEN]
- DRYRUN по умолчанию: что будет сделано (пакеты/конфиги/ufw/keys)
- APPLY: требует `ALLOW_DANGEROUS=1` и `confirm=TOKEN`
- После APPLY обязателен healthcheck (vpn: status)

## Hand v2 actions (план)
SAFE:
- vpn_status (read-only: ss/ufw/systemctl/journal tail)
- vpn_logs (read-only)
HIGH:
- vpn_setup (install/config/enable/ufw/open ports)
- vpn_restart (restart service)

## Гейты безопасности
- Любой APPLY: `ALLOW_DANGEROUS=1`
- Любое HIGH изменение: `confirm=TOKEN`

## E2E покрытие (минимум)
- dryrun setup не меняет систему, exit_code=0
- apply без ALLOW_DANGEROUS=1 → BLOCKED + exit_code=1
- apply с ALLOW_DANGEROUS=1+confirm → OK + vpn: status OK

## TODO (следующее)
1) Выбрать конкретную технологию VPN (WireGuard / Xray / Outline) и зафиксировать порты/конфиги.
2) Добавить actions+manifests под выбранный VPN.
3) Добавить в Brain shortcuts и E2E тесты.
