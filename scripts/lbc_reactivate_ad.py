#!/usr/bin/env python3
"""Reactivate one paused Leboncoin listing from the owner dashboard and verify it (free, never boost).

Usage: lbc_reactivate_ad.py <ad_id> <expected_title> [--commit]
"""
from __future__ import annotations

import argparse
import json
import re

from playwright.sync_api import sync_playwright
from lbc_config import CDP

DASHBOARD = "https://www.leboncoin.fr/compte/part/mes-annonces"
PAID = re.compile(r"(?i)\d+[,.]?\d*\s*€|payer|paiement|booster|boost")

parser = argparse.ArgumentParser()
parser.add_argument("ad_id")
parser.add_argument("expected_title")
parser.add_argument("--commit", action="store_true")
args = parser.parse_args()


def find_card(page):
    anchor = page.locator(f'a[href*="/ad/"][href*="{args.ad_id}"]').first
    if anchor.count() != 1:
        raise RuntimeError("listing anchor not found on dashboard")
    title = anchor.inner_text().strip()
    if title != args.expected_title:
        raise RuntimeError(f"title mismatch: {title!r}")
    card = anchor.locator("xpath=ancestor::li[1]")
    if card.count() != 1:
        raise RuntimeError("listing card not found")
    return title, card


with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CDP)
    page = browser.contexts[0].new_page()
    try:
        page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        title, card = find_card(page)
        pause = card.locator("button:visible").filter(has_text="Mettre en pause")
        reactivate = card.locator("button:visible").filter(has_text=re.compile(r"Réactiver"))
        pre = {"ad_id": args.ad_id, "title": title, "pause_controls": pause.count(),
               "reactivate_controls": reactivate.count(), "card_text": card.inner_text()[:400]}
        if not args.commit:
            print(json.dumps({"dry_run": True, **pre}, ensure_ascii=False, indent=2))
            raise SystemExit(0)
        if pause.count() > 0 and reactivate.count() == 0:
            print(json.dumps({"already_active": True, **pre}, ensure_ascii=False, indent=2))
            raise SystemExit(0)
        if reactivate.count() != 1:
            raise RuntimeError(f"expected one visible reactivate control, got {reactivate.count()}")

        writes = []

        def capture(response):
            if response.request.method != "GET":
                writes.append({"method": response.request.method, "status": response.status})

        page.on("response", capture)
        reactivate.click()
        page.wait_for_timeout(1000)
        dialogs = page.get_by_role("dialog")
        if dialogs.count():
            dialog = dialogs.last
            text = dialog.inner_text()
            confirm = dialog.get_by_role("button", name=re.compile(r"^(Réactiver.*|Valider|Confirmer)$"))
            if confirm.count() == 1:
                if PAID.search(confirm.inner_text()):
                    raise RuntimeError(f"reactivation looks paid, abort: {text!r}")
                confirm.click()
            elif "prise en compte" not in text and "réactivée" not in text.lower():
                raise RuntimeError(f"unexpected reactivate dialog: {text!r}")
        page.wait_for_timeout(2500)
        page.remove_listener("response", capture)
        if writes and not any(200 <= w["status"] < 300 for w in writes):
            raise RuntimeError(f"reactivate write failed: {writes}")

        page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        _, card = find_card(page)
        ok = card.locator("button:visible").filter(has_text="Mettre en pause").count() > 0
        if not ok:
            raise RuntimeError("reactivation not reflected by fresh dashboard")
        print(json.dumps({"reactivated": True, "verified_pause_control": True, "ad_id": args.ad_id,
                          "write_responses": writes}, ensure_ascii=False, indent=2))
    finally:
        page.close()
