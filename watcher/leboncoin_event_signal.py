#!/usr/bin/env python3
"""Sticky change signal for an agent-backed Leboncoin cron monitor.

Runs the read-only delta watcher. A non-empty event replaces the persisted signal;
no-event polls repeat the last signal so the cron monitor remains stable and does
not wake the agent again merely because the watcher output returned to empty.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lbc_config import STATE_DIR  # noqa: E402

WATCHER = Path(__file__).resolve().parent / "leboncoin_event_watch.sh"
WATCH_STATE = STATE_DIR / "event-watch.json"
SIGNAL = STATE_DIR / "event-signal.txt"
BASELINE = "LBC_SIGNAL_BASELINE"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def signal_marker() -> str:
    try:
        state = json.loads(WATCH_STATE.read_text(encoding="utf-8"))
        captured_at = state.get("captured_at") or "unknown"
    except (OSError, json.JSONDecodeError):
        captured_at = "unknown"
    return f"<!-- lbc-event-signal:{captured_at} -->"


def main() -> None:
    result = subprocess.run(
        ["bash", str(WATCHER)],
        text=True,
        capture_output=True,
        timeout=330,
        check=False,
    )
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.strip())
        raise SystemExit(result.returncode)

    event = result.stdout.strip()
    if event:
        sticky = f"{event}\n\n{signal_marker()}"
        atomic_write(SIGNAL, sticky)
        print(sticky)
        return

    if SIGNAL.exists():
        print(SIGNAL.read_text(encoding="utf-8").strip())
    else:
        atomic_write(SIGNAL, BASELINE)
        print(BASELINE)


if __name__ == "__main__":
    main()
