#!/usr/bin/env python3
"""Read-only: print subject/price/body/status of given ads from a fresh dashboard capture."""
import json
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP

ids = set(sys.argv[1:])
with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    hits = []
    page.on("response", lambda r: hits.append(r) if "dashboard/v1/search" in r.url and r.status == 200 else None)
    try:
        page.goto("https://www.leboncoin.fr/compte/part/mes-annonces", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        for r in hits:
            for a in (r.json().get("ads") or []):
                if str(a.get("list_id")) in ids:
                    print(json.dumps({k: a.get(k) for k in ("list_id", "subject", "price", "status")}, ensure_ascii=False))
                    print(a.get("body"))
    finally:
        page.close()
