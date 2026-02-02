#!/usr/bin/env bash
set -euo pipefail

WF_ID="XC7hfkwDAPoa2t9L"
EXPECTED_SHA="8ecfba942dd2dfa46b305a907e5b632ce06175503e3b85e9c0cca82e57396ecf"

cd "$(dirname "$0")/.."

echo "[n8n sha guard] dryrun sha for $WF_ID"
./agent_runner.py --json "n8n: workflows_get_dryrun workflow_id=${WF_ID}" >/dev/null

REPORT="$(ls -t artifacts/*_report.json 2>/dev/null | head -n 1)" || true
if [[ -z "${REPORT:-}" ]]; then echo "FAIL: no report found in artifacts/"; exit 1; fi

SHA="$(python3 - <<'PY3' "$REPORT"
import json,sys
p=sys.argv[1]
d=json.load(open(p,"r",encoding="utf-8"))
# results can live either at top-level or inside brain_report (shortcut format)
r = d.get("results")
if r is None and isinstance(d.get("brain_report"), dict):
    r = d["brain_report"].get("results")
if not r:
    raise SystemExit("no results[] in report (top-level or brain_report)")
txt = (r[0].get("response") or {}).get("text","")
obj = json.loads(txt)
print(obj.get("sha256",""))
PY3
)"

if [[ "$SHA" != "$EXPECTED_SHA" ]]; then
  echo "FAIL: sha changed"
  echo " expected: $EXPECTED_SHA"
  echo "   actual: $SHA"
  exit 1
fi

echo "OK: sha matches $EXPECTED_SHA"
