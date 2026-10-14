#!/usr/bin/env python3
"""Read-only: dump the delivery/shipping section of a Leboncoin edit page (no submit)."""
import json
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

AD = sys.argv[1]
CAPTCHA = 'iframe[src*="captcha-delivery.com"], #ddChallengeContainer'
with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    try:
        page.goto(f"https://www.leboncoin.fr/annonce/{AD}/editer", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        if page.locator(CAPTCHA).count():
            raise SystemExit("CAPTCHA")
        page.evaluate("() => document.querySelector('#gimii-root')?.remove()")
        txt = page.inner_text("body")
        i = txt.find("ivraison")
        print("TEXT around livraison:\n", txt[max(0, i - 300): i + 2500])
        ctrls = page.evaluate("""() => [...document.querySelectorAll('input[type=checkbox], input[type=radio], [role=switch], [role=checkbox]')].map(e => {
            const lab = e.labels && e.labels[0] ? e.labels[0].innerText : (e.getAttribute('aria-label') || '');
            return {tag: e.tagName, type: e.type || e.getAttribute('role'), name: e.name || '', id: e.id || '', value: e.value || '',
                    checked: e.checked ?? e.getAttribute('aria-checked'), disabled: e.disabled || false, label: lab.slice(0, 120)};
        })""")
        for c in ctrls:
            print(json.dumps(c, ensure_ascii=False))
        page.screenshot(path=str(tmp_path(f"lbc_ship_{AD}.png")), full_page=True)
    finally:
        page.close()
