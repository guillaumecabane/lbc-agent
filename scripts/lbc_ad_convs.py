"""Read-only: print buyer conversations for one or more ads (passive capture of the page's own responses; sends nothing).

Usage: lbc_ad_convs.py <ad_id> [<ad_id> ...]
"""
import json
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP

ADS = sys.argv[1:]


def walk(o, pred, out):
    if isinstance(o, dict):
        if pred(o):
            out.append(o)
        for v in o.values():
            walk(v, pred, out)
    elif isinstance(o, list):
        for v in o:
            walk(v, pred, out)


with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(CDP)
    page = b.contexts[0].new_page()
    caps = []

    def on_resp(r):
        if r.request.resource_type in ("xhr", "fetch") and ("conversation" in r.url or "messag" in r.url):
            try:
                caps.append(r.json())
            except Exception:
                pass

    page.on("response", on_resp)
    try:
        page.goto("https://www.leboncoin.fr/messages", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)
        for ad in ADS:
            hits = []
            for j in caps:
                walk(j, lambda d: ad in json.dumps(d) and any(k in d for k in ("conversationId", "conversation_id")), hits)
            ids = []
            for h in hits:
                cid = h.get("conversationId") or h.get("conversation_id")
                if cid and cid not in ids:
                    ids.append(cid)
            print(f"######## ad {ad}: {len(ids)} conversation(s)")
            for cid in ids:
                caps_before = len(caps)
                page.goto(f"https://www.leboncoin.fr/messages/id/{cid}", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(7000)
                msgs = []
                for j in caps[caps_before:]:
                    walk(j, lambda d: ("text" in d or "body" in d) and any(k in d for k in ("createdAt", "created_at", "date")), msgs)
                print("=== conversation", cid, "| api msgs:", len(msgs))
                if not msgs:
                    txt = page.inner_text("body")
                    i = txt.find("À propos de cet acheteur")
                    j2 = txt.find("Envoyez une réponse rapide")
                    if j2 < 0:
                        j2 = txt.find("Faire une offre", i if i > 0 else 0)
                    print("  PAGE:", txt[i if i > 0 else 0:(j2 if j2 > 0 else i + 2500)].replace("\n", " | ")[:2500])
                seen = set()
                for m in sorted(msgs, key=lambda m: str(m.get("createdAt") or m.get("created_at"))):
                    t = str(m.get("text") or m.get("body") or "")
                    dt = m.get("createdAt") or m.get("created_at")
                    if (dt, t) in seen:
                        continue
                    seen.add((dt, t))
                    who = "ME" if (m.get("isMe") or m.get("outgoing") or m.get("is_me")) else (m.get("type") or "")
                    print(" ", dt, "|", who, "|", t[:500].replace("\n", " / "))
    finally:
        page.close()
