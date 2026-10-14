#!/usr/bin/env python3
"""Leboncoin comparable-listing search (read-only).

Captures the search page's own `finder/search` responses through the shared
authenticated Chrome (CDP), filters them, and prints asking-price statistics.

Run under the browser lock:
  python3 scripts/with_browser_lock.py --timeout 300 -- \
    python3 scripts/lbc_comps.py --query "brand model" --query "brand model variant" \
      --include "model" --exclude "max|pro|lot|pièce|brosse|rouleau" \
      --exclude-id 1234567890 --out items/<slug>/comps.json

Asking prices are not sale prices. Ads still online after 30+ days at a price
are evidence that price does not clear.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright
from lbc_config import CDP



def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 2)


async def search(ctx, query: str) -> list[dict]:
    page = await ctx.new_page()
    ads: list[dict] = []

    async def on_resp(resp):
        if "finder/search" in resp.url and resp.status == 200:
            try:
                ads.extend((await resp.json()).get("ads") or [])
            except Exception:  # noqa: BLE001
                pass

    page.on("response", lambda r: asyncio.ensure_future(on_resp(r)))
    await page.goto(f"https://www.leboncoin.fr/recherche?text={quote(query)}", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(7000)
    if not ads:
        try:
            data = json.loads(await page.locator("script#__NEXT_DATA__").inner_text())
            ads = ((data["props"]["pageProps"].get("searchData")) or {}).get("ads") or []
        except Exception:  # noqa: BLE001
            ads = []
    await page.close()
    return ads


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", action="append", required=True, help="search text; repeatable")
    ap.add_argument("--include", default="", help="regex the subject must match (case-insensitive)")
    ap.add_argument("--exclude", default="", help="regex that disqualifies a subject (case-insensitive)")
    ap.add_argument("--exclude-id", action="append", default=[], help="own listing ids to drop")
    ap.add_argument("--min-price", type=float, default=2)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    inc = re.compile(args.include, re.I) if args.include else None
    exc = re.compile(args.exclude, re.I) if args.exclude else None
    now = datetime.now(timezone.utc)
    seen: dict[str, dict] = {}
    dropped = 0
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        for q in args.query:
            for a in await search(ctx, q):
                lid = str(a.get("list_id"))
                if lid in seen or lid in args.exclude_id:
                    continue
                subject = a.get("subject") or ""
                price = (a.get("price") or [None])[0]
                if price is None or price < args.min_price or (inc and not inc.search(subject)) or (exc and exc.search(subject)):
                    dropped += 1
                    continue
                attrs = {x.get("key"): x.get("value_label") for x in a.get("attributes", [])}
                first = a.get("first_publication_date") or ""
                try:
                    age = (now - datetime.strptime(first, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)).days
                except ValueError:
                    age = None
                seen[lid] = {
                    "id": lid,
                    "price": price,
                    "subject": subject,
                    "condition": attrs.get("condition"),
                    "shipping": attrs.get("shippable") == "true",
                    "age_days": age,
                    "city": (a.get("location") or {}).get("city"),
                    "url": a.get("url"),
                }

    comps = sorted(seen.values(), key=lambda r: r["price"])
    prices = [c["price"] for c in comps]
    used = [c["price"] for c in comps if (c["condition"] or "").lower() not in {"état neuf", "neuf"}]
    stale = [c["price"] for c in comps if (c["age_days"] or 0) >= 30]
    summary = {
        "searched_at": now.isoformat(timespec="seconds"),
        "queries": args.query,
        "include": args.include,
        "exclude": args.exclude,
        "n": len(prices),
        "dropped": dropped,
        "min": min(prices) if prices else None,
        "p25": pct(prices, 0.25),
        "median": pct(prices, 0.5),
        "p75": pct(prices, 0.75),
        "max": max(prices) if prices else None,
        "used_median": pct(used, 0.5),
        "stale_30d_n": len(stale),
        "stale_30d_median": pct(stale, 0.5),
        "comps": comps,
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    head = {k: v for k, v in summary.items() if k != "comps"}
    print(json.dumps(head, ensure_ascii=False))
    for c in comps:
        print(f"{c['price']:>7} | {c['condition'] or '-':<18} | {c['age_days'] if c['age_days'] is not None else '?':>4}j | {c['subject'][:90]}")
    return 0 if prices else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
