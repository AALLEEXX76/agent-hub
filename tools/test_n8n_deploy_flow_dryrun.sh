#!/usr/bin/env bash
set -euo pipefail

WF_ID="XC7hfkwDAPoa2t9L"

echo "[n8n deploy flow dryrun] GET via API -> build PUT payload -> sha guard -> remote healthcheck (no write)"

# Load env (prefer repo-local .agent_env)
if [[ -f ".agent_env" ]]; then
  set -a; source ".agent_env"; set +a
fi

: "${N8N_BASE_URL:?N8N_BASE_URL missing (expected like https://ii-bot-nout.ru)}"
: "${N8N_API_KEY:?N8N_API_KEY missing}"

BASE="${N8N_BASE_URL%/}"
BASE="${BASE%/api/v1}"

TMP_EXPORT="$(mktemp)"
TMP_PUT="$(mktemp)"
trap 'rm -f "$TMP_EXPORT" "$TMP_PUT"' EXIT

echo "[1/4] GET /workflows/${WF_ID}"
curl -fsS -H "X-N8N-API-KEY: ${N8N_API_KEY}" "${BASE}/api/v1/workflows/${WF_ID}" > "$TMP_EXPORT"

echo "[2/4] build PUT payload (tools/n8n_workflow_put_payload.py)"
./tools/n8n_workflow_put_payload.py "$TMP_EXPORT" "$TMP_PUT" >/dev/null

echo "[3/4] sanity: PUT payload keys allowed (no id)"
python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p,"r",encoding="utf-8")); allowed={"name","nodes","connections","settings","staticData","tags","shared","active","createdAt","updatedAt"}; bad=sorted([k for k in d.keys() if (k not in allowed) or (k=="id")]); print("OK: put payload keys allowed" if not bad else ("FAIL: unexpected keys: "+",".join(bad))); sys.exit(0 if not bad else 1)' "$TMP_PUT"

echo "[4/4] sha guard + remote healthcheck"
./tools/test_n8n_sha_guard.sh
./tools/remote_healthcheck.sh

echo "OK: n8n deploy flow dryrun passed"
