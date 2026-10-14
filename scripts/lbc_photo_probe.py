#!/usr/bin/env python3
"""Read-only: inspect the photo section of a Leboncoin edit page. Never submits.

Usage: lbc_photo_probe.py <ad_id> [<ad_id> ...]
Prints current title/body/price, photo thumbnails (src), photo-related buttons and file inputs.
Downloads current thumbnails to $LBC_TMP/lbc_photos/<ad_id>/NN.jpg for visual review.
"""
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

OUT = tmp_path("lbc_photos")

with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    for ad in sys.argv[1:]:
        page = ctx.new_page()
        try:
            r = page.goto(f"https://www.leboncoin.fr/annonce/{ad}/editer", wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(6000)
            if page.locator('iframe[src*="captcha-delivery.com"], #ddChallengeContainer').count():
                raise RuntimeError("CAPTCHA")
            info = page.evaluate(
                """() => {
                const q = s => document.querySelector(s);
                const imgs = [...document.querySelectorAll('img')]
                  .filter(i => /img\\.leboncoin|leboncoin\\.fr\\/api\\/|blob:|data:image/.test(i.src) && i.naturalWidth > 40)
                  .map(i => ({src: i.src.slice(0, 200), alt: i.alt, w: i.naturalWidth}));
                const btns = [...document.querySelectorAll('button')]
                  .map(b => (b.getAttribute('aria-label') || b.innerText || '').trim())
                  .filter(t => /photo|image|supprimer|échanger|ajouter/i.test(t));
                const files = [...document.querySelectorAll('input[type=file]')]
                  .map(f => ({name: f.name, accept: f.accept, multiple: f.multiple}));
                return {
                  title: q('input[name="subject"]')?.value,
                  price: q('input[name="price_cents"]')?.value,
                  body: q('textarea[name="body"]')?.value,
                  imgs, btns, files,
                };
            }"""
            )
            info["http"] = r.status if r else None
            d = OUT / ad
            d.mkdir(parents=True, exist_ok=True)
            n = 0
            for im in info["imgs"]:
                if im["src"].startswith("http"):
                    n += 1
                    try:
                        urllib.request.urlretrieve(im["src"], d / f"{n:02d}.jpg")
                    except Exception as exc:
                        im["download_error"] = str(exc)
            print(f"######## {ad}")
            print(json.dumps(info, ensure_ascii=False, indent=1))
        finally:
            page.close()
