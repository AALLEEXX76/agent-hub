#!/usr/bin/env bash
set -euo pipefail

echo "[1/2] recovery: all fix (dryrun; should be OK)"
./agent_runner.py --json "recovery: all fix" >/dev/null

echo "[2/2] recovery: all fix apply=1 (expect BLOCKED + exit_code=1)"
set +e
out="$(./agent_runner.py --json "recovery: all fix apply=1")"
rc=$?
set -e
echo "$out"
test "$rc" -eq 1
grep -q "BLOCKED" <<<"$out"

echo "OK: recovery all fix blocked gate works"
