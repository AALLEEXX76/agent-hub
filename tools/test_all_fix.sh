#!/usr/bin/env bash
set -euo pipefail

name="${1:-demo6}"
token_name="${name^^}"
token_name="${token_name//-/_}"

echo "[0/4] ensure $name is unblocked (idempotent pre-step)"
ALLOW_DANGEROUS=1 ./agent_runner.py --json "monitoring: all fix apply=1" >/dev/null || true

echo "[1/4] block $name (expect 404)"
ALLOW_DANGEROUS=1 ./agent_runner.py --json "site: block name=$name confirm=BLOCK_${token_name}_ALLFIX_TEST" >/dev/null

echo "[2/4] monitoring: all fix (dryrun; expect would run unblock)"
./agent_runner.py --json "monitoring: all fix" || true

echo "[3/4] monitoring: all fix apply=1 (expect unblocked)"
ALLOW_DANGEROUS=1 ./agent_runner.py --json "monitoring: all fix apply=1" >/dev/null

echo "[4/4] monitoring: all status (expect OK + blocked=0)"
./agent_runner.py --json "monitoring: all status"
