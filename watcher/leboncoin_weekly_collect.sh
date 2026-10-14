#!/usr/bin/env bash
# Read-only weekly audit collector; prints one JSON document for the reporting agent.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" "$ROOT/watcher/leboncoin_weekly_collect.py" "$@"
