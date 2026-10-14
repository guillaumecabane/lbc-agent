#!/usr/bin/env python3
"""Read-only: snapshot own Leboncoin ads from the authenticated dashboard API (all offsets) and download photos.

Usage: lbc_ad_snapshot.py <out_dir> <ad_id> [<ad_id> ...]   (run under scripts/with_browser_lock.py)
Writes <out_dir>/<ad_id>/ad.json (full dashboard record) and NN.jpg.
"""
import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
from lbc_config import CDP

OUT = Path(sys.argv[1])
IDS = set(sys.argv[2:])
API = "https://api.leboncoin.fr/api/dashboard/v1/search"
with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    first = {}

    def on_resp(r):
        if "dashboard/v1/search" in r.url and r.status == 200 and not first:
            req = r.request
            first.update(payload=json.loads(req.post_data or "{}"), body=r.json(),
                         headers={k: v for k, v in req.headers.items() if k.lower() in ("authorization", "api_key")})

    page.on("response", on_resp)
    try:
        page.goto("https://www.leboncoin.fr/compte/part/mes-annonces", wait_until="domcontentloaded", timeout=60000)
        for _ in range(30):
            page.wait_for_timeout(500)
            if first:
                break
        if not first:
            raise SystemExit("dashboard API not captured")
        ads = {str(a["list_id"]): a for a in first["body"].get("ads") or []}
        total = int(first["body"].get("total") or len(ads))
        limit = int(first["payload"].get("limit") or 30)
        for off in range(limit, total, limit):
            res = page.evaluate("""async ({url, payload, headers}) => {
                const r = await fetch(url, {method: 'POST', credentials: 'include',
                  headers: {accept: 'application/json', 'content-type': 'application/json', ...headers}, body: JSON.stringify(payload)});
                return {status: r.status, text: await r.text()}; }""", {"url": API, "payload": dict(first["payload"], offset=off), "headers": first["headers"]})
            if res["status"] != 200:
                raise SystemExit(f"offset {off}: HTTP {res['status']}")
            for a in json.loads(res["text"]).get("ads") or []:
                ads[str(a["list_id"])] = a
    finally:
        page.close()

for lid in IDS:
    a = ads.get(lid)
    if not a:
        print(lid, "NOT FOUND")
        continue
    d = OUT / lid
    d.mkdir(parents=True, exist_ok=True)
    imgs = a.get("images") or {}
    urls = imgs.get("urls_large") or imgs.get("urls") or [x.get("url") if isinstance(x, dict) else x for x in (a.get("images_list") or [])]
    files = []
    for i, u in enumerate(urls, 1):
        f = d / f"{i:02d}.jpg"
        urllib.request.urlretrieve(u, f)
        files.append(str(f))
    a["_downloaded_photos"] = files
    (d / "ad.json").write_text(json.dumps(a, ensure_ascii=False, indent=1))
    print(lid, a.get("subject"), "| keys:", sorted(a.keys())[:40], "| photos", len(files))
