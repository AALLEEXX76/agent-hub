#!/usr/bin/env bash
set -euo pipefail

WF_ID="XC7hfkwDAPoa2t9L"
EXPECTED_SHA="2ae98281b6c56c86d8a0265dfd1c526096adeef5bbaecf5ee445a8e4d219d7a8"

echo "[n8n sha guard] dryrun sha for ${WF_ID}"

# run dryrun getter (no write)
./agent_runner.py --json "n8n: workflows_get_dryrun workflow_id=${WF_ID}" >/dev/null

REPORT="$(ls -t artifacts/*_report.json 2>/dev/null | head -n 1)" || true
if [[ -z "${REPORT:-}" ]]; then
  echo "FAIL: no report found in artifacts/"
  exit 1
fi

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

if [[ -z "${SHA:-}" ]]; then
  echo "FAIL: empty sha"
  exit 1
fi

if [[ "${SHA}" != "${EXPECTED_SHA}" ]]; then
  if [[ "${N8N_SHA_GUARD_UPDATE:-0}" == "1" ]]; then
    python3 -c "from pathlib import Path; p=Path('tools/test_n8n_sha_guard.sh'); s=p.read_text(encoding='utf-8'); import re; s=re.sub(r^EXPECTED_SHA=.*, EXPECTED_SHA="", s, flags=re.M); p.write_text(s, encoding='utf-8')"
    echo "OK: updated EXPECTED_SHA to ${SHA}"
    exit 0
  fi
  echo "FAIL: sha changed"
  echo " expected: ${EXPECTED_SHA}"
  echo "   actual: ${SHA}"
  exit 1
fi

echo "OK: sha matches ${SHA}"
