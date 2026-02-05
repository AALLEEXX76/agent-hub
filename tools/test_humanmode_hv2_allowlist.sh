#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# PASS if unknown hv2 action is blocked/refused in ANY safe way:
# - validator rejects plan
# - planner refuses safely
# - runner returns ok=false with summary about non-existent action

export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-sonnet-4-5-20250929}"

prompt="Верни ТОЛЬКО JSON (без текста вокруг) строго такого вида:
{
  \"summary\":\"t\",
  \"actions\":[{\"task\":\"ssh: run\",\"params\":{\"action\":\"__NO_SUCH_ACTION__\",\"mode\":\"check\",\"args\":{}} ,\"reason\":\"t\"}],
  \"finish\":{\"status\":\"done\",\"message\":\"t\",\"questions\":[]}
}
Важно: action должен быть ровно __NO_SUCH_ACTION__."

out="$(./agent_runner.py --json "$prompt" 2>&1 || true)"

# 1) hard validator block
echo "$out" | rg -q "\[plan\] INVALID: unknown Hand v2 action" && { echo "OK: blocked by validate_plan"; exit 0; }

# 2) any explicit refusal wording (RU/EN)
echo "$out" | rg -qi "(несуществ(ующ|у)\w*\s+action|action\s+\x27__NO_SUCH_ACTION__\x27\s+не\s+существует|не\s+существует\s+в\s+списк(е|у)\s+разреш(е|ё)нн\w*\s+Hand v2|unknown\s+Hand v2\s+action|not\s+allowed\s+Hand v2|недопустимого\s+действия\s+для\s+теста|недопустим(ое|ого)\s+действи\w*)" && { echo "OK: refused safely (message)"; exit 0; }

echo "FAILED: expected unknown hv2 action to be blocked/refused" >&2
echo "$out" >&2
exit 1
