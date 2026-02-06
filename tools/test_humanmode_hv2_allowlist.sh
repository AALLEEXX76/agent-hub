#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)/.."

python3 -c "import json,subprocess,sys,re
# warm up: create/load Hand v2 manifests cache (shortcut path)
subprocess.run([\"./agent_runner.py\",\"--json\",\"ssh: run action=list_actions mode=check args={}\"],capture_output=True,text=True)

cases=[
  (\"unknown_action\", \"PLAN_JSON:{\\\"summary\\\":\\\"t\\\",\\\"actions\\\":[{\\\"task\\\":\\\"ssh: run\\\",\\\"params\\\":{\\\"action\\\":\\\"__NO_SUCH_ACTION__\\\",\\\"mode\\\":\\\"check\\\",\\\"args\\\":{}},\\\"reason\\\":\\\"t\\\"}],\\\"finish\\\":{\\\"status\\\":\\\"done\\\",\\\"message\\\":\\\"t\\\",\\\"questions\\\":[]}}\", r\"(\\[plan\\] INVALID: unknown Hand v2 action|unknown Hand v2 action for ssh: run: __NO_SUCH_ACTION__|__NO_SUCH_ACTION__)\"),
  (\"confirm_in_args\", \"PLAN_JSON:{\\\"summary\\\":\\\"t\\\",\\\"actions\\\":[{\\\"task\\\":\\\"ssh: run\\\",\\\"params\\\":{\\\"action\\\":\\\"docker_status\\\",\\\"mode\\\":\\\"apply\\\",\\\"args\\\":{\\\"confirm\\\":\\\"BAD\\\"}},\\\"reason\\\":\\\"t\\\"}],\\\"finish\\\":{\\\"status\\\":\\\"done\\\",\\\"message\\\":\\\"t\\\",\\\"questions\\\":[]}}\", r\"(confirm must be params\\.confirm)\"),
]

all_ok=True
for name,payload,pat in cases:
  out=subprocess.run([\"./agent_runner.py\",\"--json\",payload],capture_output=True,text=True)
  j=json.loads((out.stdout or \"\").strip() or \"{}\")
  rp=j.get(\"report\")
  if not rp:
    print(name, \"FAIL (no report)\"); all_ok=False; continue
  d=json.load(open(rp,\"r\",encoding=\"utf-8\"))
  txt=json.dumps(d,ensure_ascii=False)
  ok=bool(re.search(pat, txt))
  print(name, \"report:\", rp)
  print(name, \"OK\" if ok else \"FAIL\")
  all_ok = all_ok and ok
sys.exit(0 if all_ok else 1)
"
