#!/usr/bin/env python3
"""Read-only: scan ALL live ad bodies (fresh dashboard API, every offset) for seller handoff promises
and wording the seller banned. Saves every body to $LBC_TMP/body-fix/live/<id>.txt."""
import json
import re

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

PAT = re.compile(r"(?i)r[ée]initialis|param[èe]tres d.usine|r[ée]glages d.usine|z[ée]ro|\breset\b|dissoci|compte|avant (la )?remise|rebranch|r[ée]aliment|test[ée]+ (à|a) la remise|envoi via leboncoin|d[ée]mo")
OUT = tmp_path("body-fix/live")
OUT.mkdir(parents=True, exist_ok=True)
API = "https://api.leboncoin.fr/api/dashboard/v1/search"
with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    first = {}

    def on_resp(r):
        if "dashboard/v1/search" in r.url and r.status == 200 and not first:
            req = r.request
            first.update(payload=json.loads(req.post_data or "{}"), body=r.json(),
                         headers={k: v for k, v in req.headers.items() if k.lower() in ("authorization", "api_key", "x-lbc-experiment")})

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
        limit = int(first["payload"].get("limit") or len(ads) or 30)
        for off in range(limit, total, limit):
            pl = dict(first["payload"], offset=off)
            res = page.evaluate("""async ({url, payload, headers}) => {
                const r = await fetch(url, {method: 'POST', credentials: 'include',
                  headers: {accept: 'application/json', 'content-type': 'application/json', ...headers}, body: JSON.stringify(payload)});
                return {status: r.status, text: await r.text()}; }""", {"url": API, "payload": pl, "headers": first["headers"]})
            if res["status"] != 200:
                raise SystemExit(f"offset {off}: HTTP {res['status']}")
            for a in json.loads(res["text"]).get("ads") or []:
                ads[str(a["list_id"])] = a
    finally:
        page.close()
print(f"ads captured: {len(ads)} / total {total}")
for lid, a in ads.items():
    body = a.get("body") or ""
    (OUT / f"{lid}.txt").write_text(body)
    hits = [s.strip() for s in re.split(r"(?<=[.!?\n])\s*", body) if PAT.search(s)]
    if hits:
        print(f"## {lid} | {a.get('status')} | {a.get('subject')}")
        for h in hits:
            print("   >", h)
