#!/usr/bin/env bash
set -euo pipefail

echo "[1/5] monitoring: server status (expect OK)"
./agent_runner.py --json "monitoring: server status" >/dev/null

echo "[2/5] monitoring: caddy errors since_seconds=300 (expect OK)"
./agent_runner.py --json "monitoring: caddy errors since_seconds=300" >/dev/null

echo "[3/5] monitoring: audit last=20 (expect OK)"
./agent_runner.py --json "monitoring: audit last=20" >/dev/null

echo "[4/5] monitoring: audit last=50 only_fail=true (expect OK)"
./agent_runner.py --json "monitoring: audit last=50 only_fail=true" >/dev/null

echo "[5/5] monitoring: all status (expect OK)"
./agent_runner.py --json "monitoring: all status" >/dev/null

echo "OK: monitoring shortcuts passed"
