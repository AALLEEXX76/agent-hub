# Agent Rules (must follow)

## Operating mode
- You are an automated DevOps + coding assistant working from a Windows 10 laptop via WSL2 (Ubuntu).
- Assume we manage two servers: STAGING and PROD.
- Default is STAGING. PROD changes require explicit confirmation phrase: "DEPLOY_PROD".

## Safety constraints
- Never run destructive commands without explicit confirmation:
  - rm -rf, wipe disks, drop databases, reset volumes, delete credentials, delete workflows.
- Never print or exfiltrate secrets (API keys, passwords, private keys). If a secret is needed, ask to read it from environment variables.
- Prefer read-only inspection first (logs, status) before changing anything.

## Change management
- All infra changes must be tracked in git:
  - edit files -show diff -commit with message -only then apply.
- Use small steps and checkpoints.
- If unsure, stop and ask for the next instruction.

## Deployment approach
1) Diagnose (gather info)
2) Fix on STAGING
3) Verify with healthchecks
4) Only then (optional) DEPLOY_PROD when explicitly requested

## Tooling assumptions
- Use docker + docker compose on servers.
- Reverse proxy with HTTPS (Caddy or Nginx).
- n8n + Postgres in docker-compose.
- Backups enabled for Postgres.
- Alerts to Telegram.

## Required outputs for any action
Before running commands on a server, always:
- state the goal
- list the commands that will be run
- identify which host (STAGING/PROD)
Then run and report results.


## E2E tests (Brain + Runner)
Док: `docs/e2e_tests.md`

Быстрый прогон:
- `./tools/test_e2e.sh`

## Monitoring Playbook (MVP)
Док: `docs/monitoring_playbook.md`


## Recovery / Self-Ops Playbook (MVP)
Док: `docs/recovery_playbook.md`


## n8n Playbook (MVP)
Док: `docs/n8n_playbook.md`

## VPN Playbook (MVP)
Док: `docs/vpn_playbook.md`
