#!/usr/bin/env bash
set -euo pipefail

echo "[1/2] recovery: n8n restart check (no confirm; expect OK)"
./agent_runner.py --json "recovery: n8n restart" >/dev/null

echo "[2/2] recovery: n8n restart apply without ALLOW_DANGEROUS (expect BLOCKED + exit_code=1)"
set +e
out="$(./agent_runner.py --json "recovery: n8n restart confirm=TEST_RESTART")"
rc=$?
set -e

report="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("report",""))' <<<"$out")"
test -n "$report"
./tools/print_report.py "$report" | tee /tmp/recovery_n8n_restart_report.txt >/dev/null

test "$rc" -eq 1
grep -q "dangerous action blocked" /tmp/recovery_n8n_restart_report.txt

echo "OK: recovery n8n restart blocked gate works"
