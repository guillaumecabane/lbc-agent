# lbc-agent

A Playwright-over-CDP toolkit plus agent skills for running a [Leboncoin](https://www.leboncoin.fr) (French classifieds) **seller account** with an LLM agent such as Claude Code or Hermes Agent.

The scripts drive a real, persistent, already-logged-in Chrome through the Chrome DevTools Protocol. They read the seller dashboard and inbox, search comparable listings for pricing, and perform carefully guarded writes (edit, re-photo, carriers, pause/reactivate/delete, offers, messages). The `skills/` folder contains the operating knowledge an agent needs to use them safely: DataDome pitfalls, dashboard API pagination, offer flows, the two-step free edit commit, and more.

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by Leboncoin. It automates a browser you control on an account you own. Use it at your own risk and respect [Leboncoin's terms of service](https://www.leboncoin.fr/dc/cgu). Automated access may lead to captchas, rate limits, or account restrictions.

## Architecture

```text
          operator (chat)
               │  approvals, decisions
               ▼
        LLM agent + skills/ ───────────────┐
               │                           │ wakes on change
               ▼                           │
 scripts/with_browser_lock.py  ◄──── watcher/leboncoin_event_signal.py (cron, read-only)
   (one writer at a time)          watcher/leboncoin_weekly_collect.py (weekly audit, read-only)
               │
               ▼
 persistent logged-in Chrome  ──CDP──  $LBC_CDP_URL
 (dedicated profile, optional residential egress)
```

- **Persistent logged-in Chrome over CDP.** You log in once by hand in a dedicated profile; scripts attach with `connect_over_cdp`, open a fresh tab, and close it in `finally`. Cookies and the short-lived `Authorization` header are used in-process only and never printed or stored.
- **Single browser lock.** `scripts/with_browser_lock.py` serialises every browser command with an `flock` lease (exit code `75` on timeout) and sweeps leaked tabs afterwards. Never run two writers against the same account.
- **Read-only watcher + agent alerting.** `watcher/leboncoin_event_watch.py` diffs the full dashboard and all conversation summaries against a local state file and prints Markdown only for new incoming events. `leboncoin_event_signal.py` makes that output "sticky" so a scheduler in monitor mode wakes the agent only when something actually changed. The agent prompt template is `watcher/leboncoin_watcher_prompt.md`.
- **Weekly audit.** `watcher/leboncoin_weekly_collect.py` collects the complete catalogue (all dashboard offsets), per-ad stats with week-over-week deltas, and recent/unread conversations as one JSON document for a reporting agent.
- **Human-approved writes.** Every write script is a dry run unless `--commit` is passed (exceptions are listed below). The agent presents the exact batch, the operator approves, the agent commits and then re-reads the live state before claiming success.
- **Comps-first pricing.** `scripts/lbc_comps.py` captures Leboncoin's own search results for comparable listings and reports p25/median/p75 and the median of stale (30+ day) ads. `scripts/validate_manifest.py` refuses a `ready_to_publish` manifest without a fresh comps block.

## Safety principles

- **Never automate CAPTCHA, DataDome challenges or 2FA.** Scripts detect challenges structurally and stop. A human solves them in the headed browser.
- **Never buy boosts or paid options.** Edits only complete through « Modifier sans booster mon annonce »; if that free action is missing the script aborts.
- **Read-only by default.** Probes, audits and the watcher only issue GETs (plus the dashboard search POST the page itself makes) and never mark messages as read.
- **The only pre-authorized write is pausing a single-item ad after a confirmed payment**, to prevent double-selling. Everything else waits for explicit approval.
- **Assert before commit.** Write scripts check the expected title before touching anything, assert that unrelated fields (title/body/price) are unchanged, and verify the result from a fresh dashboard read.
- **Low browsing volume.** Heavy polling triggers DataDome. Keep the watcher at 15 minutes or slower and avoid redundant searches.

## Setup

Requirements: Linux or macOS, Python 3.10+, Google Chrome/Chromium, a Leboncoin account.

```bash
git clone https://github.com/guillaumecabane/lbc-agent.git && cd lbc-agent
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt        # Playwright only needs its Python package: we attach to your Chrome
cp .env.example .env                   # then edit; export it in your shell or service unit
```

Start a dedicated Chrome profile with remote debugging bound to localhost and log in to Leboncoin manually once:

```bash
google-chrome --user-data-dir="$LBC_CHROME_PROFILE" --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 https://www.leboncoin.fr/compte/part/mes-annonces
curl -fsS http://127.0.0.1:9222/json/version   # must answer
```

On a server, run Chrome headed inside a virtual display (Xvfb) under a service manager with automatic restart, and keep a remote viewer (VNC over a private tunnel) available for the rare manual CAPTCHA. Never expose the CDP port publicly: it grants full control of the logged-in session. If datacenter IPs get blocked, route the browser through a residential connection (`--proxy-server=...`) and set `LBC_PROXY`/`LBC_EXPECTED_EGRESS` so the weekly collector can check it.

Quick checks (offline / read-only):

```bash
python3 scripts/lbc_config.py                                  # print resolved configuration
python3 scripts/validate_manifest.py items/<slug>/manifest.json   # the blank template reports INVALID by design
python3 watcher/test_leboncoin_event_watch.py                  # unit tests, no network
python3 scripts/with_browser_lock.py -- python3 scripts/lbc_captcha_probe.py
```

Install the skills into your agent (e.g. copy or symlink `skills/*` into the agent's skills directory) and schedule the watcher:

```bash
# every 15 minutes, in a scheduler mode that wakes the agent only when stdout changes
python3 watcher/leboncoin_event_signal.py
python3 watcher/leboncoin_event_watch.py --baseline           # first run: save state without alerts
```

## Configuration

All configuration is via environment variables (see `.env.example` and `scripts/lbc_config.py`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `LBC_CDP_URL` | `http://127.0.0.1:9222` | CDP endpoint of the logged-in Chrome |
| `LBC_HOME` | repository root | Working directory containing `items/`, `state/`, `tmp/` |
| `LBC_STATE_DIR` | `$LBC_HOME/state` | Watcher/audit state (0600 files) and the browser lock |
| `LBC_TMP` | `$LBC_HOME/tmp` | Screenshots, downloaded photos, batch logs |
| `LBC_BROWSER_LOCK` | `$LBC_STATE_DIR/browser.lock` | Lock file used by `with_browser_lock.py` |
| `LBC_CHROME_PROFILE` | – (documentation only) | Chrome `--user-data-dir` for the dedicated profile |
| `LBC_PROXY` | unset | Proxy the browser egresses through; enables the weekly egress check |
| `LBC_EXPECTED_EGRESS` | unset | Public IP the proxy must report, otherwise the weekly collector fails |
| `LBC_TZ` | `Europe/Paris` | Time zone for weekly report dates |
| `LBC_KEEP_TABS` | unset | `1` = do not close extra tabs after a locked command (manual CAPTCHA handoff) |
| `PYTHON` | `python3` | Interpreter used by the shell wrappers |

The optional Hermes Kanban integration (`integrations/hermes/enqueue_listing.py`) reads `LBC_KANBAN_BOARD`, `LBC_INTAKE_PROFILES`, `LBC_PUBLISHER_PROFILE`, `LBC_VERIFIER_PROFILE`, `LBC_EXPERT_PROFILE`, `LBC_MODEL`, `LBC_PROVIDER`, `LBC_EXPERT_MODEL`, `LBC_EXPERT_PROVIDER`, `LBC_NOTIFY_PLATFORM`, `LBC_NOTIFY_CHAT_ID`, `LBC_NOTIFY_THREAD_ID`, `LBC_NOTIFY_USER_ID`.

## Script catalogue

Run browser scripts from the repository root under the lock: `python3 scripts/with_browser_lock.py --timeout 600 -- python3 scripts/<script> ...`.
Mode: **R** read-only · **W** write, dry run unless `--commit` · **W!** write without a dry-run mode.

| Script | Mode | Purpose |
| --- | --- | --- |
| `scripts/lbc_config.py` | – | Shared environment-driven configuration |
| `scripts/with_browser_lock.py` | – | Run one command under the exclusive browser lock; sweep leaked tabs |
| `scripts/validate_manifest.py` | – | Offline manifest invariants: status gates, comps freshness, no handoff promises |
| `scripts/lbc_comps.py` | R | Comparable-listing search with price statistics |
| `scripts/lbc_ad_snapshot.py` | R | Full dashboard record (all offsets) + photo download for given ads |
| `scripts/lbc_ad_status.py` | R | Public page state + dashboard status of one ad |
| `scripts/lbc_dashboard_ad.py` | R | Subject/price/status/body of ads from the dashboard API |
| `scripts/lbc_dashboard_photos.py` | R | Download the photos actually online for given ads |
| `scripts/lbc_scan_bodies.py` | R | Scan every live ad body for banned wording / handoff promises |
| `scripts/lbc_ad_convs.py` | R | Print buyer conversations for given ads (passive capture) |
| `scripts/lbc_conv_probe.py` | R | List buttons and recent text of a conversation |
| `scripts/lbc_conv_shot.py` | R | Screenshot a conversation and download image attachments |
| `scripts/lbc_captcha_probe.py` | R | Report whether a DataDome challenge is shown |
| `scripts/lbc_edit_shot.py` | R | Screenshot edit and public pages of an ad |
| `scripts/lbc_photo_probe.py` | R | Inspect the photo section of the edit page |
| `scripts/lbc_shipping_probe.py` | R | Dump the delivery section of the edit page |
| `scripts/lbc_carrier_probe.py` | R | Open the carrier dialog and dump it (never submits) |
| `scripts/lbc_open_for_manual.py` | R | Open the dashboard in a foreground tab for manual CAPTCHA solving |
| `scripts/lbc_close_tabs.py` | W | Close all CDP tabs but one (local browser only) |
| `scripts/lbc_edit_listing.py` | W | Free edit: title/body/price, append photos |
| `scripts/lbc_weekly_apply_edits.py` | W | Apply a JSON batch of approved title/body/brand fixes |
| `scripts/lbc_replace_photos.py` | W | Replace all photos of an ad, in order |
| `scripts/lbc_set_carriers.py` | W | Enforce the carrier policy (Shop2Shop + Colissimo, no Mondial Relay) |
| `scripts/lbc_carriers_batch.sh` | W! | Run `lbc_set_carriers.py --commit` for every id in a file, spaced out |
| `scripts/lbc_disable_shipping.py` | W | Turn shipping off (hand delivery only) |
| `scripts/lbc_pause_ad.py` | W | Pause an ad from the dashboard and verify |
| `scripts/lbc_reactivate_ad.py` | W | Reactivate a paused ad (refuses anything that looks paid) |
| `scripts/lbc_delete_ad.py` | W | Delete an ad with the correct reason step |
| `scripts/lbc_delete_favorite_only_conversations.py` | W | Delete pre-audited "toujours disponible ?"-only conversations |
| `scripts/lbc_send.py` | W | Send a message and/or a formal offer in a conversation |
| `scripts/lbc_send_message.py` | W! | Send one exact message and verify it appears |
| `scripts/lbc_send_offer.py` | W! | Send a message plus a formal seller offer (refusing a pending offer first) |
| `scripts/lbc_accept_offer.py` | W | Accept a pending incoming offer and verify |
| `scripts/lbc_counter.py` | W | Refuse a pending offer, then send a counter-offer |
| `watcher/leboncoin_event_watch.py` (+ `.sh`) | R | Diff dashboard + inbox, print new events as Markdown |
| `watcher/leboncoin_event_signal.py` | R | Sticky change signal for a monitor-mode scheduler |
| `watcher/leboncoin_weekly_collect.py` (+ `.sh`) | R | Weekly catalogue/inbox audit as JSON |
| `watcher/test_leboncoin_event_watch.py` | – | Unit tests for the watcher diff logic |
| `watcher/leboncoin_watcher_prompt.md` | – | French prompt template for the alerting agent |
| `integrations/hermes/enqueue_listing.py` | – | Optional: manifest + intake → publisher → verifier Kanban graph |
| `skills/leboncoin-management/scripts/mask_personal_info.py` | – | Mask personal info in photos with OpenCV seamless clone |

Per-item work lives in `items/<slug>/manifest.json` (git-ignored), created from `templates/listing-manifest.json`.

## Skills

| Skill | Use |
| --- | --- |
| `skills/leboncoin-management` | Main operating manual: session, audits, messages, offers, edits, carriers, copy style, monitoring |
| `skills/leboncoin-offer-negotiation` | Handling buyer offers against comps and the floor |
| `skills/leboncoin-multicomponent-listing-photos` | Avoiding photo mix-ups on kits and bundles |
| `skills/leboncoin-purchase-history-recovery` | Recovering purchase evidence from email archives |

The skills use the `SKILL.md` format (YAML front matter + Markdown) understood by Claude Code and Hermes Agent; other agents can simply read them as documentation. Buyer-facing text and the watcher prompt are in French on purpose; French UI labels quoted in the scripts (« Faire une offre », « Modifier sans booster mon annonce », …) are functional selectors and must stay verbatim.

## Limitations

- Leboncoin changes its front end regularly; selectors and internal API shapes here were valid when written and will drift.
- Linux/macOS only (`fcntl` lock).
- No tests touch Leboncoin; only the watcher diff logic is unit-tested.

## License

MIT — see [LICENSE](LICENSE).
