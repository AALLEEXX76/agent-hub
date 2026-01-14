#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-ii-bot-nout}"

OUTDIR="${HOME}/agent-hub/snapshots"
mkdir -p "$OUTDIR"

TS="$(date -u +%Y%m%d-%H%M%S)"
NAME="iibot_server_snapshot_${TS}.tgz"
OUT="${OUTDIR}/${NAME}"

# Собираем ключевые файлы Hand v2 + конфиги (без секрета из env)
# --ignore-failed-read чтобы не падать, если какого-то файла нет
ssh "$HOST" 'tar -czf - --ignore-failed-read \
  /usr/local/lib/iibot \
  /usr/local/sbin/iibotv2 \
  /etc/caddy/Caddyfile \
  /opt/n8n/docker-compose.yml \
  /etc/zabbix/zabbix_agentd.conf \
  /etc/ufw/user.rules \
  /etc/ufw/user6.rules 2>/dev/null' > "$OUT"

SHA="$(sha256sum "$OUT" | awk "{print \$1}")"
echo "${SHA}  ${NAME}" > "${OUT}.sha256"
printf "%s\t%s\t%s\n" "$TS" "$NAME" "$SHA" >> "${OUTDIR}/INDEX.txt"

echo "OK: snapshot saved:"
echo " - $OUT"
echo " - ${OUT}.sha256"
echo " - ${OUTDIR}/INDEX.txt (appended)"
