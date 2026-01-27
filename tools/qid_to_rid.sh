#!/usr/bin/env bash
set -euo pipefail

qid="${1:-}"
if [[ -z "$qid" ]]; then
  echo "usage: $0 q_<...>" >&2
  exit 2
fi

ssh ii-bot-nout "set -euo pipefail; qid='${qid}'; if [[ \$qid == q_* ]]; then f=/tmp/iibot_\$qid.log; else f=/tmp/iibot_q_\$qid.log; fi; # wait up to ~120s (480 * 0.25)
for i in \$(seq 1 480); do [ -s \"\$f\" ] && break; sleep 0.25; done; [ -s \"\$f\" ] || { echo \"ERROR: log not ready: \$f\" >&2; exit 1; }; head -n 1 \"\$f\" | python3 -c \"import sys,json; print(json.loads(sys.stdin.read()).get('request_id',''))\""
