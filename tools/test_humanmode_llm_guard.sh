#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cd ..

# E2E: human phrase -> LLM planner -> validate_plan -> execute
# Guard: LLM may use only Hand v2 actions from manifests cache; confirm must not be inside params.args.

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "SKIP: ANTHROPIC_API_KEY not set"
  exit 0
fi

python3 -c "import json,subprocess,sys
from pathlib import Path

# Warm up manifests cache (so validate_plan has hv2_index)
subprocess.run([\"./agent_runner.py\",\"--json\",\"ssh: run action=list_actions mode=check args={}\"],capture_output=True,text=True)

# This should go through LLM planning (not a shortcut)
TASK=\"Please check server status (HTTP root + /healthz, docker, and caddy errors last 5 minutes) and summarize the result.\"

out=subprocess.run([\"./agent_runner.py\",\"--json\",TASK],capture_output=True,text=True)

try:
  j=json.loads((out.stdout or \"\").strip() or \"{}\")
except Exception:
  print(\"FAIL: runner output not json:\", (out.stdout or \"\")[:2000])
  raise

rp=j.get(\"report\")
if not rp:
  print(\"FAIL: no report in runner output:\", j)
  sys.exit(1)

rep=json.load(open(rp,\"r\",encoding=\"utf-8\"))
br = rep.get(\"brain_report\") if isinstance(rep.get(\"brain_report\"), dict) else rep

if not br.get(\"ok\", False):
  print(\"FAIL: task failed\nsummary:\", br.get(\"summary\"))
  sys.exit(1)

# Load hv2 allowed actions from cache
cache=Path(\"artifacts/handv2_manifests_cache.json\")
allowed=set()
if cache.exists():
  data=json.loads(cache.read_text(encoding=\"utf-8\"))
  if isinstance(data,list):
    for m in data:
      if isinstance(m,dict) and isinstance(m.get(\"name\"),str):
        allowed.add(m[\"name\"])

# Validate all planned tasks
for r in (br.get(\"results\") or []):
  if not isinstance(r,dict):
    continue
  task=r.get(\"task\")
  params=(r.get(\"params\") or {})
  if task==\"ssh: run\":
    act=params.get(\"action\")
    if allowed and act not in allowed:
      print(\"FAIL: LLM produced unknown hv2 action:\", act)
      sys.exit(1)
    args=params.get(\"args\") or {}
    if isinstance(args,dict) and \"confirm\" in args:
      print(\"FAIL: confirm was placed inside params.args\")
      sys.exit(1)

print(\"OK: LLM plan used only allowed hv2 actions; confirm not in args\")
print(\"report:\", rp)
"
