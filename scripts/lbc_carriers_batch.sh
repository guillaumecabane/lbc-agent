#!/usr/bin/env bash
# Batch carrier fix: run lbc_set_carriers.py --commit on every ad id listed in a file
# (one id per line; blank lines and "#" comments ignored). Default policy in lbc_set_carriers.py:
# Shop2Shop by Chronopost + Colissimo ON, Mondial Relay OFF.
# One lock acquisition per ad so the watcher can interleave; 90 s pause after an accepted edit,
# 20 s otherwise; stops on the first CAPTCHA.
#
# Usage: scripts/lbc_carriers_batch.sh ad_ids.txt [extra lbc_set_carriers.py args, e.g. --allow-no-colissimo]
set -u
IDS_FILE="${1:?usage: $0 ad_ids.txt [extra args]}"
shift
[ -r "$IDS_FILE" ] || { echo "cannot read $IDS_FILE" >&2; exit 1; }
IDS_FILE="$(cd "$(dirname "$IDS_FILE")" && pwd)/$(basename "$IDS_FILE")"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
PYTHON="${PYTHON:-python3}"
TMPDIR_LBC="${LBC_TMP:-${LBC_HOME:-$ROOT}/tmp}"
mkdir -p "$TMPDIR_LBC"
LOG="$TMPDIR_LBC/lbc_carriers_batch.log"
: > "$LOG"
grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$IDS_FILE" | while read -r id _; do
  out=$("$PYTHON" scripts/with_browser_lock.py --timeout 600 "$PYTHON" scripts/lbc_set_carriers.py "$id" --commit "$@" 2>&1 | grep -v -e DEP0169 -e trace-deprecation)
  echo "=== $id" >> "$LOG"
  echo "$out" | grep -E "before|after|ALREADY|SKIP|accepted|Error|CAPTCHA|locked|mapping" >> "$LOG"
  if echo "$out" | grep -q CAPTCHA; then echo "STOP: CAPTCHA at $id" >> "$LOG"; exit 2; fi
  if echo "$out" | grep -q accepted; then sleep 90; else sleep 20; fi
done
rc=$?
[ "$rc" -eq 0 ] && echo "DONE" >> "$LOG"
echo "log: $LOG"
exit "$rc"
