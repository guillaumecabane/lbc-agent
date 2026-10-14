"""Read-only: status of one ad — public page HTTP/state + presence/status in the owner dashboard.

Usage: lbc_ad_status.py <ad_id>
"""
import json
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP

AD = sys.argv[1]
found = {}


def walk(o):
    if isinstance(o, dict):
        if str(o.get("list_id") or o.get("ad_id") or "") == AD and o.get("subject"):
            found["ad"] = {"subject": o.get("subject"), "price": o.get("price"), "status": o.get("status")}
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)


with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(CDP)
    page = b.contexts[0].new_page()
    try:
        r = page.goto(f"https://www.leboncoin.fr/vi/{AD}.htm", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        t = page.inner_text("body")
        print("public HTTP", r.status if r else None, "| désactivée:", "Cette annonce est désactivée" in t)
        page.on("response", lambda resp: (walk(resp.json()) if resp.request.resource_type in ("xhr", "fetch") and "dashboard" in resp.url else None))
        page.goto("https://www.leboncoin.fr/compte/part/mes-annonces", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        tabs = page.evaluate("""() => [...new Set([...document.querySelectorAll('a, button, [role=tab]')].map(e => (e.innerText||'').trim()).filter(x => /^En ligne|^Expir/i.test(x)))]""")
        print("dashboard tabs:", tabs)
        print("dashboard entry:", json.dumps(found.get("ad"), ensure_ascii=False))
    finally:
        page.close()
