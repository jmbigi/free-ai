#!/usr/bin/env bash
# Synchronize the NCM LM1B server source into the external NCM runtime.
#
# The active systemd unit runs from /home/kubuntu/ncm, so the repo copy and the
# runtime copy can drift. This script makes the relationship explicit:
#
#   ./deploy/sync-ncm-lm1b.sh check     # no writes; exit 1 if drift
#   ./deploy/sync-ncm-lm1b.sh apply     # backup + copy; does NOT restart
#   ./deploy/sync-ncm-lm1b.sh restart   # apply + restart + health check
#
# NCM_HOME and NCM_BASE_URL are configurable. No secrets are read or printed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NCM_HOME="${NCM_HOME:-/home/kubuntu/ncm}"
NCM_BASE="${NCM_BASE_URL:-http://127.0.0.1:11436}"
SERVICE="ncm-lm1b.service"
FILES=(ncm_lm1b_server.py response_builder.py)
MODE="${1:-check}"

usage() {
  cat <<EOF
Usage: $0 [check|apply|restart]

  check    Compare repo source with $NCM_HOME; exit 1 on drift.
  apply    Backup runtime files and copy the repo versions; no restart.
  restart  apply + systemctl --user restart $SERVICE + health probe.

NCM_HOME=${NCM_HOME}
NCM_BASE_URL=${NCM_BASE}
EOF
}

case "$MODE" in
  check|apply|restart) ;;
  -h|--help|help) usage; exit 0 ;;
  *) echo "Unknown mode: $MODE" >&2; usage >&2; exit 2 ;;
esac

if [[ ! -d "$NCM_HOME" ]]; then
  echo "NCM_HOME does not exist: $NCM_HOME" >&2
  exit 1
fi

do_check() {
  local drift=0 file src dst
  for file in "${FILES[@]}"; do
    src="$ROOT/local/ncm/$file"
    dst="$NCM_HOME/$file"
    if [[ ! -f "$src" ]]; then
      echo "MISSING repo source: $src" >&2
      drift=1
    elif [[ ! -f "$dst" ]]; then
      echo "MISSING runtime: $dst" >&2
      drift=1
    elif cmp -s "$src" "$dst"; then
      echo "IN SYNC $file"
    else
      echo "DRIFT   $file"
      drift=1
    fi
  done
  return "$drift"
}

do_apply() {
  local file src dst stamp
  stamp="$(date +%Y%m%d-%H%M%S)"
  for file in "${FILES[@]}"; do
    src="$ROOT/local/ncm/$file"
    dst="$NCM_HOME/$file"
    if [[ ! -f "$src" ]]; then
      echo "MISSING repo source: $src" >&2
      exit 1
    fi
    if [[ -f "$dst" ]]; then
      cp -a "$dst" "$dst.bak-$stamp"
      echo "BACKUP  $dst.bak-$stamp"
    fi
    install -m 0644 "$src" "$dst"
    echo "APPLIED $file"
  done
}

wait_health() {
  local attempt
  for attempt in $(seq 1 45); do
    if curl -fsS "$NCM_BASE/health" >/dev/null 2>&1; then
      echo "HEALTH  $NCM_BASE/health OK after ${attempt}s"
      return 0
    fi
    sleep 1
  done
  echo "ERROR: NCM health not ready after 45s" >&2
  systemctl --user status "$SERVICE" --no-pager -l 2>&1 | sed -n '1,25p' >&2 || true
  return 1
}

case "$MODE" in
  check)
    do_check
    ;;
  apply)
    do_apply
    echo "Applied without restart. Run '$0 restart' to load it."
    ;;
  restart)
    do_apply
    systemctl --user restart "$SERVICE"
    wait_health
    systemctl --user is-active "$SERVICE"
    ;;
esac
