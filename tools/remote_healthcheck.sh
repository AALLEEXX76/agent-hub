# Optional: run snapshot after successful apply (manual trigger)

#!/usr/bin/env bash
set -euo pipefail

RID="rq_hc_$(date +%s)_$RANDOM"
echo "RID=$RID"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

echo "--- / (first 2 lines) ---"
curl -fsS 'https://ii-bot-nout.ru/' -o "$tmp" 2>/dev/null
head -n 2 "$tmp"

echo "--- webhook:list_actions ---"
curl -fsS -X POST 'https://ii-bot-nout.ru/webhook/agent-exec' \
  -H 'Content-Type: application/json' \
  -d "{\"task\":\"ssh: run\",\"request_id\":\"$RID\",\"params\":{\"action\":\"list_actions\",\"mode\":\"check\",\"args\":{}}}" \
| python3 -c 'import sys,json; d=json.load(sys.stdin); print("got:", d.get("request_id")); print("ok:", d.get("ok"), "action:", d.get("action"), "mode:", d.get("mode"))'

echo "--- audit match (server) ---"
ssh ii-bot-nout "tail -n 800 /var/log/iibot/audit.jsonl | grep -F '$RID' || echo 'AUDIT NOT FOUND'"

# Optional: snapshot (local)
if [ "${MAKE_IIBOT_SNAPSHOT:-0}" = "1" ]; then
  echo "--- snapshot (local) ---"
  ./tools/make_iibot_snapshot.sh
fi
