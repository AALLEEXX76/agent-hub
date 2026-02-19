#!/usr/bin/env bash
set -euo pipefail

SERVER_ALIAS="${SERVER_ALIAS:-ii-bot-nout}"
SUDOERS="/etc/sudoers.d/90-agent-turbo-root"

usage() {
  echo "Usage:"
  echo "  SERVER_ALIAS=ii-bot-nout   $0 enable"
  echo "  SERVER_ALIAS=ii-bot-nout   $0 rollback"
  echo
  echo "Notes:"
  echo "  - requires ssh -o BatchMode=yes access to SERVER_ALIAS"
  echo "  - your ssh user on server must have sudo -n"
  echo "  - this grants agent NOPASSWD: ALL (test stend only)"
  echo "  - rollback removes ${SUDOERS} (optionally remove agent from docker group manually)"
}

cmd="${1:-}"
if [ -z "$cmd" ] || [ "$cmd" = "--help" ] || [ "$cmd" = "-h" ]; then
  usage
  exit 0
fi

if [ "$cmd" = "enable" ]; then
  echo "== enable root/docker-level for agent on server =="
  ssh -o BatchMode=yes "$SERVER_ALIAS" "bash -lc 'set -euo pipefail; sudo -n true; getent group docker >/dev/null 2>&1 || sudo -n groupadd docker 2>/dev/null || true; id agent >/dev/null 2>&1 || sudo -n useradd -m -s /bin/bash agent; sudo -n usermod -aG docker,sudo agent || true; echo \"agent ALL=(ALL) NOPASSWD:ALL\" | sudo -n tee $SUDOERS >/dev/null; sudo -n chmod 0440 $SUDOERS; sudo -n visudo -cf $SUDOERS >/dev/null; sudo -n -u agent -H bash -lc \'set -e; sudo -n id; sudo -n docker ps | head -n 3 || true; echo OK_AGENT_ROOT_DOCKER\''"
  echo "OK_ENABLE"
  exit 0
fi

if [ "$cmd" = "rollback" ]; then
  echo "== rollback root/docker-level for agent on server =="
  ssh -o BatchMode=yes "$SERVER_ALIAS" "bash -lc 'set -euo pipefail; sudo -n true; sudo -n rm -f $SUDOERS; echo OK_ROLLBACK'"
  echo "NOTE: rotate TURBO_TOKEN locally in .agent_env after rollback."
  exit 0
fi

echo "ERROR: unknown command: $cmd"
usage
exit 2
