#!/usr/bin/env bash
set -euo pipefail

RID="rq_hc_$(date +%s)_$RANDOM"
echo "RID=$RID"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

echo "--- / (first 2 lines) ---"
curl -ksS 'https://ii-bot-nout.ru/' -o "$tmp" 2>/dev/null
head -n 2 "$tmp"

echo "--- webhook:list_actions ---"
resp_json="$(curl -ksSf -X POST 'https://ii-bot-nout.ru/webhook/agent-exec' \
  -H 'Content-Type: application/json' \
  -d "{\"task\":\"ssh: run\",\"request_id\":\"$RID\",\"params\":{\"action\":\"list_actions\",\"mode\":\"check\",\"args\":{}}}")"

got="$(python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("request_id",""))' <<<"$resp_json")"
python3 -c 'import sys,json; d=json.load(sys.stdin); print("got:", d.get("request_id")); print("ok:", d.get("ok"), "action:", d.get("action"), "mode:", d.get("mode"))' <<<"$resp_json"

echo "--- audit match (server) ---"
if [ -n "${got:-}" ]; then
  ssh ii-bot-nout "tail -n 800 /var/log/iibot/audit.jsonl | grep -F '$got' || echo 'AUDIT NOT FOUND'"
else
  echo "AUDIT NOT FOUND (no request_id in response)"
fi

# Optional: snapshot (local)
if [ "${MAKE_IIBOT_SNAPSHOT:-0}" = "1" ]; then
  echo "--- snapshot (local) ---"
  ./tools/make_iibot_snapshot.sh
fi
