#!/usr/bin/env python3
"""Free edit of a Leboncoin ad: title/body (and optionally price) + append photos. Never boosts.

Usage:
  lbc_edit_listing.py <ad_id> <current_title> --title-file F --body-file F [--price EUR] [--add-photo P ...] [--commit]

Dry run (no --commit): fills everything, asserts values, saves a screenshot, closes WITHOUT submitting.
--commit: « Valider les modifications » then « Modifier sans booster mon annonce ».
Run under scripts/with_browser_lock.py.
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

CAPTCHA = 'iframe[src*="captcha-delivery.com"], #ddChallengeContainer'

ap = argparse.ArgumentParser()
ap.add_argument("ad")
ap.add_argument("current_title")
ap.add_argument("--title-file", type=Path)
ap.add_argument("--body-file", type=Path)
ap.add_argument("--price", type=int)
ap.add_argument("--add-photo", action="append", default=[])
ap.add_argument("--commit", action="store_true")
a = ap.parse_args()
NEW_TITLE = a.title_file.read_text().strip() if a.title_file else None
NEW_BODY = a.body_file.read_text().strip() if a.body_file else None
PHOTOS = [str(Path(p).resolve()) for p in a.add_photo]
for p in PHOTOS:
    if not Path(p).is_file():
        raise SystemExit(f"missing photo {p}")


def type_exact(field, text):
    field.click()
    field.press("Control+A")
    field.press_sequentially(text, delay=1)
    field.press("Tab")
    if field.input_value() != text:
        raise AssertionError(f"React field mismatch: {field.input_value()[:80]!r}")


def photo_count(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('button')]
            .filter(b => /^Retirer la photo numéro \\d+$/.test((b.getAttribute('aria-label')||'').trim())).length"""
    )


with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    try:
        r = page.goto(f"https://www.leboncoin.fr/annonce/{a.ad}/editer", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        if page.locator(CAPTCHA).count():
            raise RuntimeError("CAPTCHA before mutation")
        if "en cours de validation" in page.inner_text("body"):
            raise RuntimeError("Ad locked (transaction in progress): edit not possible now")
        page.evaluate("() => document.querySelector('#gimii-root')?.remove()")
        title = page.locator('input[name="subject"]')
        body = page.locator('textarea[name="body"]')
        price = page.locator('input[name="price_cents"]')
        if title.input_value() != a.current_title:
            raise AssertionError(f"title mismatch: {title.input_value()!r}")
        print("CURRENT body:\n" + body.input_value() + "\n---")
        price0 = price.input_value()
        n0 = photo_count(page)
        print("price", price0, "photos", n0)

        if PHOTOS:
            page.locator("input[type=file]").first.set_input_files(PHOTOS)
            for _ in range(60):
                page.wait_for_timeout(1000)
                if photo_count(page) == n0 + len(PHOTOS):
                    break
            page.wait_for_timeout(3000)
            if photo_count(page) != n0 + len(PHOTOS):
                raise AssertionError(f"photo upload: {photo_count(page)} != {n0 + len(PHOTOS)}")
        # Body last: the AI autofill can fire after photo upload and overwrite it.
        if NEW_TITLE:
            type_exact(title, NEW_TITLE)
        if a.price is not None:
            type_exact(price, str(a.price))
        if NEW_BODY:
            type_exact(body, NEW_BODY)
        page.wait_for_timeout(1500)
        exp_price = str(a.price) if a.price is not None else price0
        if NEW_TITLE and title.input_value() != NEW_TITLE:
            raise AssertionError("title changed after fill")
        if NEW_BODY and body.input_value() != NEW_BODY:
            raise AssertionError("body overwritten after fill")
        if price.input_value() != exp_price:
            raise AssertionError(f"price {price.input_value()} != {exp_price}")
        print("photos now", photo_count(page))
        page.screenshot(path=str(tmp_path(f"lbc_edit_{a.ad}.png")), full_page=True)

        if not a.commit:
            print("DRY RUN OK — not submitted")
        else:
            btn = page.get_by_role("button", name="Valider les modifications", exact=True)
            if btn.count() != 1 or not btn.is_enabled():
                raise RuntimeError("first commit unavailable")
            btn.click()
            page.wait_for_timeout(9000)
            if page.locator(CAPTCHA).count():
                raise RuntimeError("CAPTCHA after first commit")
            free = page.get_by_role("button", name="Modifier sans booster mon annonce", exact=True)
            if free.count() != 1 or not free.is_enabled():
                raise RuntimeError("free second commit unavailable; refusing paid action")
            free.click()
            page.wait_for_timeout(10000)
            print("accepted", page.url)
    finally:
        page.close()
