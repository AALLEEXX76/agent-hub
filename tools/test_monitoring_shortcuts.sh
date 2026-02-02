#!/usr/bin/env bash
set -euo pipefail

echo "[1/3] monitoring: server status (expect OK)"
./agent_runner.py --json 'monitoring: server status' >/dev/null

echo "[2/3] monitoring: caddy errors since_seconds=300 (expect OK)"
./agent_runner.py --json 'monitoring: caddy errors since_seconds=300' >/dev/null

echo "[3/3] monitoring: all status (expect OK)"
./agent_runner.py --json 'monitoring: all status' >/dev/null

echo "OK: monitoring shortcuts passed"
