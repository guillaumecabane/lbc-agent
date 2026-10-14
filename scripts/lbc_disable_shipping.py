#!/usr/bin/env python3
"""Turn OFF shipping on a Leboncoin ad (hand delivery only). Free edit, never boosts.

Usage: lbc_disable_shipping.py <ad_id> [--commit]   (run under scripts/with_browser_lock.py)
"""
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP

AD = sys.argv[1]
COMMIT = "--commit" in sys.argv
CAPTCHA = 'iframe[src*="captcha-delivery.com"], #ddChallengeContainer'
STATE = """() => { const b = [...document.querySelectorAll('button[role=checkbox], button')].find(x => /(Activer|Désactiver) la livraison/.test(x.getAttribute('aria-label') || ''));
  return b ? {label: b.getAttribute('aria-label'), checked: b.getAttribute('aria-checked') ?? b.getAttribute('data-state')} : null; }"""

with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    try:
        page.goto(f"https://www.leboncoin.fr/annonce/{AD}/editer", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        if page.locator(CAPTCHA).count():
            raise RuntimeError("CAPTCHA before mutation")
        page.evaluate("() => document.querySelector('#gimii-root')?.remove()")
        vals = lambda: (page.locator('input[name="subject"]').input_value(), page.locator('textarea[name="body"]').input_value(), page.locator('input[name="price_cents"]').input_value())
        v0 = vals()
        before = page.evaluate(STATE)
        print(AD, v0[0], "| before:", before, "| carriers editor:", page.evaluate("() => !!document.querySelector('button[aria-label=\"Modifier les transporteurs\"]')"))
        if not before:
            raise RuntimeError("shipping toggle not found")
        if before["label"] == "Activer la livraison" and before["checked"] in ("false", None):
            print("ALREADY OFF")
            sys.exit(0)
        page.evaluate("() => [...document.querySelectorAll('button')].find(x => x.getAttribute('aria-label') === 'Désactiver la livraison').click()")
        page.wait_for_timeout(2000)
        if page.get_by_role("dialog").count():
            print("dialog:", page.get_by_role("dialog").first.inner_text()[:300])
        after = page.evaluate(STATE)
        editor = page.evaluate("() => !!document.querySelector('button[aria-label=\"Modifier les transporteurs\"]')")
        print("after:", after, "| carriers editor:", editor)
        if not (after and after["label"] == "Activer la livraison" and after["checked"] in ("false", None)):
            raise AssertionError("shipping still on")
        if vals() != v0:
            raise AssertionError("title/body/price changed")
        if not COMMIT:
            print("DRY RUN OK — not submitted")
        else:
            page.get_by_role("button", name="Valider les modifications", exact=True).click()
            page.wait_for_timeout(9000)
            if page.locator(CAPTCHA).count():
                raise RuntimeError("CAPTCHA after first commit")
            free = page.get_by_role("button", name="Modifier sans booster mon annonce", exact=True)
            if free.count() != 1 or not free.is_enabled():
                raise RuntimeError("free second commit unavailable; refusing paid action")
            free.click()
            page.wait_for_timeout(9000)
            print("accepted", page.url)
    finally:
        page.close()
