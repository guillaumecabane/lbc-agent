"""Send a message (and optionally a formal 'Faire une offre' price) in a Leboncoin conversation.

Usage: lbc_send.py <conv_id> <expected_ad_title_substr> <message_file|-> [--offer EUR] [--commit]
Without --commit: fills nothing irreversible, prints plan only.
"""
import json
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

args = [a for a in sys.argv[1:]]
COMMIT = "--commit" in args
args = [a for a in args if a != "--commit"]
OFFER = None
if "--offer" in args:
    i = args.index("--offer")
    OFFER = int(args[i + 1])
    del args[i:i + 2]
CID, TITLE, MSGF = args[0], args[1], args[2]
MSG = None if MSGF == "-" else open(MSGF).read().strip()

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(CDP)
    page = b.contexts[0].new_page()
    try:
        page.goto(f"https://www.leboncoin.fr/messages/id/{CID}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        body = page.inner_text("main") if page.locator("main").count() else page.inner_text("body")
        if TITLE not in body:
            print("AD TITLE NOT FOUND in conversation; stopping"); sys.exit(2)
        print("plan:", {"conv": CID, "msg": MSG, "offer": OFFER, "commit": COMMIT})
        if not COMMIT:
            sys.exit(0)
        if MSG:
            ta = page.locator("textarea").first
            ta.click()
            ta.fill(MSG)
            page.wait_for_timeout(500)
            if ta.input_value() != MSG:
                print("TEXTAREA MISMATCH; stopping"); sys.exit(3)
            page.get_by_role("button", name="Envoyer mon message").click()
            page.wait_for_timeout(4000)
            print("message sent; textarea now:", repr(page.locator("textarea").first.input_value()))
        if OFFER is not None:
            page.get_by_role("button", name="Faire une offre").first.click()
            page.wait_for_timeout(2500)
            dlg = page.locator('[role="dialog"]').last
            dlg.get_by_role("button", name="Autre prix").click()
            page.wait_for_timeout(800)
            inp = dlg.locator("input#price")
            inp.click()
            inp.fill(str(OFFER))
            page.wait_for_timeout(800)
            v = inp.input_value()
            if "".join(c for c in v if c.isdigit()) != str(OFFER):
                print("OFFER INPUT MISMATCH", repr(v)); page.keyboard.press("Escape"); sys.exit(4)
            btn = dlg.get_by_role("button", name="Proposer")
            if not btn.is_enabled():
                print("PROPOSER DISABLED"); page.keyboard.press("Escape"); sys.exit(5)
            btn.click()
            page.wait_for_timeout(5000)
            print("offer submitted; dialog open:", page.locator('[role="dialog"]').count())
        page.wait_for_timeout(2000)
        txt = page.inner_text("body")
        i = txt.find("Aujourd")
        print("AFTER:", txt[i:i + 900].replace("\n", " | "))
        page.screenshot(path=str(tmp_path(f"lbc_sent_{CID[:8]}.png")))
    finally:
        page.close()
