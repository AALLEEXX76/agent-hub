#!/usr/bin/env bash
set -euo pipefail

URL="${TURBO_URL:-}"
TOK="${TURBO_TOKEN-:-}"

if [ -z "$URL" ] || [ -z "$TOK" ]; then
  echo "ERROR: set TURBO_URL and TURBO_TOKEN first"
  exit 2
fi

echo "[turbo edge guard] URL=$URL"

pywrite() {
  python3 -c 'import json,sys; open(sys.argv[1],"w",encoding="utf-8").write(json.dumps({"cmd":sys.argv[2]}))' "$1" "$2"
}

echo "[1/2] without token (expect 401 unauthorized)"
pywrite /tmp/turbo_no_token.json "set -e; echo SHOULD_NOT_RUN; whoami; id"
code=$(curl -sSS -o /tmp/turbo_no_token.out -w "%{http_code}" -X POST "$URL" \
  -H "Content-Type: application/json" \
  --data-binary "@/tmp/turbo_no_token.json" || true)
head=$(head -c 140 /tmp/turbo_no_token.out 2>/dev/null || true)
printf 'http=%s body_head=%q\n' "$code" "$head"
[ "$code" = "401" ] || { echo "FAIL: expected 401"; exit 1; }

echo "[2/2] with token (expect 200 + OK_SECURE)"
pywrite /tmp/turbo_with_token.json "set -e; echo OK_SECURE; whoami; id"
code2=$(curl -sSS -o /tmp/turbo_with_token.out -w "%{http_code}" -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "X-Turbo-Token: $TOK" \
  --data-binary "@/tmp/turbo_with_token.json" || true)
body2=$(cat /tmp/turbo_with_token.out 2>/dev/null || true)
printf 'http=%s body_head=%q\n ' "$code2" "$(echo "$body2" | head -c 200 | tr '\n' ' ')"
[ "$code2" = "200" ] || { echo "FAIL: expected 200"; exit 2; }
echo "$body2" | grep -q "OK_SECURE" || { echo "FAIL: OK_SECURE not found"; exit 3; }

echo "OK: turbo edge guard passed"
