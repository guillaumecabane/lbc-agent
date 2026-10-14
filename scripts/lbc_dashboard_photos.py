#!/usr/bin/env python3
"""Read-only: capture the dashboard API response and print images for given ad ids."""
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

ids = set(sys.argv[1:])
OUT = tmp_path("lbc_photos")
got = []

with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    try:
        def on_resp(r):
            if "/api/dashboard/v1/search" in r.url:
                try:
                    got.append(r.json())
                except Exception:
                    pass
        page.on("response", on_resp)
        page.goto("https://www.leboncoin.fr/compte/part/mes-annonces", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)
        if page.locator('iframe[src*="captcha-delivery.com"], #ddChallengeContainer').count():
            raise RuntimeError("CAPTCHA")
    finally:
        page.close()

ads = {}
for g in got:
    for a in g.get("ads", []):
        ads[str(a.get("list_id"))] = a
print("dashboard ads captured:", len(ads))
for lid in ids:
    a = ads.get(lid)
    if not a:
        print("########", lid, "NOT IN FIRST PAGE")
        continue
    urls = (a.get("images") or {}).get("urls_large") or (a.get("images") or {}).get("urls") or []
    print("########", lid, a.get("subject"), a.get("status"), len(urls), "photos")
    d = OUT / f"dash_{lid}"
    d.mkdir(parents=True, exist_ok=True)
    for i, u in enumerate(urls, 1):
        print("  ", i, u)
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        (d / f"{i:02d}.jpg").write_bytes(urllib.request.urlopen(req, timeout=20).read())
