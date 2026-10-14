#!/usr/bin/env python3
"""Read-only: screenshot the edit page and public page of an ad to see why the form is missing."""
import sys
from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

ad = sys.argv[1]
with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    try:
        for name, url in [("edit", f"https://www.leboncoin.fr/annonce/{ad}/editer"),
                          ("public", f"https://www.leboncoin.fr/ad/bricolage/{ad}")]:
            r = page.goto(url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(6000)
            out = str(tmp_path(f"lbc_{name}_{ad}.png"))
            page.screenshot(path=out, full_page=False)
            imgs = page.evaluate("""() => [...document.querySelectorAll('img[alt^="produit"], img[src*="rule=ad-"]')].map(i => i.src)""")
            print(name, r.status if r else None, page.url, out)
            print("  h1:", page.locator("h1").first.inner_text() if page.locator("h1").count() else None)
            for s in dict.fromkeys(imgs):
                print("  img", s)
    finally:
        page.close()
