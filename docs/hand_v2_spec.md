# Hand v2 (iibot) — contract & actions

## Goal
Universal, safe executor for infrastructure actions with audit log, dry-run, and confirmation gates.

## Request (to Agent Executor webhook)
{
  "task": "ssh: run",
  "params": {
    "action": "<action_name>",
    "args": { },
    "mode": "check|plan|apply",
    "confirm": "<token_optional>"
  }
}

## Response (normalized)
{
  "ok": true|false,
  "exit_code": 0|1,
  "action": "<action_name>",
  "mode": "check|plan|apply",
  "stdout": "",
  "stderr": "",
  "artifacts": [],
  "meta": { "changed": false, "warnings": [] }
}

## Danger levels
- safe: status/health/read-only
- medium: service reload/deploy without network changes
- high: network/iptables/wireguard/users/sudo/DNS

## Gates
- high requires:
  - ALLOW_DANGEROUS=1 (or dedicated flag)
  - confirm token in request

## Server layout
/usr/local/lib/iibot/
  iibot.py (dispatcher)
  actions/*.py
  manifests/*.json

## Mandatory action properties
- idempotent
- supports mode=check at minimum
- writes audit log JSONL
- returns stable JSON
