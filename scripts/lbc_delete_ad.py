"""Delete a Leboncoin ad from its own page ('Supprimer l’annonce'), handling the optional reason step.

Usage: lbc_delete_ad.py <ad_id> <title_substr> [--commit]
Without --commit: opens the confirm dialog, prints it, closes. Never deletes.
With --commit: confirms (Valider); if a reason step appears, picks a 'vendu' option (else 'Autre') and validates.
"""
import json
import re
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP

args = [a for a in sys.argv[1:] if a != "--commit"]
COMMIT = "--commit" in sys.argv
AD, TITLE = args[0], args[1]
REASON = args[2] if len(args) > 2 else None  # lbc | ailleurs | retrait | autre — required with --commit
if COMMIT and REASON not in ("lbc", "ailleurs", "retrait", "autre"):
    print("--commit requires reason: lbc | ailleurs | retrait | autre"); sys.exit(9)
DLG = '[role="dialog"]:not(#gimii-root), dialog[open]:not(#gimii-root)'


def dump(scope, label):
    info = scope.evaluate("""el => ({
      text: (el.innerText||'').slice(0,900),
      controls: [...el.querySelectorAll('button, [role=button], label, input[type=radio]')]
        .map(b => [(b.innerText||b.value||'').trim().slice(0,70), b.getAttribute('aria-label'), b.tagName])
        .filter(x => x[0] || x[1])
    })""")
    print(label, json.dumps(info, ensure_ascii=False)[:2000])


def kill_overlay(page):
    page.evaluate("() => document.querySelectorAll('#gimii-root').forEach(e => e.remove())")


with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(CDP)
    page = b.contexts[0].new_page()
    try:
        r = page.goto(f"https://www.leboncoin.fr/vi/{AD}.htm", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        h1 = page.locator("h1").first.inner_text() if page.locator("h1").count() else ""
        print("HTTP", r.status if r else None, "| H1:", h1)
        if TITLE.lower() not in h1.lower():
            print("TITLE MISMATCH; stopping"); sys.exit(2)
        kill_overlay(page)
        btn = page.get_by_role("button", name=re.compile("Supprimer l.annonce"))
        if not btn.count():
            print("NO DELETE BUTTON (not owner view?)"); sys.exit(3)
        btn.first.evaluate("b => b.click()")
        page.wait_for_timeout(3000)
        dlg = page.locator(DLG).last
        if not dlg.count():
            print("NO DIALOG"); sys.exit(4)
        dump(dlg, "CONFIRM")
        if TITLE.lower() not in dlg.inner_text().lower():
            print("DIALOG TITLE MISMATCH; stopping"); page.keyboard.press("Escape"); sys.exit(5)
        if not COMMIT:
            page.keyboard.press("Escape"); sys.exit(0)
        dlg.get_by_role("button", name=re.compile(r"^Valider$", re.I)).first.evaluate("b => b.click()")
        page.wait_for_timeout(4000)
        kill_overlay(page)
        d2 = page.locator(DLG).last
        if d2.count() and d2.is_visible():
            dump(d2, "STEP2")
            reasons = {"lbc": r"vendu mon bien sur leboncoin", "ailleurs": r"vendu mon bien sur une autre plateforme",
                       "retrait": r"ne souhaite plus vendre", "autre": r"^Autre$"}
            opt = d2.get_by_text(re.compile(reasons[REASON], re.I))
            if opt.count():
                opt.first.evaluate("e => e.click()")
                page.wait_for_timeout(1200)
                print("reason picked:", opt.first.inner_text()[:80])
            v = d2.get_by_role("button", name=re.compile(r"^(Valider|Confirmer|Supprimer)", re.I))
            if v.count():
                v.first.evaluate("b => b.click()")
                page.wait_for_timeout(4000)
                print("step2 validated")
            d3 = page.locator(DLG).last
            if d3.count() and d3.is_visible():
                dump(d3, "STEP3")
        print("url:", page.url)
    finally:
        page.close()
