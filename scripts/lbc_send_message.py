"""Send one exact message in a Leboncoin conversation and verify it appears.
Usage: lbc_send_message.py <conversation_id> <expected_title_substring> <message_file>
"""
import sys
from playwright.sync_api import sync_playwright
from lbc_config import CDP

CID, TITLE, MSGF = sys.argv[1:4]
MSG = open(MSGF).read().strip()
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(CDP)
    page = b.contexts[0].new_page()
    try:
        page.goto(f"https://www.leboncoin.fr/messages/id/{CID}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        body = page.inner_text("body")
        if TITLE not in body:
            print("TITLE NOT FOUND; stopping"); sys.exit(2)
        ta = page.locator("textarea").first
        ta.click(); ta.fill(MSG)
        if ta.input_value() != MSG:
            print("TEXTAREA MISMATCH; stopping"); sys.exit(3)
        btn = page.get_by_role("button", name="Envoyer mon message")
        if not btn.count() or not btn.first.is_enabled():
            print("SEND BUTTON UNAVAILABLE; stopping"); sys.exit(4)
        btn.first.click(); page.wait_for_timeout(5000)
        print("sent; textarea empty:", page.locator("textarea").first.input_value() == "")
        print("message visible:", MSG in page.inner_text("body"))
    finally:
        page.close()
