#!/usr/bin/env bash
# serve_dashboard.sh - preview the static dashboard on this machine only.
#
#   bash scripts/serve_dashboard.sh            # http://127.0.0.1:8765/ (or the next free port up to 8799)
#   PORT=9000 bash scripts/serve_dashboard.sh  # exactly this port; fails if it is taken
#
# Binds to 127.0.0.1 (never 0.0.0.0): nothing is exposed on the network. From a laptop,
# VS Code Remote SSH forwards the port automatically (Ports panel), or use
#   ssh -L 8765:127.0.0.1:8765 <server>
# The page also opens directly from disk (dashboard/index.html) because the data bundle is
# a plain <script>. The data is checked first; a stale bundle is reported, not served silently.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON="${PYTHON:-python3}"
HOST=127.0.0.1

# On a shared server another user may already hold 8765. Without an explicit PORT, take the
# first free port in 8765-8799; with PORT set, use exactly that port or stop with a message.
port_free() { "$PYTHON" -c 'import socket,sys; s=socket.socket(); s.bind((sys.argv[1], int(sys.argv[2])))' "$HOST" "$1" 2>/dev/null; }
if [[ -n "${PORT:-}" ]]; then
  if ! port_free "$PORT"; then
    echo "!! ${HOST}:${PORT} is already in use (by another process or user); choose another PORT" >&2
    exit 1
  fi
else
  for candidate in $(seq 8765 8799); do
    if port_free "$candidate"; then PORT=$candidate; break; fi
  done
  if [[ -z "${PORT:-}" ]]; then
    echo "!! no free port in 8765-8799 on ${HOST}; set PORT explicitly" >&2
    exit 1
  fi
  [[ "$PORT" == 8765 ]] || echo "== 127.0.0.1:8765 is in use (another process or user); using ${PORT} instead"
fi

if ! "$PYTHON" -m src.dashboard.build_data --check; then
  echo "!! dashboard data is not current: run '$PYTHON -m src.dashboard.build_data' (exit codes: 1 BLOCKED, 2 BROKEN, 3 STALE)" >&2
  exit 1
fi
echo "== serving dashboard/ at http://${HOST}:${PORT}/  (simulation page: /simulation.html; Ctrl-C to stop)"
exec "$PYTHON" -m http.server "$PORT" --bind "$HOST" --directory dashboard
