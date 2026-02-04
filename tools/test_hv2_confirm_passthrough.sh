#!/usr/bin/env bash
set -euo pipefail

echo "[extra] hv2 confirm passthrough (expect OK)"
# Direct --json call so confirm is guaranteed at top-level params
out="$(env -u ALLOW_DANGEROUS ./agent_runner.py --json 'ssh: run action=caddy_site_route mode=apply args={"name":"demo6","port":18085,"state":"present"} confirm=ROUTE_DEMO6')"
report="$(printf "%s" "$out" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("report",""))')"
[ -n "$report" ] || { echo "FAIL: no report path"; echo "$out"; exit 1; }
./tools/print_report.py "$report" | grep -q "\"confirm\": \"ROUTE_DEMO6\"" || { echo "FAIL: confirm not stored"; ./tools/print_report.py "$report"; exit 1; }
./agent_runner.py "site: status name=demo6" | grep -q "http=200"
echo "OK: hv2 confirm passthrough works"
