#!/usr/bin/env python3
"""Validate the minimum invariants of a Leboncoin item manifest."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

ALLOWED_STATUS = {"intake", "blocked", "ready_to_publish", "submitted", "verified", "changes_requested"}
ALLOWED_CONFIDENCE = {"unknown", "low", "medium", "high", "very_high"}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


COMPS_MAX_AGE_DAYS = 14
MIN_COMPS = 3
HANDOFF_PROMISES = [re.compile(p, re.I) for p in (
    r"r[ée]initialis", r"param[èe]tres d.usine", r"r[ée]glages d.usine", r"remise? à z[ée]ro", r"mise à z[ée]ro",
    r"\breset\b", r"dissoci", r"retir[ée]+ (de|du) (mon )?compte", r"retrait du compte", r"supprim[ée]+ (de|du) (mon )?compte",
    r"avant (la )?remise", r"test[ée]+ (à|a) la remise", r"rebranch", r"r[ée]aliment",
)]


def validate_pricing(data: dict) -> list[str]:
    """A publishable price must be grounded in a fresh Leboncoin comparable search."""
    errors: list[str] = []
    pricing = data.get("pricing")
    if not isinstance(pricing, dict):
        return ["pricing block is required when status=ready_to_publish (run scripts/lbc_comps.py)"]
    comps = pricing.get("lbc_comps") or {}
    listing = data.get("listing") or {}
    searched_at = comps.get("searched_at") or ""
    if not searched_at:
        fail(errors, "pricing.lbc_comps.searched_at is required: run scripts/lbc_comps.py before pricing")
    else:
        try:
            ts = datetime.fromisoformat(searched_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - ts > timedelta(days=COMPS_MAX_AGE_DAYS):
                fail(errors, f"pricing.lbc_comps is older than {COMPS_MAX_AGE_DAYS} days; rerun the search")
        except ValueError:
            fail(errors, "pricing.lbc_comps.searched_at is not ISO-8601")
    if not comps.get("queries"):
        fail(errors, "pricing.lbc_comps.queries must list the searches actually run")
    n = comps.get("n") or 0
    if n < MIN_COMPS and not (pricing.get("no_comps_reason") or "").strip():
        fail(errors, f"only {n} Leboncoin comps; broaden to equivalent products or set pricing.no_comps_reason")
    if n >= MIN_COMPS and comps.get("median") is None:
        fail(errors, "pricing.lbc_comps.median is required when comps exist")
    if not (pricing.get("rationale") or "").strip():
        fail(errors, "pricing.rationale is required (price vs comps median/p75, condition, accessories, age)")
    price, floor, p75 = listing.get("price_eur"), listing.get("floor_eur"), comps.get("p75")
    if isinstance(price, (int, float)) and isinstance(floor, (int, float)) and floor > price:
        fail(errors, "listing.floor_eur must not exceed listing.price_eur")
    if (
        n >= 5 and isinstance(price, (int, float)) and isinstance(p75, (int, float))
        and price > p75 and not (pricing.get("above_p75_justification") or "").strip()
    ):
        fail(errors, f"price {price} EUR is above comps p75 {p75} EUR; lower it or set pricing.above_p75_justification")
    return errors


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        fail(errors, "schema_version must be 1")
    item = data.get("item") or {}
    listing = data.get("listing") or {}
    workflow = data.get("workflow") or {}
    identification = data.get("identification") or {}
    publication = data.get("publication") or {}
    tests = data.get("tests") or {}

    if not item.get("slug"):
        fail(errors, "item.slug is required")
    if not item.get("title"):
        fail(errors, "item.title is required")
    if not isinstance(item.get("photo_paths", []), list):
        fail(errors, "item.photo_paths must be a list")
    if identification.get("confidence") not in ALLOWED_CONFIDENCE:
        fail(errors, "identification.confidence is invalid")
    status = workflow.get("status")
    if status not in ALLOWED_STATUS:
        fail(errors, "workflow.status is invalid")

    if status in {"ready_to_publish", "submitted", "verified"}:
        if tests.get("blocked_reason"):
            fail(errors, f"tests.blocked_reason must be empty when status={status}")
        for key in ("category", "title", "body", "price_eur", "floor_eur"):
            if listing.get(key) in (None, ""):
                fail(errors, f"listing.{key} is required when status={status}")
        paths = item.get("photo_paths") or []
        missing = [p for p in paths if not Path(p).is_file()]
        if missing:
            fail(errors, f"missing photo files: {missing}")
        if listing.get("photo_order") and set(listing["photo_order"]) != set(paths):
            fail(errors, "listing.photo_order must contain exactly item.photo_paths")

    if status == "ready_to_publish":
        errors.extend(validate_pricing(data))

    # Standing rule: never promise seller-side handoff work (reset, account removal, re-powering).
    body = listing.get("body") or ""
    for rx in HANDOFF_PROMISES:
        m = rx.search(body)
        if m:
            fail(errors, f"listing.body promises seller handoff work ({m.group(0)!r}); the seller does not do reset/account removal/re-powering — remove it")

    if status in {"submitted", "verified"}:
        if not publication.get("listing_id"):
            fail(errors, "publication.listing_id is required")
        url = publication.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in {"www.leboncoin.fr", "leboncoin.fr"}:
            fail(errors, "publication.url must be an https Leboncoin URL")
        if not publication.get("submitted_at"):
            fail(errors, "publication.submitted_at is required")

    if status == "verified" and not (data.get("verification") or {}).get("verified_at"):
        fail(errors, "verification.verified_at is required when verified")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print(f"VALID: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
