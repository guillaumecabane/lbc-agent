#!/usr/bin/env python3
"""Replace ALL photos of a Leboncoin ad with the given local files, in order (free edit, never boost).

Usage:
  lbc_replace_photos.py <ad_id> <exact_title> <photo1> [<photo2> ...] [--commit]

Without --commit: full rehearsal on the edit page (remove + upload + asserts), then closes WITHOUT submitting.
With --commit: submits « Valider les modifications » then « Modifier sans booster mon annonce ».
Title, body and price are asserted unchanged before submit. Run under scripts/with_browser_lock.py.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

CAPTCHA = 'iframe[src*="captcha-delivery.com"], #ddChallengeContainer'

args = [a for a in sys.argv[1:] if a != "--commit"]
COMMIT = "--commit" in sys.argv
AD, TITLE, PHOTOS = args[0], args[1], [str(Path(p).resolve()) for p in args[2:]]
if not PHOTOS:
    sys.exit("no photos given")
for p in PHOTOS:
    if not Path(p).is_file():
        sys.exit(f"missing file: {p}")


def dom_click(page, label):
    ok = page.evaluate(
        """(label) => {
        const b = [...document.querySelectorAll('button')].find(x => (x.getAttribute('aria-label')||'').trim() === label);
        if (!b) return false; b.click(); return true; }""",
        label,
    )
    if not ok:
        raise RuntimeError(f"button not found: {label}")


def photo_count(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('button')]
            .filter(b => /^Retirer la photo numéro \\d+$/.test((b.getAttribute('aria-label')||'').trim())).length"""
    )


def confirm_dialog_if_any(page):
    page.wait_for_timeout(800)
    for name in ("Retirer", "Supprimer", "Confirmer", "Oui"):
        btn = page.get_by_role("dialog").get_by_role("button", name=name, exact=True)
        if btn.count() == 1 and btn.is_visible():
            btn.click()
            page.wait_for_timeout(800)
            return


with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    try:
        page.evaluate("() => document.querySelector('#gimii-root')?.remove()") if False else None
        r = page.goto(f"https://www.leboncoin.fr/annonce/{AD}/editer", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        if page.locator(CAPTCHA).count():
            raise RuntimeError("CAPTCHA before mutation")
        if "en cours de validation" in page.inner_text("body"):
            raise RuntimeError("Ad under validation / locked by Leboncoin: edit not possible now")
        page.evaluate("() => document.querySelector('#gimii-root')?.remove()")
        title = page.locator('input[name="subject"]')
        body = page.locator('textarea[name="body"]')
        price = page.locator('input[name="price_cents"]')
        if title.input_value() != TITLE:
            raise AssertionError(f"title mismatch: {title.input_value()!r}")
        body0, price0 = body.input_value(), price.input_value()

        n0 = photo_count(page)
        print("photos before:", n0)
        for i in range(n0, 0, -1):
            dom_click(page, f"Retirer la photo numéro {i}")
            confirm_dialog_if_any(page)
        if photo_count(page) != 0:
            raise AssertionError(f"photos not all removed: {photo_count(page)} left")

        page.locator("input[type=file]").first.set_input_files(PHOTOS)
        for _ in range(60):
            page.wait_for_timeout(1000)
            if photo_count(page) == len(PHOTOS):
                break
        page.wait_for_timeout(4000)
        n1 = photo_count(page)
        print("photos after upload:", n1)
        if n1 != len(PHOTOS):
            raise AssertionError(f"upload count {n1} != {len(PHOTOS)}")
        if title.input_value() != TITLE or body.input_value() != body0 or price.input_value() != price0:
            raise AssertionError("title/body/price changed during photo edit")
        page.screenshot(path=str(tmp_path(f"lbc_replace_{AD}.png")), full_page=True)

        if not COMMIT:
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
