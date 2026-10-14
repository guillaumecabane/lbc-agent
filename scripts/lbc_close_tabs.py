#!/usr/bin/env python3
"""List CDP page targets and close all but one (keeps the first leboncoin tab, or the first page).

Usage: lbc_close_tabs.py [--commit]
"""
import json
import sys
import urllib.request
from lbc_config import CDP

commit = "--commit" in sys.argv

with urllib.request.urlopen(f"{CDP}/json/list", timeout=10) as r:
    targets = json.load(r)

pages = [t for t in targets if t.get("type") == "page"]
keep = next((t for t in pages if "leboncoin.fr" in t.get("url", "")), pages[0] if pages else None)
closed = []
for t in pages:
    if keep and t["id"] == keep["id"]:
        continue
    if commit:
        urllib.request.urlopen(f"{CDP}/json/close/{t['id']}", timeout=10).read()
    closed.append(t.get("url", "")[:90])

print(json.dumps({
    "pages_before": len(pages),
    "kept": keep.get("url", "")[:90] if keep else None,
    "closed" if commit else "would_close": len(closed),
    "sample": closed[:10],
}, ensure_ascii=False, indent=2))
