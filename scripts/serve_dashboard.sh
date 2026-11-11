#!/usr/bin/env bash
# serve_dashboard.sh - preview the static dashboard on this machine only.
#
#   bash scripts/serve_dashboard.sh            # http://127.0.0.1:8765/
#   PORT=9000 bash scripts/serve_dashboard.sh
#
# Binds to 127.0.0.1 (never 0.0.0.0): nothing is exposed on the network. From a laptop,
# VS Code Remote SSH forwards the port automatically (Ports panel), or use
#   ssh -L 8765:127.0.0.1:8765 <server>
# The page also opens directly from disk (dashboard/index.html) because the data bundle is
# a plain <script>. The data is checked first; a stale bundle is reported, not served silently.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8765}"
HOST=127.0.0.1

if ! "$PYTHON" -m src.dashboard.build_data --check; then
  echo "!! dashboard data is not current: run '$PYTHON -m src.dashboard.build_data' (exit codes: 1 BLOCKED, 2 BROKEN, 3 STALE)" >&2
  exit 1
fi
echo "== serving dashboard/ at http://${HOST}:${PORT}/  (simulation page: /simulation.html; Ctrl-C to stop)"
exec "$PYTHON" -m http.server "$PORT" --bind "$HOST" --directory dashboard
