#!/usr/bin/env python3
"""Pause one Leboncoin listing from the owner dashboard and verify it.

Usage: lbc_pause_ad.py <ad_id> <expected_title> [--commit]
"""
from __future__ import annotations

import argparse
import json
import re

from playwright.sync_api import sync_playwright
from lbc_config import CDP

DASHBOARD = "https://www.leboncoin.fr/compte/part/mes-annonces"

parser = argparse.ArgumentParser()
parser.add_argument("ad_id")
parser.add_argument("expected_title")
parser.add_argument("--commit", action="store_true")
args = parser.parse_args()

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CDP)
    page = browser.contexts[0].new_page()
    try:
        page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        anchor = page.locator(f'a[href*="/ad/"][href*="{args.ad_id}"]').first
        if anchor.count() != 1:
            raise RuntimeError("listing anchor not found on dashboard")
        title = anchor.inner_text().strip()
        if title != args.expected_title:
            raise RuntimeError(f"title mismatch: {title!r}")
        card = anchor.locator("xpath=ancestor::li[1]")
        if card.count() != 1:
            raise RuntimeError("listing card not found")
        card_text = card.inner_text()
        pause = card.locator("button:visible").filter(has_text="Mettre en pause")
        reactivate = card.locator("button:visible").filter(has_text=re.compile(r"Réactiver"))
        preflight = {
            "ad_id": args.ad_id,
            "title": title,
            "pause_controls": pause.count(),
            "reactivate_controls": reactivate.count(),
            "card_text": card_text[:500],
        }
        if not args.commit:
            print(json.dumps({"dry_run": True, **preflight}, ensure_ascii=False, indent=2))
            raise SystemExit(0)
        if reactivate.count() > 0 and pause.count() == 0:
            print(json.dumps({"already_paused": True, **preflight}, ensure_ascii=False, indent=2))
            raise SystemExit(0)
        if pause.count() != 1:
            raise RuntimeError(f"expected one visible pause control, got {pause.count()}")

        writes = []
        def capture(response):
            if response.request.method != "GET":
                writes.append({"method": response.request.method, "status": response.status, "url": response.url})
        page.on("response", capture)
        pause.click()
        page.wait_for_timeout(700)
        dialogs = page.get_by_role("dialog")
        if dialogs.count():
            dialog = dialogs.last
            dialog_text = dialog.inner_text()
            if "Votre demande de mise en pause a été prise en compte" not in dialog_text:
                confirm = dialog.get_by_role("button", name=re.compile(r"^(Mettre en pause|Valider|Confirmer)$"))
                if confirm.count() != 1:
                    raise RuntimeError(f"unexpected pause dialog: {dialog_text!r}")
                confirm.click()
        page.wait_for_timeout(2500)
        page.remove_listener("response", capture)
        if writes and not any(200 <= item["status"] < 300 for item in writes):
            raise RuntimeError(f"pause write failed: {writes}")

        page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        anchor = page.locator(f'a[href*="/ad/"][href*="{args.ad_id}"]').first
        if anchor.count() != 1:
            raise RuntimeError("listing missing after pause")
        card = anchor.locator("xpath=ancestor::li[1]")
        verified = card.locator("button:visible").filter(has_text=re.compile(r"Réactiver")).count() > 0
        if not verified:
            raise RuntimeError("pause not reflected by fresh dashboard")
        print(json.dumps({
            "dry_run": False,
            "paused": True,
            "verified_reactivate_control": True,
            "ad_id": args.ad_id,
            "title": args.expected_title,
            "write_responses": [{"method": item["method"], "status": item["status"]} for item in writes],
        }, ensure_ascii=False, indent=2))
    finally:
        page.close()
