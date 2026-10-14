#!/usr/bin/env python3
"""Decline a pending buyer offer, then send a formal counter-offer. Usage: lbc_counter.py <conv_id> <title_substr> <eur> [--commit]"""
import sys
from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

CID, TITLE, EUR = sys.argv[1], sys.argv[2], int(sys.argv[3])
COMMIT = "--commit" in sys.argv


def buttons(page):
    return sorted(set(page.evaluate("""() => [...document.querySelectorAll('button')]
        .map(b => (b.innerText || b.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ')).filter(t => t && t.length < 60)""")))


with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(CDP)
    page = b.contexts[0].new_page()
    page.set_viewport_size({"width": 1400, "height": 1600})
    try:
        page.goto(f"https://www.leboncoin.fr/messages/id/{CID}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        page.evaluate("() => document.querySelectorAll('#gimii-root').forEach(e => e.remove())")
        if TITLE not in page.inner_text("body"):
            print("TITLE NOT FOUND"); sys.exit(2)
        print("before:", buttons(page))
        if not COMMIT:
            sys.exit(0)
        refuse = page.get_by_role("button", name="Refuser l'offre")
        if refuse.count():
            refuse.first.click()
            page.wait_for_timeout(2500)
            dlg = page.locator('[role="dialog"]')
            if dlg.count():
                print("refuse dialog:", dlg.last.inner_text()[:300].replace("\n", " | "))
                for name in ("Refuser l'offre", "Refuser", "Confirmer", "Valider"):
                    c = dlg.last.get_by_role("button", name=name, exact=True)
                    if c.count():
                        c.first.click(); print("confirmed via", name); break
                page.wait_for_timeout(4000)
        print("after refuse:", buttons(page))
        offer = page.get_by_role("button", name="Faire une offre")
        if not offer.count():
            page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(7000)
            page.evaluate("() => document.querySelectorAll('#gimii-root').forEach(e => e.remove())")
            offer = page.get_by_role("button", name="Faire une offre")
        if not offer.count():
            print("NO 'Faire une offre' AFTER REFUSAL:", buttons(page)); sys.exit(6)
        offer.first.click(); page.wait_for_timeout(2500)
        dlg = page.locator('[role="dialog"]').last
        dlg.get_by_role("button", name="Autre prix").click(); page.wait_for_timeout(800)
        inp = dlg.locator("input#price"); inp.click(); inp.fill(str(EUR)); page.wait_for_timeout(800)
        if "".join(c for c in inp.input_value() if c.isdigit()) != str(EUR):
            print("OFFER INPUT MISMATCH"); page.keyboard.press("Escape"); sys.exit(4)
        btn = dlg.get_by_role("button", name="Proposer")
        if not btn.is_enabled():
            print("PROPOSER DISABLED"); page.keyboard.press("Escape"); sys.exit(5)
        btn.click(); page.wait_for_timeout(5000)
        txt = page.inner_text("body")
        i = txt.rfind("Offre")
        print("AFTER:", txt[max(0, i - 300):i + 400].replace("\n", " | "))
        page.screenshot(path=str(tmp_path(f"lbc_counter_{CID[:8]}.png")))
    finally:
        page.close()
