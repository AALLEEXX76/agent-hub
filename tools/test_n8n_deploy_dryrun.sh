#!/usr/bin/env bash
set -euo pipefail

WF_ID="XC7hfkwDAPoa2t9L"

echo "[n8n deploy dryrun] fetch -> build put payload -> sha guard (no write)"

./tools/test_n8n_sha_guard.sh

echo "OK: sha guard passed; deploy would run tools/n8n_deploy_workflow_api.sh (PUT payload only name/nodes/connections/settings) ${WF_ID}"
