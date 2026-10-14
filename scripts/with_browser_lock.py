#!/usr/bin/env python3
"""Run one command while holding the shared Leboncoin browser-write lease."""
from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
from lbc_config import BROWSER_LOCK as LOCK, CDP



def close_extra_tabs() -> None:
    """Close every page target except one Leboncoin tab, even if the command crashed.

    Scripts open a fresh tab per run; a crash before page.close() used to leak it and
    Chrome RAM grew unbounded. Set LBC_KEEP_TABS=1 to skip (manual CAPTCHA handoff).
    """
    if os.environ.get("LBC_KEEP_TABS") == "1":
        return
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"{CDP}/json/list", timeout=5) as resp:
            pages = [t for t in json.load(resp) if t.get("type") == "page"]
        keep = next((t for t in pages if "leboncoin.fr" in t.get("url", "")), pages[0] if pages else None)
        for t in pages:
            if keep is None or t["id"] != keep["id"]:
                urllib.request.urlopen(f"{CDP}/json/close/{t['id']}", timeout=5).read()
    except Exception as exc:  # never mask the command's own exit code
        print(f"tab cleanup skipped: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as handle:
        import time
        deadline = time.monotonic() + args.timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    print(f"browser lock timeout after {args.timeout:g}s", file=sys.stderr)
                    return 75
                time.sleep(0.5)
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()} command={command!r}\n")
        handle.flush()
        try:
            return subprocess.run(command, check=False).returncode
        finally:
            close_extra_tabs()
            handle.seek(0)
            handle.truncate()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main())
