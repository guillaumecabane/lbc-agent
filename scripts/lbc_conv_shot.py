"""Read-only: screenshot a conversation and download its image attachments. Usage: lbc_conv_shot.py <conv_id>"""
import re
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

CID = sys.argv[1]
OUT = str(tmp_path("conv_" + CID[:8]))
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(CDP)
    page = b.contexts[0].new_page()
    page.set_viewport_size({"width": 1400, "height": 1800})
    try:
        page.goto(f"https://www.leboncoin.fr/messages/id/{CID}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        page.evaluate("() => document.querySelectorAll('#gimii-root').forEach(e => e.remove())")
        for _ in range(4):
            page.mouse.move(700, 900)
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1500)
        page.screenshot(path=OUT + ".png", full_page=False)
        srcs = page.evaluate("""() => [...document.querySelectorAll('main img, [role=main] img, img')]
            .map(i => [i.currentSrc || i.src, i.naturalWidth, i.naturalHeight, i.alt])
            .filter(x => x[1] >= 100 && !x[0].includes('ad-thumb'))""")
        for k, (src, w, h, alt) in enumerate(srcs):
            print(k, w, h, alt[:40], src[:140])
            if src.startswith("http"):
                r = page.request.get(src)
                if r.ok:
                    open(f"{OUT}_{k}.jpg", "wb").write(r.body())
        print("shot:", OUT + ".png")
    finally:
        page.close()
