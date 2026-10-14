#!/usr/bin/env python3
"""Collect a compact, read-only Leboncoin weekly audit for the cron agent."""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener, urlopen
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lbc_config import CDP, EXPECTED_EGRESS, PROXY, STATE_DIR, TZ_NAME  # noqa: E402

DASHBOARD_URL = "https://www.leboncoin.fr/compte/part/mes-annonces"
DASHBOARD_PATH = "/api/dashboard/v1/search"
CONVERSATIONS_URL = "https://api.leboncoin.fr/api/messaging-items-api/v3/conversations"
TZ = ZoneInfo(TZ_NAME)
STATE = STATE_DIR / "weekly-snapshots.json"
LEGACY_ROTATION = STATE_DIR / "rotation-history.json"
MAX_SNAPSHOTS = 16
RECENT_CONVERSATION_DAYS = 45


def fail(stage: str, detail: str) -> None:
    print(json.dumps({"ok": False, "stage": stage, "detail": detail}, ensure_ascii=False))
    raise SystemExit(1)


def get_text(url: str, proxy: str | None = None, timeout: int = 12) -> str:
    if proxy:
        opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
        with opener.open(url, timeout=timeout) as response:
            return response.read().decode().strip()
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode().strip()


def load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else [data]
    except (OSError, json.JSONDecodeError):
        return []


def parse_lbc_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    except ValueError:
        return None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)
    except ValueError:
        return None


def attr_summary(ad: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in ad.get("attributes") or []:
        if not item.get("generic"):
            continue
        key = item.get("key_label") or item.get("key")
        value = item.get("value_label") or item.get("value")
        if key and value:
            out[str(key)] = str(value)
    return out


def main() -> None:
    now = datetime.now(TZ)
    try:
        cdp_version = json.loads(get_text(f"{CDP}/json/version", timeout=5))
    except Exception as exc:
        fail("cdp", f"{type(exc).__name__}: {exc}")

    # Optional egress check: only when the browser is routed through LBC_PROXY. If
    # LBC_EXPECTED_EGRESS is set too, refuse to run from any other public IP.
    proxy_egress = None
    if PROXY:
        try:
            proxy_egress = get_text("https://api.ipify.org", proxy=PROXY)
        except Exception as exc:
            fail("proxy", f"{type(exc).__name__}: {exc}")
        if EXPECTED_EGRESS and proxy_egress != EXPECTED_EGRESS:
            fail("proxy", f"unexpected egress {proxy_egress}")

    dashboard: dict | None = None
    dashboard_payload: dict | None = None
    dashboard_headers: dict[str, str] = {}
    dashboard_pages = 0
    auth_header: str | None = None
    counter_url: str | None = None
    unread_before: int | None = None
    page_state: dict = {}
    conversations: list[dict] = []
    conversation_pages = 0

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        if not browser.contexts:
            fail("browser", "no browser context")
        context = browser.contexts[0]
        pages = [pg for pg in context.pages if pg.url.startswith(DASHBOARD_URL)]
        page = pages[0] if pages else context.new_page()

        def on_request(request) -> None:
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

        def on_response(response) -> None:
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
            if page.url.startswith(DASHBOARD_URL):
                page.reload(wait_until="domcontentloaded", timeout=60_000)
            else:
                page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60_000)
        except PlaywrightTimeoutError:
            pass

        for _ in range(20):
            if dashboard is not None and auth_header:
                break
            page.wait_for_timeout(500)

        page_state = page.evaluate(
            """() => ({
              url: location.href,
              title: document.title,
              h1: document.querySelector('h1')?.innerText || null,
              hasLoginForm: !!document.querySelector('input[name=email],input[name=password]'),
              // Structural DataDome/captcha detection only: a text regex on "robot|vérif" false-positived on
              // the seller's own listing titles ("… pour robot …", "Vérifiez la compatibilité…").
              hasCaptcha: !!document.querySelector('iframe[src*="captcha-delivery.com"], iframe[src*="geo.captcha"], #ddChallengeContainer, [class*="ddCaptcha"]')
                || (!document.querySelector('h1') && /captcha|vérification de sécurité|êtes-vous un robot/i.test(document.body?.innerText || ''))
            })"""
        )
        if page_state.get("hasCaptcha"):
            fail("authentication", "CAPTCHA/anti-bot checkpoint")
        if page_state.get("hasLoginForm") or page_state.get("h1") != "Mes annonces":
            fail("authentication", f"not on authenticated dashboard: {page_state}")
        if dashboard is None:
            fail("dashboard", "dashboard response not captured")
        if not auth_header:
            fail("messaging", "authorization header not captured")
        if not dashboard_payload:
            fail("dashboard", "dashboard request payload not captured")

        # Stop passive capture before the manual requests below; otherwise their paginated response
        # would overwrite `dashboard` with only the last page.
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)

        # The dashboard loads only 30 cards initially even when `total` is larger. Fetch every
        # remaining offset from the authenticated page and merge by list_id. Do not trust the first
        # page as a complete catalogue: pricing/rotation recommendations require full coverage.
        initial_ads = list(dashboard.get("ads") or [])
        ads_by_id = {str(ad.get("list_id")): ad for ad in initial_ads if ad.get("list_id") is not None}
        limit = int(dashboard_payload.get("limit") or len(initial_ads) or 30)
        total = int(dashboard.get("total") or len(initial_ads))
        dashboard_pages = 1
        for offset in range(limit, total, limit):
            payload = dict(dashboard_payload)
            payload["offset"] = offset
            result = page.evaluate(
                """async ({url, payload, headers}) => {
                  const r = await fetch(url, {
                    method: 'POST', credentials: 'include',
                    headers: {accept: 'application/json', 'content-type': 'application/json', ...headers},
                    body: JSON.stringify(payload)
                  });
                  return {status: r.status, text: await r.text()};
                }""",
                {
                    "url": "https://api.leboncoin.fr/api/dashboard/v1/search",
                    "payload": payload,
                    "headers": dashboard_headers,
                },
            )
            if result["status"] != 200:
                fail("dashboard", f"dashboard page at offset {offset}: HTTP {result['status']}")
            try:
                extra = json.loads(result["text"])
            except json.JSONDecodeError:
                fail("dashboard", f"dashboard page at offset {offset}: invalid JSON")
            dashboard_pages += 1
            for ad in extra.get("ads") or []:
                if ad.get("list_id") is not None:
                    ads_by_id[str(ad.get("list_id"))] = ad
        dashboard["ads"] = list(ads_by_id.values())
        if len(dashboard["ads"]) != total:
            fail("dashboard", f"pagination incomplete: collected {len(dashboard['ads'])} of {total}")

        page_hash: str | None = None
        seen: set[str] = set()
        while True:
            url = CONVERSATIONS_URL
            if page_hash:
                url += "?page_hash=" + quote(page_hash, safe="")
            result = page.evaluate(
                """async ({url, auth}) => {
                  const r = await fetch(url, {
                    method: 'GET', credentials: 'include',
                    headers: {accept: 'application/json', authorization: auth, 'x-version': 'lbc-web-client'}
                  });
                  return {status: r.status, text: await r.text()};
                }""",
                {"url": url, "auth": auth_header},
            )
            if result["status"] != 200:
                fail("messaging", f"conversation page {conversation_pages + 1}: HTTP {result['status']}")
            body = json.loads(result["text"])
            conversation_pages += 1
            for conversation in body.get("conversations") or []:
                conversation_id = conversation.get("conversation_id")
                if conversation_id and conversation_id not in seen:
                    seen.add(conversation_id)
                    conversations.append(conversation)
            page_hash = (body.get("metadata") or {}).get("next_page_hash")
            if not page_hash:
                break
            if conversation_pages >= 20:
                fail("messaging", "pagination safety cap reached")

        unread_after = unread_before
        if counter_url:
            result = page.evaluate(
                """async ({url, auth}) => {
                  const r = await fetch(url, {
                    method: 'GET', credentials: 'include',
                    headers: {accept: 'application/json', authorization: auth}
                  });
                  return {status: r.status, text: await r.text()};
                }""",
                {"url": counter_url, "auth": auth_header},
            )
            if result["status"] == 200:
                try:
                    unread_after = json.loads(result["text"]).get("unread")
                except json.JSONDecodeError:
                    pass

    ads_raw = dashboard.get("ads") or []
    active_raw = [ad for ad in ads_raw if ad.get("status") == "active"]

    previous_snapshots = load_json_list(STATE)
    previous_metrics = {}
    if previous_snapshots:
        previous_metrics = {
            str(item.get("id")): item
            for item in (previous_snapshots[-1].get("metrics") or [])
        }

    ads: list[dict] = []
    metrics: list[dict] = []
    for ad in ads_raw:
        published = parse_lbc_date(ad.get("first_publication_date"))
        age_days = max((now - published).total_seconds() / 86_400, 1 / 24) if published else None
        stats = ad.get("stats") or {}
        views = int(stats.get("Views") or 0)
        item_id = str(ad.get("list_id"))
        previous = previous_metrics.get(item_id) or {}
        images = ad.get("images") or {}
        ad_compact = {
            "id": ad.get("list_id"),
            "status": ad.get("status"),
            "title": ad.get("subject"),
            "category": ad.get("category_name"),
            "price_eur": (ad.get("price") or [None])[0],
            "first_publication_date": ad.get("first_publication_date"),
            "age_days": round(age_days, 1) if age_days is not None else None,
            "views": views,
            "favorites": int(stats.get("Favorites") or 0),
            "messages": int(stats.get("Messages") or 0),
            "views_per_day": round(views / age_days, 3) if age_days else None,
            "delta_views": views - int(previous.get("views") or 0) if previous else None,
            "delta_favorites": int(stats.get("Favorites") or 0) - int(previous.get("favorites") or 0) if previous else None,
            "delta_messages": int(stats.get("Messages") or 0) - int(previous.get("messages") or 0) if previous else None,
            "photos": images.get("nb_images"),
            "hero_url": (images.get("urls") or [None])[0],
            "free_edit": ad.get("free_edit"),
            "body": ad.get("body") or "",
            "attributes": attr_summary(ad),
            "url": ad.get("url"),
        }
        ads.append(ad_compact)
        metrics.append({k: ad_compact[k] for k in (
            "id", "status", "title", "category", "price_eur", "first_publication_date",
            "views", "favorites", "messages", "photos"
        )})

    own_ad_ids = {str(a.get("id")) for a in ads if a.get("id") is not None}
    cutoff = now - timedelta(days=RECENT_CONVERSATION_DAYS)
    recent_conversations = []
    for conversation in conversations:
        sent = parse_iso(conversation.get("last_message_sent_at"))
        unseen = int(conversation.get("unseen_counter") or 0)
        if not unseen and (not sent or sent < cutoff):
            continue
        item = conversation.get("item") or {}
        # The account owner may also buy on Leboncoin. If the ad owner is the conversation partner, the
        # owner is the BUYER and any "offre" in the thread is their own offer — never report it as
        # incoming buyer interest.
        partner_ids = {p.get("id") for p in (conversation.get("partners") or []) if p.get("id")}
        owner_id = item.get("owner_id")
        if owner_id and owner_id in partner_ids:
            side = "buyer"
        elif owner_id or str(item.get("id")) in own_ad_ids:
            side = "seller"
        else:
            side = "unknown"
        recent_conversations.append({
            "conversation_id": conversation.get("conversation_id"),
            "side": side,
            "ad_id": item.get("id"),
            "ad_title": item.get("subject"),
            "ad_status": item.get("status"),
            "last_message_at": conversation.get("last_message_sent_at"),
            "preview": conversation.get("last_message_preview"),
            "unseen": unseen,
            "partners": [p.get("name") for p in (conversation.get("partners") or []) if p.get("name")],
        })

    legacy = load_json_list(LEGACY_ROTATION)
    last_proposed_ids = legacy[-1].get("selected_ids", []) if legacy else []
    recently_modified_ids = legacy[-1].get("recently_modified_excluded", []) if legacy else []

    snapshot = {
        "captured_at": now.isoformat(),
        "metrics": metrics,
        "unread": unread_after,
    }
    previous_snapshots.append(snapshot)
    previous_snapshots = previous_snapshots[-MAX_SNAPSHOTS:]
    if os.environ.get("LBC_COLLECT_DRY_RUN") != "1":
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(previous_snapshots, ensure_ascii=False, indent=2))
        os.chmod(STATE, 0o600)

    output = {
        "ok": True,
        "captured_at": now.isoformat(),
        "preflight": {
            "browser": cdp_version.get("Browser"),
            "proxy_egress": proxy_egress,
            "authenticated": True,
        },
        "dashboard_total": dashboard.get("total"),
        "dashboard_pages": dashboard_pages,
        "dashboard_ads_collected": len(ads_raw),
        "catalogue_complete": len(ads_raw) == int(dashboard.get("total") or 0),
        "account_stats": dashboard.get("account_stats"),
        "status_counts": {
            "active": len(active_raw),
            "paused": sum(ad.get("status") == "paused" for ad in ads_raw),
        },
        "rotation_count": math.ceil(len(active_raw) / 3),
        "last_proposed_ids": last_proposed_ids,
        "recently_modified_ids": recently_modified_ids,
        "ads": ads,
        "messaging": {
            "pages": conversation_pages,
            "conversation_count": len(conversations),
            "unread_before": unread_before,
            "unread_after": unread_after,
            "unread_unchanged": unread_before == unread_after,
            "recent_or_unread": recent_conversations,
        },
        "constraints": [
            "Read-only collector: no listing/message writes performed.",
            "index_date is not used as proof of a recent edit.",
            "Never accept a paid edit without explicit approval.",
        ],
    }
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
