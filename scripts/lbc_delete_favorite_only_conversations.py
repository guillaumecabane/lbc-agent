#!/usr/bin/env python3
"""Delete pre-audited favorite-only Leboncoin conversations.

Safety gates:
- exact approved audit catalogue;
- fresh authenticated GET history immediately before deletion;
- exactly one incoming ApiSystemMessage with the favorite prompt;
- no attachment, outgoing message, integration event, or human message;
- UI confirmation dialog for every deletion;
- fresh paginated conversation-list verification after the batch.

Usage:
  python3 scripts/lbc_delete_favorite_only_conversations.py AUDIT.json [--commit]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from lbc_config import CDP

DASHBOARD_URL = "https://www.leboncoin.fr/compte/part/mes-annonces"
CONVERSATIONS_API = "https://api.leboncoin.fr/api/messaging-items-api/v3/conversations"
PROMPT = "Votre bien est toujours disponible ? Faites-le lui savoir."


def compact(value: object) -> str:
    return " ".join(str(value or "").split())


def exact_favorite_only(messages: list[dict]) -> bool:
    if len(messages) != 1:
        return False
    message = messages[0]
    return (
        message.get("type") == "ApiSystemMessage"
        and not bool(message.get("outgoing"))
        and not bool(message.get("attachments"))
        and compact(message.get("text")) == compact(PROMPT)
    )


def fetch_conversations(page, auth: str) -> list[dict]:
    rows: list[dict] = []
    page_hash = None
    for _ in range(30):
        url = CONVERSATIONS_API + (("?page_hash=" + quote(page_hash, safe="")) if page_hash else "")
        result = page.evaluate("""async ({url,auth}) => {
          const r = await fetch(url, {credentials:'include', cache:'no-store', headers:{accept:'application/json', authorization:auth, 'x-version':'lbc-web-client'}});
          return {status:r.status, text:await r.text()};
        }""", {"url": url, "auth": auth})
        if result["status"] != 200:
            raise RuntimeError(f"conversation list HTTP {result['status']}")
        body = json.loads(result["text"])
        rows.extend(body.get("conversations") or [])
        page_hash = (body.get("metadata") or {}).get("next_page_hash")
        if not page_hash:
            return rows
    raise RuntimeError("conversation pagination safety cap reached")


def fetch_history(page, owner_id: str, auth: str, experiment: str | None, conv: dict) -> list[dict]:
    cid = conv.get("conversation_id")
    item = conv.get("item") or {}
    category_ids = item.get("category_ids") or []
    url = (
        f"https://api.leboncoin.fr/messaging/proxy/api/v1/hal/{owner_id}/conversations/{cid}/messages"
        "?expanded=true&order=asc"
    )
    if category_ids:
        url += "&category_id=" + quote(str(category_ids[0]), safe="")
    result = page.evaluate("""async ({url,auth,experiment,referer}) => {
      const headers = {accept:'*/*', 'content-type':'application/json', authorization:auth, 'x-version':'lbc-web-client'};
      if (experiment) headers['x-lbc-experiment'] = experiment;
      const r = await fetch(url, {credentials:'include', cache:'no-store', headers, referrer:referer});
      return {status:r.status, text:await r.text()};
    }""", {
        "url": url,
        "auth": auth,
        "experiment": experiment,
        "referer": f"https://www.leboncoin.fr/messages/id/{cid}",
    })
    if result["status"] != 200:
        raise RuntimeError(f"history {cid}: HTTP {result['status']}")
    body = json.loads(result["text"])
    return ((body.get("_embedded") or {}).get("messages") or [])


def load_conversation_ui(page, cid: str) -> str:
    url = f"https://www.leboncoin.fr/messages/id/{cid}"
    for attempt in range(2):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        if body:
            return body
        if attempt == 0:
            page.goto("https://www.leboncoin.fr/messages", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
    raise RuntimeError(f"blank conversation UI: {cid}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    approved = {
        row["conversation_id"]: row
        for row in audit.get("catalogue") or []
        if row.get("eligible") and row.get("message_count") == 1
    }
    if not approved:
        raise RuntimeError("approved audit contains no eligible conversation")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        context = browser.contexts[0]
        page = context.new_page()
        dashboard_payload = None
        auth_header = None
        experiment = None
        counter_url = None
        unread_before = None

        def on_request(request):
            nonlocal dashboard_payload, auth_header, experiment, counter_url
            if "/api/dashboard/v1/search" in request.url:
                try:
                    dashboard_payload = request.post_data_json
                    experiment = request.all_headers().get("x-lbc-experiment")
                except Exception:
                    pass
            if "/counter/" in request.url:
                try:
                    auth_header = request.all_headers().get("authorization")
                    counter_url = request.url
                except Exception:
                    pass

        def on_response(response):
            nonlocal unread_before
            if "/counter/" in response.url and response.status == 200:
                try:
                    unread_before = response.json().get("unread")
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)
        try:
            page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightTimeoutError:
            pass
        for _ in range(24):
            if dashboard_payload and auth_header:
                break
            page.wait_for_timeout(500)
        if not dashboard_payload or not auth_header:
            raise RuntimeError("authenticated dashboard capture incomplete")
        owner_id = str(((dashboard_payload.get("filters") or {}).get("owner") or {}).get("user_id") or "")
        if not owner_id:
            raise RuntimeError("owner id unavailable")

        current_rows = fetch_conversations(page, auth_header)
        current = {row.get("conversation_id"): row for row in current_rows}
        fresh_eligible: list[str] = []
        absent_before: list[str] = []
        changed: list[dict] = []
        for cid, approved_row in approved.items():
            conv = current.get(cid)
            if not conv:
                absent_before.append(cid)
                continue
            messages = fetch_history(page, owner_id, auth_header, experiment, conv)
            if exact_favorite_only(messages):
                fresh_eligible.append(cid)
            else:
                changed.append({
                    "conversation_id": cid,
                    "title": approved_row.get("title"),
                    "partner": approved_row.get("partner"),
                    "message_count": len(messages),
                })

        preflight = {
            "approved": len(approved),
            "fresh_eligible": len(fresh_eligible),
            "changed_and_skipped": changed,
            "already_absent": len(absent_before),
            "unread_before": unread_before,
        }
        if not args.commit:
            print(json.dumps({"dry_run": True, **preflight}, ensure_ascii=False, indent=2))
            page.close()
            return 0

        page.goto("https://www.leboncoin.fr/messages", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        deleted: list[dict] = []
        failed: list[dict] = []
        for cid in fresh_eligible:
            approved_row = approved[cid]
            try:
                # Re-check through GET immediately before this irreversible action.
                refreshed_rows = fetch_conversations(page, auth_header)
                refreshed = {row.get("conversation_id"): row for row in refreshed_rows}
                conv = refreshed.get(cid)
                if not conv:
                    absent_before.append(cid)
                    continue
                messages = fetch_history(page, owner_id, auth_header, experiment, conv)
                if not exact_favorite_only(messages):
                    changed.append({
                        "conversation_id": cid,
                        "title": approved_row.get("title"),
                        "partner": approved_row.get("partner"),
                        "message_count": len(messages),
                    })
                    continue

                body = load_conversation_ui(page, cid)
                for expected in (approved_row.get("title"), approved_row.get("partner"), "Message automatique leboncoin"):
                    if expected and expected not in body:
                        raise RuntimeError(f"UI mismatch for {expected!r}")
                page.get_by_role("button", name="Plus d'options").click()
                delete_control = page.locator("button:visible").filter(has_text="Supprimer la conversation")
                if delete_control.count() != 1:
                    raise RuntimeError(f"visible delete controls: {delete_control.count()}")
                delete_control.click()
                dialog = page.get_by_role("dialog")
                dialog.wait_for(state="visible", timeout=5000)
                if "Voulez-vous vraiment supprimer cette conversation ?" not in dialog.inner_text():
                    raise RuntimeError("unexpected deletion confirmation dialog")

                write_responses: list[dict] = []

                def capture_write(response):
                    if response.request.method != "GET" and "conversation" in response.url:
                        write_responses.append({"method": response.request.method, "status": response.status, "url": response.url})

                page.on("response", capture_write)
                dialog.get_by_role("button", name="Supprimer", exact=True).click()
                page.wait_for_timeout(1800)
                page.remove_listener("response", capture_write)
                if not write_responses or not any(200 <= item["status"] < 300 for item in write_responses):
                    raise RuntimeError(f"no successful delete response: {write_responses}")
                deleted.append({
                    "conversation_id": cid,
                    "title": approved_row.get("title"),
                    "partner": approved_row.get("partner"),
                    "write": [{"method": item["method"], "status": item["status"]} for item in write_responses],
                })
            except Exception as exc:
                failed.append({
                    "conversation_id": cid,
                    "title": approved_row.get("title"),
                    "partner": approved_row.get("partner"),
                    "error": str(exc),
                })
                break

        remaining_rows = fetch_conversations(page, auth_header)
        remaining_ids = {row.get("conversation_id") for row in remaining_rows}
        verified_absent = [row for row in deleted if row["conversation_id"] not in remaining_ids]
        verification_failures = [row for row in deleted if row["conversation_id"] in remaining_ids]

        unread_after = unread_before
        if counter_url:
            result = page.evaluate("""async ({url,auth}) => {
              const r = await fetch(url, {credentials:'include', cache:'no-store', headers:{accept:'application/json', authorization:auth}});
              return {status:r.status, text:await r.text()};
            }""", {"url": counter_url, "auth": auth_header})
            if result["status"] == 200:
                unread_after = json.loads(result["text"]).get("unread")
        page.close()

    output = {
        "dry_run": False,
        **preflight,
        "deleted": len(deleted),
        "verified_absent": len(verified_absent),
        "verification_failures": verification_failures,
        "changed_and_skipped": changed,
        "failed": failed,
        "unread_after": unread_after,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not failed and not verification_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
