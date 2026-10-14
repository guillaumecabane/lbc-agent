#!/usr/bin/env python3
"""Read-only: open the LBC dashboard in a fresh tab and report whether a DataDome challenge is shown."""
import json
from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

SEL = 'iframe[src*="captcha-delivery.com"],iframe[src*="geo.captcha"],#ddChallengeContainer,[class*="ddCaptcha"]'
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CDP)
    page = browser.contexts[0].new_page()
    try:
        resp = page.goto("https://www.leboncoin.fr/compte/part/mes-annonces", wait_until="domcontentloaded", timeout=60000)
        seen = []
        for t in (0, 3000, 7000):
            page.wait_for_timeout(t)
            seen.append(page.evaluate("(sel) => document.querySelectorAll(sel).length", SEL))
        page.screenshot(path=str(tmp_path("lbc_captcha_state.png")))
        print(json.dumps({"http": resp.status if resp else None,
                          "h1": page.evaluate("document.querySelector('h1')?.innerText||null"),
                          "captcha_matches_over_time": seen}, ensure_ascii=False))
    finally:
        page.close()
