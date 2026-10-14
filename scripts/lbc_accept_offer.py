#!/usr/bin/env python3
"""Accept one pending incoming Leboncoin offer and verify it.

Usage: lbc_accept_offer.py <conversation_id> <expected_title> <amount_eur> [--commit]
"""
from __future__ import annotations

import argparse
import json
import re

from playwright.sync_api import sync_playwright
from lbc_config import CDP

MESSAGES = "https://www.leboncoin.fr/messages"

parser = argparse.ArgumentParser()
parser.add_argument("conversation_id")
parser.add_argument("expected_title")
parser.add_argument("amount_eur", type=int)
parser.add_argument("--commit", action="store_true")
args = parser.parse_args()

accept_pattern = re.compile(rf"^Accepter\s+{args.amount_eur}\s*€$")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CDP)
    page = browser.contexts[0].new_page()
    try:
        page.goto(MESSAGES, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        url = f"{MESSAGES}/id/{args.conversation_id}"
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4500)
        body = page.inner_text("body")
        if args.expected_title not in body:
            raise RuntimeError("conversation title mismatch")
        expected_offer = f"Voici l'offre de"
        if expected_offer not in body or f"{args.amount_eur} €" not in body.replace(" ", " "):
            # The exact offer may use either a normal or non-breaking space.
            normalized = " ".join(body.split())
            if expected_offer not in normalized or f"{args.amount_eur} €" not in normalized:
                raise RuntimeError("pending offer amount not found")
        accept = page.get_by_role("button", name=accept_pattern)
        preflight = {
            "conversation_id": args.conversation_id,
            "title": args.expected_title,
            "amount_eur": args.amount_eur,
            "accept_controls": accept.count(),
        }
        if not args.commit:
            print(json.dumps({"dry_run": True, **preflight}, ensure_ascii=False, indent=2))
            raise SystemExit(0)
        if accept.count() != 1:
            raise RuntimeError(f"expected one accept control, got {accept.count()}")

        writes = []
        def capture(response):
            if response.request.method != "GET":
                writes.append({"method": response.request.method, "status": response.status, "url": response.url})
        page.on("response", capture)
        accept.click()
        page.wait_for_timeout(800)
        dialogs = page.get_by_role("dialog")
        if dialogs.count():
            dialog = dialogs.last
            text = dialog.inner_text()
            if "Votre réponse a bien été envoyée" not in text:
                confirm = dialog.get_by_role("button", name=re.compile(r"^(Accepter|Accepter l'offre|Valider|Confirmer)$"))
                if confirm.count() != 1:
                    raise RuntimeError(f"unexpected acceptance dialog: {text!r}")
                confirm.click()
        page.wait_for_timeout(2500)
        page.remove_listener("response", capture)
        if not writes or not any(200 <= row["status"] < 300 for row in writes):
            raise RuntimeError(f"no successful acceptance response: {writes}")

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4500)
        still_pending = page.get_by_role("button", name=accept_pattern).count()
        if still_pending:
            raise RuntimeError("acceptance button still present after fresh reload")
        print(json.dumps({
            "dry_run": False,
            "accepted": True,
            "verified_pending_button_absent": True,
            "conversation_id": args.conversation_id,
            "title": args.expected_title,
            "amount_eur": args.amount_eur,
            "write_responses": [{"method": row["method"], "status": row["status"]} for row in writes],
        }, ensure_ascii=False, indent=2))
    finally:
        page.close()
