#!/usr/bin/env python3
"""Shared, environment-driven configuration for the lbc-agent toolkit.

Every script in scripts/ imports from here (scripts/ is on sys.path when a script is run as
``python3 scripts/<name>.py``). The watcher/ and integrations/ code add scripts/ to sys.path
explicitly. Nothing here talks to the network.

Environment variables (all optional):
  LBC_CDP_URL          Chrome DevTools endpoint of the logged-in browser (default http://127.0.0.1:9222)
  LBC_HOME             Working directory holding items/, state/, tmp/ (default: repository root)
  LBC_STATE_DIR        Watcher/audit state + browser lock (default: $LBC_HOME/state)
  LBC_TMP              Screenshots, downloads, logs (default: $LBC_HOME/tmp)
  LBC_BROWSER_LOCK     Lock file serialising browser writers (default: $LBC_STATE_DIR/browser.lock)
  LBC_PROXY            HTTP proxy the browser egresses through, used only for the weekly egress check
  LBC_EXPECTED_EGRESS  Public IP the proxy must egress from; the weekly collector fails otherwise
  LBC_TZ               Time zone for weekly reports (default Europe/Paris)
  LBC_KEEP_TABS        Set to 1 to keep extra tabs open after a locked command (manual CAPTCHA handoff)
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _path(var: str, default: Path) -> Path:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else default


LBC_HOME = _path("LBC_HOME", REPO_ROOT)
CDP = (os.environ.get("LBC_CDP_URL") or "http://127.0.0.1:9222").rstrip("/")
STATE_DIR = _path("LBC_STATE_DIR", LBC_HOME / "state")
TMP = _path("LBC_TMP", LBC_HOME / "tmp")
BROWSER_LOCK = _path("LBC_BROWSER_LOCK", STATE_DIR / "browser.lock")
PROXY = os.environ.get("LBC_PROXY") or None
EXPECTED_EGRESS = os.environ.get("LBC_EXPECTED_EGRESS") or None
TZ_NAME = os.environ.get("LBC_TZ") or "Europe/Paris"


def tmp_path(name: str) -> Path:
    """Return a path inside $LBC_TMP, creating the directory (and parents of `name`) if needed."""
    path = TMP / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


if __name__ == "__main__":
    for key in ("LBC_HOME", "CDP", "STATE_DIR", "TMP", "BROWSER_LOCK", "PROXY", "EXPECTED_EGRESS", "TZ_NAME"):
        print(f"{key}={globals()[key]}")
