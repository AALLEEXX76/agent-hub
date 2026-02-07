#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   tools/n8n_deploy_workflow_api.sh <workflow_id> <local_json_path>
#
# Requires .agent_env:
#   N8N_BASE_URL=https://ii-bot-nout.ru
#   N8N_API_KEY=...

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

# Load env (prefer repo-local .agent_env)
if [[ -f ".agent_env" ]]; then
  set -a; source ".agent_env"; set +a
fi
: "${N8N_BASE_URL:?N8N_BASE_URL missing (expected like https://ii-bot-nout.ru)}"
: "${N8N_API_KEY:?N8N_API_KEY missing}"

# Normalize BASE in case someone set it with /api/v1
BASE="${N8N_BASE_URL%/}"
BASE="${BASE%/api/v1}"

TMP_PAYLOAD="$(mktemp)"
python3 - "$LOCAL_JSON" > "$TMP_PAYLOAD" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    d = json.load(f)

# Accept shapes: object | [object] | {"workflows":[object]}
if isinstance(d, dict) and "workflows" in d and isinstance(d["workflows"], list) and d["workflows"]:
    d = d["workflows"][0]
if isinstance(d, list):
    if not d:
        raise SystemExit("empty JSON array")
    d = d[0]
if not isinstance(d, dict):
    raise SystemExit("unsupported JSON shape")

# Keep only fields n8n API expects for update
keep = {"name","nodes","connections","settings"}
payload = {k: d[k] for k in keep if k in d}

# minimal sanity
for k in ("name","nodes","connections"):
    if k not in payload:
        raise SystemExit(f"missing required field in export: {k}")

print(json.dumps(payload, ensure_ascii=False))
PY

echo "[1/2] PUT /workflows/${WF_ID}"
HTTP="$(curl -sS -o /tmp/n8n_put_body.json -w "%{http_code}" \
  -X PUT \
  -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
  -H "Content-Type: application/json" \
  --data-binary @"${TMP_PAYLOAD}" \
  "${BASE}/api/v1/workflows/${WF_ID}")"
echo "HTTP=${HTTP}"
head -c 200 /tmp/n8n_put_body.json; echo

echo "[2/2] POST /workflows/${WF_ID}/activate"
HTTP2="$(curl -sS -o /tmp/n8n_act_body.json -w "%{http_code}" \
  -X POST \
  -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
  "${BASE}/api/v1/workflows/${WF_ID}/activate")"
echo "HTTP=${HTTP2}"
head -c 200 /tmp/n8n_act_body.json; echo

rm -f "$TMP_PAYLOAD"
echo "OK: deployed via API (no restart)"
