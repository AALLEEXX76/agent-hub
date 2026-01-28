#!/usr/bin/env bash
set -euo pipefail

name="${1:-demo6}"

token_name="${name^^}"
token_name="${token_name//-/_}"

echo "[1/4] block $name (expect 404)"
ALLOW_DANGEROUS=1 ./agent_runner.py --json "site: block name=$name confirm=BLOCK_${token_name}_TEST" >/dev/null

echo "[2/4] sites: fix dryrun (expect hint unblock)"
./agent_runner.py --json "sites: fix" | tee /tmp/sites_fix_dryrun.json >/dev/null || true

echo "[3/4] unblock via sites: fix apply=1 (expect 200)"
ALLOW_DANGEROUS=1 ./agent_runner.py --json "sites: fix apply=1" >/dev/null

echo "[4/4] site: status (expect OK http=200)"
./agent_runner.py --json "site: status name=$name"
