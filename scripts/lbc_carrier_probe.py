#!/usr/bin/env python3
"""Read-only: open the carrier-selection pencil on a Leboncoin edit page and dump the dialog. Never submits."""
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
        btns = page.evaluate("""() => {
            const sec = [...document.querySelectorAll('section, div')].find(d => d.innerText && d.innerText.startsWith('Remise du bien'));
            if (!sec) return [];
            return [...sec.querySelectorAll('button')].map((b, i) => ({i, aria: b.getAttribute('aria-label'), text: b.innerText.slice(0, 60)}));
        }""")
        print("buttons in section:", json.dumps(btns, ensure_ascii=False))
        # carrier logos alt text
        alts = page.evaluate("""() => [...document.querySelectorAll('img')].map(i => i.alt).filter(a => /relay|chrono|colissimo|courrier|poste|shop/i.test(a))""")
        print("logos:", alts)
        pencil = page.locator("section:has-text('Remise du bien') button").filter(has_not_text="Activer").first
        cand = [b for b in btns if b.get("aria") == "Modifier les transporteurs"]
        print("candidates:", cand)
        if cand:
            ok = page.evaluate("""() => { const b = [...document.querySelectorAll('button')].find(x => x.getAttribute('aria-label') === 'Modifier les transporteurs'); if (!b) return false; b.click(); return true; }""")
            print("clicked:", ok)
            page.wait_for_timeout(2500)
            dlg = page.get_by_role("dialog")
            print("dialogs:", dlg.count())
            if dlg.count():
                print(dlg.first.inner_text()[:3000])
                ctrls = dlg.first.evaluate("""d => [...d.querySelectorAll('input, button, [role=checkbox], [role=switch]')].map(e => ({tag: e.tagName, type: e.type || e.getAttribute('role'),
                    aria: e.getAttribute('aria-label'), checked: e.checked ?? e.getAttribute('aria-checked'), disabled: e.disabled, text: (e.innerText||'').slice(0,60), name: e.name||'', value: e.value||''}))""")
                for c in ctrls:
                    print(json.dumps(c, ensure_ascii=False))
                dlg.first.screenshot(path=str(tmp_path(f"lbc_carriers_{AD}.png")))
        print("NOT SUBMITTED")
    finally:
        page.close()
