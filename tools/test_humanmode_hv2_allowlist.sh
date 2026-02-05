#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Deterministic human-mode hardening test:
# Feed PLAN_JSON directly (bypass LLM), then assert the refusal/block appears in the saved report JSON.

python3 -c 'import json,subprocess,sys,re
p="PLAN_JSON:{\"summary\":\"t\",\"actions\":[{\"task\":\"ssh: run\",\"params\":{\"action\":\"__NO_SUCH_ACTION__\",\"mode\":\"check\",\"args\":{}},\"reason\":\"t\"}],\"finish\":{\"status\":\"done\",\"message\":\"t\",\"questions\":[]}}"
out=subprocess.run(["./agent_runner.py","--json",p],capture_output=True,text=True)
j=json.loads(out.stdout.strip() or "{}")
rp=j.get("report")
assert rp, f"no report in stdout: {out.stdout!r}"
d=json.load(open(rp,"r",encoding="utf-8"))
txt=json.dumps(d,ensure_ascii=False)
ok=bool(re.search(r"(\[plan\] INVALID: unknown Hand v2 action|unsupported ssh: run action: __NO_SUCH_ACTION__|__NO_SUCH_ACTION__)", txt))
print("report:", rp)
print("OK" if ok else "FAIL")
sys.exit(0 if ok else 1)
'
