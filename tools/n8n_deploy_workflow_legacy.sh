#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   tools/n8n_deploy_workflow.sh <workflow_id> <local_json_path>
#
# Env overrides (optional):
#   SSH_HOST=ii-bot-nout
#   CONTAINER=n8n-n8n-1
#   COMPOSE_FILE=/opt/n8n/docker-compose.yml
#   N8N_SERVICE=n8n

WF_ID="${1:-}"
LOCAL_JSON="${2:-}"

if [[ -z "${WF_ID}" || -z "${LOCAL_JSON}" ]]; then
  echo "Usage: $0 <workflow_id> <local_json_path>" >&2
  exit 2
fi

if [[ ! -f "${LOCAL_JSON}" ]]; then
  echo "ERROR: file not found: ${LOCAL_JSON}" >&2
  exit 2
fi

SSH_HOST="${SSH_HOST:-ii-bot-nout}"
CONTAINER="${CONTAINER:-n8n-n8n-1}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/n8n/docker-compose.yml}"
N8N_SERVICE="${N8N_SERVICE:-n8n}"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
REMOTE_JSON="/tmp/n8n_workflow_${WF_ID}_${STAMP}.json"
REMOTE_IN_CONTAINER="/tmp/n8n_workflow_import.json"

echo "[1/4] Upload JSON to server: ${SSH_HOST}:${REMOTE_JSON}"
scp -q "${LOCAL_JSON}" "${SSH_HOST}:${REMOTE_JSON}"

echo "[2/4] Copy JSON into container: ${CONTAINER}:${REMOTE_IN_CONTAINER}"
ssh "${SSH_HOST}" "docker cp '${REMOTE_JSON}' '${CONTAINER}:${REMOTE_IN_CONTAINER}'"

echo "[3/4] Import workflow JSON"
ssh "${SSH_HOST}" "docker exec -i '${CONTAINER}' n8n import:workflow --input='${REMOTE_IN_CONTAINER}'"

echo "[4/4] Publish + restart n8n to apply changes"
ssh "${SSH_HOST}" "docker exec -i '${CONTAINER}' n8n publish:workflow --id '${WF_ID}' || docker exec -i '${CONTAINER}' n8n update:workflow --id '${WF_ID}' --active=true"
ssh "${SSH_HOST}" "docker compose -f '${COMPOSE_FILE}' restart '${N8N_SERVICE}'"

echo "OK: deployed workflow ${WF_ID}"
