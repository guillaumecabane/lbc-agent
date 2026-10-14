#!/usr/bin/env bash
# Run the read-only event watcher under the shared browser lock.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" "$ROOT/scripts/with_browser_lock.py" --timeout 240 "$PYTHON" "$ROOT/watcher/leboncoin_event_watch.py" "$@"
