# Playbooks Index

Короткая навигация по playbook-докам (MVP).

## 1) Monitoring Playbook (MVP)
Файл: `docs/monitoring_playbook.md`
Команды:
- `monitoring: all status`
- `monitoring: all fix` / `monitoring: all fix apply=1`
- `monitoring: server status`
- `monitoring: sites status`
- `monitoring: disk quickcheck`

## 2) Recovery / Self-Ops Playbook (MVP)
Файл: `docs/recovery_playbook.md`
Команды:
- `recovery: all fix` / `recovery: all fix apply=1 confirm=<TOKEN>`
- `recovery: n8n restart` / `recovery: n8n restart apply=1 confirm=<TOKEN>`

Гейты:
- apply требует `ALLOW_DANGEROUS=1` + `confirm=<TOKEN>`
- при падении webhook включается SSH fallback только для allowlist `RECOVERY_SSH_ACTIONS`

## 3) n8n Playbook (MVP)
Файл: `docs/n8n_playbook.md`
Команды:
- `monitoring: n8n status`
- `monitoring: n8n logs last=N`
- `monitoring: n8n restart confirm=<TOKEN>`
- (extra) `n8n sha guard` (dryrun)

Деплой:
- Public API: PUT `{name,nodes,connections,settings}` + activate
- write требует `N8N_ALLOW_WRITE=1`

## 4) Playbooks Framework (MVP)
Файл: `docs/playbooks_framework.md`
Что описывает:
- единый контракт check/plan/apply
- гейты (ALLOW_DANGEROUS / confirm / allowlists)
- post-apply healthcheck + артефакты

## 5) Site / VPN Playbooks
Файлы:
- `docs/e2e_tests.md` — E2E smoke-tests и критерии “готово”
- `docs/vpn_playbook.md` — VPN (позже, на отдельном сервере)
- `docs/hand_v2_spec.md` — спецификация Hand v2

## Definition of Done (Docs MVP)
1) Все playbooks лежат в `docs/`
2) Есть единый индекс `docs/PLAYBOOKS_INDEX.md`
3) Всё закоммичено и запушено в `main`
