#!/usr/bin/env python3
"""Apply a batch of operator-approved free edits (e.g. from the weekly review). Never boosts.

Each edit is described in a JSON spec file (a list of objects):

  [
    {
      "ad_id": "1234567890",
      "expect": {"title": "Old title", "body": "Old body", "price": "17",
                 "combobox_values": ["De 7 à 12 ans"]},
      "set": {"title": "New title", "body": "New body"},
      "clear_brand": "WrongBrand"
    }
  ]

- "expect": optional guards; every given value must match the live edit page before anything is
  touched (title/body/price are compared exactly, combobox_values must each be present).
- "set": optional new title/body, typed with keyboard events (React-safe) and re-asserted.
- "clear_brand": optional value of a wrongly auto-filled brand combobox to clear via its
  « Effacer » button (useful when the real brand is not offered in Leboncoin's list).
- Price is never changed here (use lbc_edit_listing.py --price) and is asserted unchanged.

Usage: lbc_weekly_apply_edits.py edits.json [--commit]
Without --commit every edit is rehearsed on the edit page and the page is closed WITHOUT submitting.
Run under scripts/with_browser_lock.py.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
from lbc_config import CDP


def type_exact(field, text):
    field.click(); field.press("Control+A"); field.press_sequentially(text, delay=1); field.press("Tab")
    if field.input_value() != text: raise AssertionError("React field mismatch")


def commit_free(page):
    btn = page.get_by_role("button", name="Valider les modifications", exact=True)
    if btn.count() != 1 or not btn.is_enabled(): raise RuntimeError("First free-edit commit unavailable")
    btn.click(); page.wait_for_timeout(9000)
    if "captcha" in page.inner_text("body").lower(): raise RuntimeError("CAPTCHA after first commit")
    free = page.get_by_role("button", name="Modifier sans booster mon annonce", exact=True)
    if free.count() != 1 or not free.is_enabled(): raise RuntimeError("Free second commit unavailable; refusing paid action")
    free.click(); page.wait_for_timeout(10000)
    print("accepted", page.url)


def open_edit(ctx, ad):
    page = ctx.new_page(); r = page.goto(f"https://www.leboncoin.fr/annonce/{ad}/editer", wait_until="domcontentloaded", timeout=90000); page.wait_for_timeout(5000)
    if not r or r.status != 200: raise RuntimeError(f"edit {ad} HTTP {r.status if r else None}")
    if "captcha" in page.inner_text("body").lower(): raise RuntimeError("CAPTCHA before mutation")
    return page


def combobox_values(pg):
    boxes = pg.locator('input[role="combobox"]')
    return [boxes.nth(i).input_value() for i in range(boxes.count())]


def apply(ctx, edit, commit):
    ad = str(edit["ad_id"])
    expect = edit.get("expect") or {}
    new = edit.get("set") or {}
    pg = open_edit(ctx, ad)
    try:
        title = pg.locator('input[name="subject"]'); body = pg.locator('textarea[name="body"]'); price = pg.locator('input[name="price_cents"]')
        if "title" in expect: assert title.input_value() == expect["title"], f"{ad}: title mismatch {title.input_value()!r}"
        if "body" in expect: assert body.input_value() == expect["body"], f"{ad}: body mismatch"
        if "price" in expect: assert price.input_value() == str(expect["price"]), f"{ad}: price mismatch {price.input_value()!r}"
        for value in expect.get("combobox_values") or []:
            assert value in combobox_values(pg), f"{ad}: combobox value {value!r} not found"
        price0 = price.input_value()
        if edit.get("clear_brand"):
            combos = pg.locator('input[role="combobox"]')
            brand = None
            for i in range(combos.count()):
                if combos.nth(i).input_value() == edit["clear_brand"]: brand = combos.nth(i); break
            if brand is None: raise AssertionError(f"{ad}: brand value {edit['clear_brand']!r} not found")
            brand.locator("xpath=../..").get_by_role("button", name="Effacer", exact=True).click(); pg.wait_for_timeout(1000)
            if brand.input_value(): raise AssertionError(f"{ad}: brand did not clear")
        if new.get("title"): type_exact(title, new["title"])
        # Body last: Leboncoin's AI autofill can overwrite a body typed earlier.
        if new.get("body"): type_exact(body, new["body"])
        pg.wait_for_timeout(1000)
        if new.get("title") and title.input_value() != new["title"]: raise AssertionError(f"{ad}: title changed after fill")
        if new.get("body") and body.input_value() != new["body"]: raise AssertionError(f"{ad}: body overwritten after fill")
        if price.input_value() != price0: raise AssertionError(f"{ad}: price changed")
        if commit:
            commit_free(pg)
        else:
            print(ad, "DRY RUN OK — not submitted")
    finally:
        pg.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", type=Path, help="JSON list of edits (see module docstring)")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    edits = json.loads(args.spec.read_text(encoding="utf-8"))
    if not isinstance(edits, list) or not all(isinstance(e, dict) and e.get("ad_id") for e in edits):
        raise SystemExit("spec must be a JSON list of objects with an ad_id")
    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
        for edit in edits:
            apply(ctx, edit, args.commit)


if __name__ == "__main__":
    main()
