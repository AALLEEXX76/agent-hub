#!/usr/bin/env bash
set -euo pipefail

echo "[1/1] monitoring: all fix apply=1 (expect OK)"
ALLOW_DANGEROUS=1 ./agent_runner.py --json 'monitoring: all fix apply=1' >/dev/null

echo "OK: monitoring all fix apply passed"
