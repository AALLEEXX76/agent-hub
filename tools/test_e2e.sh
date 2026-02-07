#!/usr/bin/env bash
set -euo pipefail

./tools/test_sites_fix.sh
./tools/test_all_fix.sh
env -u ALLOW_DANGEROUS ./tools/test_recovery_all_fix.sh
env -u ALLOW_DANGEROUS ./tools/test_recovery_n8n_restart.sh

echo "[extra] n8n sha guard (expect OK)"
./tools/test_n8n_sha_guard.sh
\echo "[extra] hv2 confirm passthrough (expect OK)"
./tools/test_hv2_confirm_passthrough.sh


echo "[extra] monitoring: sites status (expect OK)"
./agent_runner.py --json 'monitoring: sites status'

echo "[extra] monitoring shortcuts (expect OK)"
./tools/test_monitoring_shortcuts.sh

echo "[extra] monitoring: all fix apply=1 (expect OK)"
./tools/test_monitoring_all_fix_apply.sh


echo "[extra] humanmode LLM guard (expect OK)"
./tools/test_humanmode_llm_guard.sh



echo "[extra] n8n deploy dryrun (expect OK)"
./tools/test_n8n_deploy_dryrun.sh


echo "[extra] n8n deploy flow dryrun (expect OK)"
./tools/test_n8n_deploy_flow_dryrun.sh
echo "OK: all e2e tests passed"
