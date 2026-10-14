#!/usr/bin/env python3
"""Optional Hermes Agent integration: create one manifest and an intake -> publisher -> verifier
Kanban task graph (requires the `hermes` CLI with the kanban feature).

Configuration (environment):
  LBC_KANBAN_BOARD        board name (default "leboncoin")
  LBC_INTAKE_PROFILES     comma-separated intake worker profiles (default "intake-1,intake-2,intake-3")
  LBC_PUBLISHER_PROFILE   publisher profile (default "publisher")
  LBC_VERIFIER_PROFILE    verifier profile (default "verifier")
  LBC_EXPERT_PROFILE      profile used with --expert (default "expert")
  LBC_MODEL / LBC_PROVIDER                 model/provider for routine tasks (omitted when unset)
  LBC_EXPERT_MODEL / LBC_EXPERT_PROVIDER   model/provider for --expert intake (omitted when unset)
  LBC_NOTIFY_PLATFORM     notification platform for coordinator wake-ups (default "telegram")
  LBC_NOTIFY_CHAT_ID / LBC_NOTIFY_THREAD_ID / LBC_NOTIFY_USER_ID
                          where intake blockers and verification results are delivered;
                          subscription is skipped when LBC_NOTIFY_CHAT_ID is unset.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
import string
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from lbc_config import LBC_HOME, REPO_ROOT  # noqa: E402

ROOT = LBC_HOME
BOARD = os.environ.get("LBC_KANBAN_BOARD", "leboncoin")
INTAKE_PROFILES = tuple(
    p.strip() for p in os.environ.get("LBC_INTAKE_PROFILES", "intake-1,intake-2,intake-3").split(",") if p.strip()
)
PUBLISHER_PROFILE = os.environ.get("LBC_PUBLISHER_PROFILE", "publisher")
VERIFIER_PROFILE = os.environ.get("LBC_VERIFIER_PROFILE", "verifier")
EXPERT_PROFILE = os.environ.get("LBC_EXPERT_PROFILE", "expert")
MODEL = os.environ.get("LBC_MODEL", "")
PROVIDER = os.environ.get("LBC_PROVIDER", "")
EXPERT_MODEL = os.environ.get("LBC_EXPERT_MODEL", "")
EXPERT_PROVIDER = os.environ.get("LBC_EXPERT_PROVIDER", "")
NOTIFY_PLATFORM = os.environ.get("LBC_NOTIFY_PLATFORM", "telegram")
NOTIFY_CHAT_ID = os.environ.get("LBC_NOTIFY_CHAT_ID", "")
NOTIFY_THREAD_ID = os.environ.get("LBC_NOTIFY_THREAD_ID", "")
NOTIFY_USER_ID = os.environ.get("LBC_NOTIFY_USER_ID", "")


def run_json(args: list[str]) -> dict:
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stdout}\n{result.stderr}")
    text = result.stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"expected JSON from {' '.join(args)}; got:\n{text}") from exc


def task_id(payload: dict) -> str:
    for key in ("id", "task_id"):
        if payload.get(key):
            return str(payload[key])
    task = payload.get("task")
    if isinstance(task, dict) and task.get("id"):
        return str(task["id"])
    raise RuntimeError(f"task id missing from response: {payload}")


def create_task(
    *, title: str, body: str, assignee: str, key: str, parent: str | None = None,
    model: str = MODEL, provider: str = PROVIDER,
) -> str:
    cmd = [
        "hermes", "kanban", "--board", BOARD, "create", title,
        "--body", body,
        "--assignee", assignee,
        "--workspace", f"dir:{ROOT}",
        "--idempotency-key", key,
        "--max-runtime", "30m",
        "--skill", "leboncoin-management",
        "--initial-status", "blocked",
        "--json",
    ]
    if model:
        cmd.extend(["--model", model])
    if provider:
        cmd.extend(["--provider", provider])
    if parent:
        cmd.extend(["--parent", parent])
    return task_id(run_json(cmd))


def subscribe_coordinator(task: str) -> None:
    if not NOTIFY_CHAT_ID:
        return  # no alert channel configured
    cmd = [
        "hermes", "kanban", "--board", BOARD, "notify-subscribe", task,
        "--platform", NOTIFY_PLATFORM,
        "--chat-id", NOTIFY_CHAT_ID,
    ]
    if NOTIFY_THREAD_ID:
        cmd.extend(["--thread-id", NOTIFY_THREAD_ID, "--chat-type", "thread", "--parent-chat-id", NOTIFY_CHAT_ID])
    if NOTIFY_USER_ID:
        cmd.extend(["--user-id", NOTIFY_USER_ID])
    cmd.extend(["--notifier-profile", "default", "--delivery-mode", "wake"])
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"failed to subscribe coordinator to {task}: {result.stderr or result.stdout}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--photo", action="append", default=[])
    parser.add_argument("--blocked", default="", help="critical gate; leaves intake blocked")
    parser.add_argument("--expert", action="store_true", help="route intake to the expert profile/model")
    args = parser.parse_args()

    slug = args.slug.strip().lower()
    if not slug or any(c not in string.ascii_lowercase + string.digits + "-" for c in slug):
        parser.error("--slug must be lowercase kebab-case")

    item_dir = ROOT / "items" / slug
    item_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = item_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = json.loads((REPO_ROOT / "templates" / "listing-manifest.json").read_text())
    manifest["item"].update({
        "slug": slug,
        "title": args.title,
        "source": args.source,
        "photo_paths": args.photo,
    })
    index = int(hashlib.sha256(slug.encode()).hexdigest(), 16) % len(INTAKE_PROFILES)
    intake_profile = EXPERT_PROFILE if args.expert else INTAKE_PROFILES[index]
    manifest["workflow"]["intake_profile"] = intake_profile
    manifest["workflow"]["status"] = "blocked" if args.blocked else "intake"
    manifest["tests"]["blocked_reason"] = args.blocked
    manifest.setdefault("metadata", {})["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    intake_body = f"""Process exactly one physical item. Canonical manifest: {manifest_path}
Source: {args.source}
Photos: {args.photo}
Critical gate at enqueue: {args.blocked or 'none'}
Inspect, identify, and recover purchase evidence when useful.

PRICING IS MANDATORY BEFORE PROPOSING A PRICE:
1. Run the Leboncoin comparable search (read-only, under the browser lock):
   python3 scripts/with_browser_lock.py --timeout 600 -- python3 scripts/lbc_comps.py --query "<brand model>" [--query "<equivalent wording>"] --include "<regex for the same product>" --exclude "<variants, lots, parts, accessories-only>" --out items/{slug}/comps.json
2. Same model first; if fewer than 3 comps, broaden to equivalent products (same class, age and capability) and say so.
3. Results are asking prices, not sale prices. Ads unsold after 30+ days at a price show that price does not clear.
4. Default target: around the comps median; floor near p25 or the stale-30d median. Exceed p75 only with a concrete, verifiable reason (new/sealed, extra accessories, rare), recorded in pricing.above_p75_justification.
5. Fill manifest.pricing (lbc_comps summary + file path, new_price_eur if known, rationale). Purchase or new price alone never sets the price.

Then prepare/redact photos and update the manifest. Run scripts/validate_manifest.py; it rejects ready_to_publish without fresh comps. Never publish. Complete only when ready_to_publish; otherwise block with one exact gate."""
    intake_id = create_task(
        title=f"Intake — {args.title}", body=intake_body, assignee=intake_profile,
        key=f"lbc:{slug}:intake",
        model=EXPERT_MODEL if args.expert else MODEL,
        provider=EXPERT_PROVIDER if args.expert else PROVIDER,
    )

    publish_body = f"""Publish exactly the item in {manifest_path}. Require workflow.status=ready_to_publish and a valid manifest. Acquire the shared browser lock for the entire mutation. Never buy a boost. Leboncoin auto-generates a description (and may predict a price) after photos/category are set, and can overwrite the body AFTER you typed it: set textarea[name=body] LAST via keyboard events (Ctrl+A, press_sequentially, Tab), re-read it and assert it equals manifest listing.body exactly (and price/title) immediately before the first commit (Continuer); also assert shipping on/off equals manifest listing.shipping and the brand attribute matches the item (autofill has enabled Mondial Relay and set a wrong brand); when shipping is on, open « Modifier les transporteurs » and keep ONLY Shop2Shop by Chronopost + Colissimo checked (Mondial Relay OFF, the default carrier policy), click Valider in that dialog; abort if anything differs. After acceptance, record listing ID, URL and submitted_at, set status=submitted, then complete. A confirmation page is not verification."""
    publish_id = create_task(
        title=f"Publish — {args.title}", body=publish_body, assignee=PUBLISHER_PROFILE,
        key=f"lbc:{slug}:publish", parent=intake_id,
    )

    verify_body = f"""Independently verify the fresh dashboard and public listing against {manifest_path}. Check title, price, body, condition, photo count/order, shipping, status and URL. Never mutate. Set status=verified only on exact match; otherwise request changes with every mismatch."""
    verify_id = create_task(
        title=f"Verify — {args.title}", body=verify_body, assignee=VERIFIER_PROFILE,
        key=f"lbc:{slug}:verify", parent=publish_id,
    )
    subscribe_coordinator(intake_id)
    subscribe_coordinator(verify_id)

    # Child tasks were created blocked to prevent a dispatcher race while the graph was incomplete.
    # Parent gating is now established, so children can move to todo and the intake can start unless
    # a real human/test gate was supplied.
    def unblock_if_needed(task: str) -> None:
        result = subprocess.run(
            ["hermes", "kanban", "--board", BOARD, "unblock", task],
            text=True, capture_output=True,
        )
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if result.returncode and "not blocked" not in combined:
            raise RuntimeError(f"failed to unblock {task}: {combined.strip()}")

    for child in (publish_id, verify_id):
        unblock_if_needed(child)
    if not args.blocked:
        unblock_if_needed(intake_id)

    print(json.dumps({
        "manifest": str(manifest_path),
        "intake_profile": intake_profile,
        "tasks": {"intake": intake_id, "publisher": publish_id, "verifier": verify_id},
        "status": "blocked" if args.blocked else "ready",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
