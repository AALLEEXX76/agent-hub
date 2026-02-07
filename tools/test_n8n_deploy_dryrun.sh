#!/usr/bin/env bash
set -euo pipefail

WF_ID="XC7hfkwDAPoa2t9L"

echo "[n8n deploy dryrun] fetch -> build put payload -> sha guard (no write)"

./tools/test_n8n_sha_guard.sh

echo "[n8n deploy dryrun] sanity: PUT payload schema (no extra keys)"
rg -q "keep = \{\"name\",\"nodes\",\"connections\",\"settings\"\}" tools/n8n_deploy_workflow_api.sh
rg -q "OPTIONAL = \(\"staticData\", \"tags\", \"shared\", \"active\", \"createdAt\", \"updatedAt\"\)" tools/n8n_workflow_put_payload.py


echo "OK: sha guard passed; deploy would run tools/n8n_deploy_workflow_api.sh (PUT payload only name/nodes/connections/settings) ${WF_ID}"
