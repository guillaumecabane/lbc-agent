#!/usr/bin/env python3
"""Read-only Leboncoin event watcher.

Polls the complete seller dashboard and all conversation summary pages, diffs them against a
0600 local state file, and prints chat-ready Markdown (e.g. for Telegram) only for new incoming messages/system
events or listing status/removal changes. Direct message-history GETs are read-only: the watcher
never invokes message read links, sends replies, or writes to Leboncoin.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lbc_config import CDP, STATE_DIR  # noqa: E402

DASHBOARD_URL = "https://www.leboncoin.fr/compte/part/mes-annonces"
DASHBOARD_API = "https://api.leboncoin.fr/api/dashboard/v1/search"
DASHBOARD_PATH = "/api/dashboard/v1/search"
CONVERSATIONS_API = "https://api.leboncoin.fr/api/messaging-items-api/v3/conversations"
STATE = STATE_DIR / "event-watch.json"
WEEKLY_STATE = STATE_DIR / "weekly-snapshots.json"
MAX_PAGES = 30
MAX_ALERTS = 12
REAPPEAR_GRACE = timedelta(minutes=30)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def latest_weekly_cutoff(now: datetime) -> datetime:
    snapshots = load_json(WEEKLY_STATE, [])
    if isinstance(snapshots, list) and snapshots:
        parsed = parse_dt(snapshots[-1].get("captured_at"))
        if parsed:
            return parsed
    return now - timedelta(minutes=20)


def atomic_save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def conversation_changed(current: dict, previous: dict | None) -> bool:
    if previous is None:
        return True
    return (
        current.get("last_message_at") != previous.get("last_message_at")
        or current.get("preview") != previous.get("preview")
        or int(current.get("unseen") or 0) > int(previous.get("unseen") or 0)
    )


def priority_icon(text: str, msg_type: str) -> str:
    lower = text.casefold()
    urgent = (
        "a payé", "paiement", "commande", "offre acceptée", "achat confirmé",
        "confirmer l'envoi", "confirmer l’envoi", "annulé", "annulation",
        "remboursement", "délai", "expédier avant", "débloquerons automatiquement",
    )
    if any(term in lower for term in urgent):
        return "🚨"
    if msg_type in {"ApiSystemMessage", "ApiIntegrationMessage"}:
        return "⚙️"
    return "🔔"


def render_alerts(alerts: list[dict]) -> str:
    if not alerts:
        return ""
    visible = alerts[:MAX_ALERTS]
    lines = [f"## Leboncoin — {len(alerts)} nouvel événement" + ("s" if len(alerts) != 1 else "")]
    for event in visible:
        if event["kind"] == "conversation":
            lines.extend([
                "",
                f"{event['icon']} **{event['title']}** — {event['partner']}",
                f"> {event['text'].replace(chr(10), ' / ')}",
                f"[Ouvrir la conversation](https://www.leboncoin.fr/messages/id/{event['conversation_id']})",
            ])
        else:
            lines.extend([
                "",
                f"📦 **{event['title']}**",
                event["text"],
            ])
    if len(alerts) > len(visible):
        lines.extend(["", f"… {len(alerts) - len(visible)} autre(s) changement(s)."])
    return "\n".join(lines)


def diff_events(current: dict, previous: dict | None, baseline_cutoff: datetime) -> list[dict]:
    alerts: list[dict] = []
    prev_convs = (previous or {}).get("conversations") or {}
    prev_captured = parse_dt((previous or {}).get("captured_at"))
    for cid, conv in current.get("conversations", {}).items():
        prev = prev_convs.get(cid)
        if not conversation_changed(conv, prev):
            continue
        sent = parse_dt(conv.get("last_message_at"))
        if previous is None and (not sent or sent <= baseline_cutoff):
            continue
        # A conversation missing from the previous snapshot (partial listing) whose latest
        # message predates that snapshot is a replay, not a new event (this once replayed ~20 old threads).
        if previous is not None and prev is None and prev_captured and (
            not sent or sent <= prev_captured - REAPPEAR_GRACE
        ):
            continue
        if conv.get("latest_outgoing") is not False:
            continue
        latest_id = conv.get("latest_message_id")
        if prev and latest_id and latest_id == prev.get("latest_message_id"):
            continue
        text = (conv.get("latest_text") or conv.get("preview") or "Pièce jointe reçue").strip()
        alerts.append({
            "kind": "conversation",
            "icon": priority_icon(text, conv.get("latest_type") or ""),
            "title": conv.get("title") or "Annonce Leboncoin",
            "partner": conv.get("partner") or "Acheteur",
            "text": text[:900],
            "conversation_id": cid,
            "sort_at": conv.get("last_message_at") or "",
        })

    if previous is not None:
        cur_ads = current.get("ads") or {}
        prev_ads = previous.get("ads") or {}
        for ad_id, old in prev_ads.items():
            new = cur_ads.get(ad_id)
            if new is None:
                alerts.append({
                    "kind": "listing",
                    "title": old.get("title") or f"Annonce {ad_id}",
                    "text": "L’annonce n’apparaît plus dans le catalogue du compte.",
                    "sort_at": current.get("captured_at") or "",
                })
            elif old.get("status") != new.get("status"):
                alerts.append({
                    "kind": "listing",
                    "title": new.get("title") or old.get("title") or f"Annonce {ad_id}",
                    "text": f"Statut modifié : **{old.get('status')} → {new.get('status')}**.",
                    "sort_at": current.get("captured_at") or "",
                })
    alerts.sort(key=lambda event: event.get("sort_at") or "")
    return alerts


def collect(previous: dict | None, baseline_cutoff: datetime) -> dict:
    now = datetime.now(timezone.utc)
    dashboard = None
    dashboard_payload = None
    dashboard_headers: dict[str, str] = {}
    auth_header = None
    counter_url = None
    unread_before = None

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        if not browser.contexts:
            raise RuntimeError("no browser context")
        context = browser.contexts[0]
        page = context.new_page()

        def on_request(request):
            nonlocal dashboard_payload, dashboard_headers, auth_header, counter_url
            if DASHBOARD_PATH in request.url:
                try:
                    dashboard_payload = request.post_data_json
                    headers = request.all_headers()
                    dashboard_headers = {
                        key: headers[key]
                        for key in ("authorization", "x-lbc-experiment")
                        if key in headers
                    }
                except Exception:
                    pass
            if "/counter/" in request.url:
                counter_url = request.url
                try:
                    auth_header = request.all_headers().get("authorization")
                except Exception:
                    pass

        def on_response(response):
            nonlocal dashboard, unread_before
            if DASHBOARD_PATH in response.url and response.status == 200:
                try:
                    dashboard = response.json()
                except Exception:
                    pass
            if "/counter/" in response.url and response.status == 200:
                try:
                    unread_before = response.json().get("unread")
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)
        try:
            page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightTimeoutError:
            pass
        for _ in range(20):
            if dashboard is not None and auth_header and dashboard_payload:
                break
            page.wait_for_timeout(500)

        state = page.evaluate("""() => ({
          h1: document.querySelector('h1')?.innerText || null,
          login: !!document.querySelector('input[name=email],input[name=password]'),
          captcha: !!document.querySelector('iframe[src*="captcha-delivery.com"],iframe[src*="geo.captcha"],#ddChallengeContainer,[class*="ddCaptcha"]')
        })""")
        if state["captcha"]:
            raise RuntimeError("DataDome/CAPTCHA checkpoint")
        if state["login"] or state["h1"] != "Mes annonces":
            raise RuntimeError(f"not authenticated: {state}")
        if dashboard is None or not dashboard_payload or not auth_header:
            raise RuntimeError("dashboard/auth capture incomplete")

        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)

        first_ads = list(dashboard.get("ads") or [])
        all_ads = {str(ad["list_id"]): ad for ad in first_ads if ad.get("list_id") is not None}
        limit = int(dashboard_payload.get("limit") or len(first_ads) or 30)
        total = int(dashboard.get("total") or len(first_ads))
        for page_number, offset in enumerate(range(limit, total, limit), start=2):
            if page_number > MAX_PAGES:
                raise RuntimeError("dashboard pagination safety cap reached")
            payload = dict(dashboard_payload)
            payload["offset"] = offset
            result = page.evaluate("""async ({url,payload,headers}) => {
              const r=await fetch(url,{method:'POST',credentials:'include',headers:{accept:'application/json','content-type':'application/json',...headers},body:JSON.stringify(payload)});
              return {status:r.status,text:await r.text()};
            }""", {"url": DASHBOARD_API, "payload": payload, "headers": dashboard_headers})
            if result["status"] != 200:
                raise RuntimeError(f"dashboard offset {offset}: HTTP {result['status']}")
            extra = json.loads(result["text"])
            for ad in extra.get("ads") or []:
                if ad.get("list_id") is not None:
                    all_ads[str(ad["list_id"])] = ad
        if len(all_ads) != total:
            raise RuntimeError(f"incomplete dashboard: {len(all_ads)}/{total}")

        owner_id = str(((dashboard_payload.get("filters") or {}).get("owner") or {}).get("user_id") or "")
        if not owner_id:
            raise RuntimeError("owner id unavailable")

        conversations = []
        page_hash = None
        for page_number in range(1, MAX_PAGES + 1):
            url = CONVERSATIONS_API + (("?page_hash=" + quote(page_hash, safe="")) if page_hash else "")
            result = page.evaluate("""async ({url,auth}) => {
              const r=await fetch(url,{credentials:'include',headers:{accept:'application/json',authorization:auth,'x-version':'lbc-web-client'}});
              return {status:r.status,text:await r.text()};
            }""", {"url": url, "auth": auth_header})
            if result["status"] != 200:
                raise RuntimeError(f"conversation page {page_number}: HTTP {result['status']}")
            body = json.loads(result["text"])
            conversations.extend(body.get("conversations") or [])
            page_hash = (body.get("metadata") or {}).get("next_page_hash")
            if not page_hash:
                break
        else:
            raise RuntimeError("conversation pagination safety cap reached")

        prev_convs = (previous or {}).get("conversations") or {}
        seller_convs: dict[str, dict] = {}
        for conv in conversations:
            item = conv.get("item") or {}
            if str(item.get("owner_id") or "") != owner_id:
                continue
            cid = conv.get("conversation_id")
            if not cid:
                continue
            partners = [p.get("name") for p in (conv.get("partners") or []) if p.get("name")]
            compact = {
                "ad_id": str(item.get("id") or ""),
                "title": item.get("subject") or "",
                "ad_status": item.get("status") or "",
                "partner": partners[0] if partners else "Acheteur",
                "last_message_at": conv.get("last_message_sent_at"),
                "preview": conv.get("last_message_preview") or "",
                "unseen": int(conv.get("unseen_counter") or 0),
            }
            previous_conv = prev_convs.get(cid)
            sent = parse_dt(compact["last_message_at"])
            should_fetch = conversation_changed(compact, previous_conv) and (
                previous is not None or (sent is not None and sent > baseline_cutoff)
            )
            if should_fetch:
                category_ids = item.get("category_ids") or []
                history_url = (
                    f"https://api.leboncoin.fr/messaging/proxy/api/v1/hal/{owner_id}/conversations/{cid}/messages"
                    "?expanded=true&order=asc"
                )
                if category_ids:
                    history_url += "&category_id=" + quote(str(category_ids[0]), safe="")
                result = page.evaluate("""async ({url,auth,experiment,referer}) => {
                  const headers={accept:'*/*','content-type':'application/json',authorization:auth,'x-version':'lbc-web-client'};
                  if (experiment) headers['x-lbc-experiment']=experiment;
                  const r=await fetch(url,{credentials:'include',headers,referrer:referer});
                  return {status:r.status,text:await r.text()};
                }""", {
                    "url": history_url,
                    "auth": auth_header,
                    "experiment": dashboard_headers.get("x-lbc-experiment"),
                    "referer": f"https://www.leboncoin.fr/messages/id/{cid}",
                })
                if result["status"] != 200:
                    raise RuntimeError(f"history {cid}: HTTP {result['status']}")
                history = json.loads(result["text"])
                messages = ((history.get("_embedded") or {}).get("messages") or [])
                if messages:
                    latest = max(messages, key=lambda m: m.get("sentAt") or m.get("date") or "")
                    compact.update({
                        "latest_message_id": latest.get("id"),
                        "latest_outgoing": latest.get("outgoing"),
                        "latest_type": latest.get("type"),
                        "latest_text": latest.get("text") or ("Pièce jointe reçue" if latest.get("attachments") else ""),
                    })
            elif previous_conv:
                for key in ("latest_message_id", "latest_outgoing", "latest_type", "latest_text"):
                    if key in previous_conv:
                        compact[key] = previous_conv[key]
            seller_convs[cid] = compact

        unread_after = unread_before
        if counter_url:
            result = page.evaluate("""async ({url,auth}) => {
              const r=await fetch(url,{credentials:'include',headers:{accept:'application/json',authorization:auth}});
              return {status:r.status,text:await r.text()};
            }""", {"url": counter_url, "auth": auth_header})
            if result["status"] == 200:
                unread_after = json.loads(result["text"]).get("unread")
        page.close()

    return {
        "schema_version": 1,
        "captured_at": now.isoformat(),
        "catalogue_total": total,
        "catalogue_complete": len(all_ads) == total,
        "unread_before": unread_before,
        "unread_after": unread_after,
        "ads": {
            ad_id: {
                "title": ad.get("subject") or "",
                "status": ad.get("status") or "",
                "price_eur": (ad.get("price") or [None])[0],
            }
            for ad_id, ad in all_ads.items()
        },
        "conversations": seller_convs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="collect and diff without saving state")
    parser.add_argument("--baseline", action="store_true", help="save current state without emitting alerts")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    previous = load_json(STATE, None)
    if not isinstance(previous, dict):
        previous = None
    cutoff = latest_weekly_cutoff(now)
    current = collect(previous, cutoff)
    alerts = diff_events(current, previous, cutoff)
    if previous:
        # Carry forward conversations absent from a (possibly partial) listing so they are
        # not re-reported as new when they reappear.
        for cid, conv in (previous.get("conversations") or {}).items():
            current["conversations"].setdefault(cid, conv)
    if not args.dry_run:
        atomic_save(STATE, current)
    if not args.baseline:
        output = render_alerts(alerts)
        if output:
            print(output)


if __name__ == "__main__":
    main()
