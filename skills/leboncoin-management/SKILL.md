---
name: leboncoin-management
description: "Use when managing a Leboncoin seller account's listings and messages."
version: 1.0.0
metadata:
  hermes:
    tags: [leboncoin, classifieds, listings, messages, pricing]
---

# Leboncoin management

All paths below are relative to the toolkit root (`$LBC_HOME`, by default the repository root). Every browser-touching script connects to the logged-in Chrome at `$LBC_CDP_URL`; writes run under `scripts/with_browser_lock.py`.

## Session and network

- Reuse a dedicated persistent Chrome profile (`$LBC_CHROME_PROFILE`) exposed through CDP at `$LBC_CDP_URL` (default `http://127.0.0.1:9222`).
- Supervise Chrome with a service manager (e.g. a systemd unit with `Restart=always`, ordered after the virtual display and any proxy). Before a scheduled retry, verify both that the service is active and `curl -fsS "$LBC_CDP_URL/json/version"`; do not rely on a manually launched browser process.
- If datacenter IPs get blocked, route the browser through a residential connection (optional `LBC_PROXY`, checked by the weekly collector against `LBC_EXPECTED_EGRESS`); verify egress before login.
- The private target is `https://www.leboncoin.fr/compte/part/mes-annonces`.
- Never automate DataDome/CAPTCHA or email 2FA. Retrieve an email code only when the live page requests it.
- Do not infer a manual DataDome checkpoint from one stale tab showing `ERR_BLOCKED_BY_RESPONSE` or merely from an `x-datadome: protected` response header. Under the browser lock, probe `/deposer-une-annonce` in a fresh tab and require both HTTP 200 and the real title field. If the real form returns after a short cooldown, retry the publisher without involving the operator; ask for manual recovery only when a visible challenge or persistent blocked response remains.
- Manual CAPTCHA handoff: expose the headed browser only temporarily through an authenticated remote viewer (e.g. VNC behind a private tunnel), open the dashboard with `scripts/lbc_open_for_manual.py` (run with `LBC_KEEP_TABS=1` under the lock), let the operator solve it, then remove the exposure, confirm with `scripts/lbc_captcha_probe.py`, and resume the watcher.
- Close tabs. Chrome RAM is limited: every script must `page.close()` in `finally`, and `scripts/with_browser_lock.py` sweeps all page targets except one Leboncoin tab after each command, even on crash (`scripts/lbc_close_tabs.py [--commit]` does it on demand). Never leave probe/manual tabs open.
- Browsing volume triggers DataDome: a day of 10-minute watcher runs plus many coordinator rereads/sends caused a persistent slider and then HTTP 403. Run the watcher every 15 minutes or slower; batch rereads, avoid redundant comps searches (do not let intake workers re-run comps the coordinator already did), and pause the watcher on the first checkpoint instead of letting it fail repeatedly. A comps search in the task body using `--out items/<slug>/comps.json` flags it as done; intake workers must omit the `--out` flag if the coordinator already populated that file.
- Detect captchas structurally (DataDome iframe `captcha-delivery.com`, `#ddChallengeContainer`), never by body-text regex. A `/captcha|robot|vérif/` text test false-positived on the seller's own listing titles (« … pour robot … », « Vérifiez la compatibilité ») and failed the weekly audit twice as a phantom "CAPTCHA".

## Read-only inventory audit

Capture the page's own dashboard request instead of scraping text when possible:

- Endpoint: `POST https://api.leboncoin.fr/api/dashboard/v1/search`.
- The initial dashboard request is capped at 30 ads (`limit: 30`, `offset: 0`) even when `total` is higher. A complete catalogue audit must replay the captured authenticated request from the page at offsets `30, 60, ...`, merge by `list_id`, and assert `len(unique_ads) == total`; otherwise fail the audit rather than analyze partial inventory. `watcher/leboncoin_weekly_collect.py` implements this and reports `dashboard_pages`, `dashboard_ads_collected`, and `catalogue_complete`.
- Reuse the request payload observed from the live authenticated page; do not hardcode the user ID.
- Useful response fields: `total`, `account_stats`, and per-ad `list_id`, `subject`, `price`, `category_name`, `first_publication_date`, `status`, `stats`, `images`, `body`, `attributes`, `url`.
- Treat `stats.Views`, `stats.Favorites`, and `stats.Messages` as Leboncoin dashboard counters, not completed sales.
- Compare ads by age-normalized views/day as well as lifetime totals; old inventory otherwise dominates the ranking.
- Derive active inventory from each ad's `status`, not the page label or `total`: the dashboard can count a paused ad under “En ligne” and disagree with `account_stats.active_ads`.
- Do not treat `index_date` as a reliable edit timestamp. Persist each run's metrics, selected IDs, and exclusion reasons in `$LBC_STATE_DIR/rotation-history.json` so later runs can compute deltas and rotate fairly.

For live market comps, run `scripts/lbc_comps.py` under the browser lock. It loads `https://www.leboncoin.fr/recherche?text=...` in the shared authenticated Chrome and passively captures the page's own `finder/search` responses; replaying `finder/search` directly can hit DataDome. Filter with `--include`/`--exclude` regexes so variants (Max/Pro/Advanced…), lots, parts-only listings and your own ads (`--exclude-id`) drop out. The script reports n, p25, median, p75 and the median of ads online 30+ days. Asking prices are not sale prices; label them accordingly.

Pricing is comps-first and mandatory for every new listing and every repricing: target roughly the comps median, floor near p25 or the stale-30d median, and exceed p75 only with a verifiable reason. Purchase price, new retail price and web prices are context, never the price basis. `scripts/validate_manifest.py` enforces this through the manifest `pricing` block.

Run read-only audit/extraction code as a script file under `$LBC_TMP` (`python3 /path/script.py`), never as `python3 - <<EOF`, `python3 -c`, `node -e`, or `... | python3 -c`. Agent harnesses with command approval often flag heredoc and `-c`/`-e` inline execution and can hold a read-only audit until timeout. If an approval prompt is genuinely unavoidable (a real Leboncoin write the operator has not yet approved), state in the chat, before the tool call, what the command does and why.

## Message audit without side effects

- Conversation list: `GET https://api.leboncoin.fr/api/messaging-items-api/v3/conversations`. Follow `metadata.next_page_hash` with the `page_hash` query parameter until absent; the first page is only 50 conversations.
- Unread count: the live messaging counter endpoint ending in `/counter/?withPollingTime=true`.
- Separate buyer-authored messages from `ApiSystemMessage` favorite/availability prompts and `ApiIntegrationMessage` negotiation events.
- Full history is available from the live app's conversation-messages request. It requires the short-lived `Authorization` header already used by the page. Capture and reuse that header only in process memory; never print or save it.
- The UI deep link is `/messages/id/{conversation_id}`. The corresponding read-only history endpoint is `GET https://api.leboncoin.fr/messaging/proxy/api/v1/hal/{current_user}/conversations/{conversation_id}/messages?expanded=true&order=asc&category_id={category_id}`; omit `category_id` for customer-support conversations. Use the category from conversation detail rather than guessing it.
- Prefer passively capturing the page's own responses (`page.on('response')` on `/messages` and `/messages/id/{id}`) over replaying API calls: a replayed GET to `messaging-items-api/v3/conversations` (via `context.request` or in-page `fetch` with the captured header) returned a DataDome 403 captcha URL while the page's own identical request succeeded. The `/messages` page load already returns the first 50 conversations.
- Read histories with GET only. Do not call message `read` links, send endpoints, block, archive, or delete unless the operator explicitly approves.
- For inbox cleanup, delete only conversations whose fresh full history contains exactly one incoming `ApiSystemMessage` with « Votre bien est toujours disponible ? Faites-le lui savoir. », no attachment, no outgoing message, no integration event, and no human message. Audit all candidates via authenticated GET without changing the unread counter, present the exact batch, then use `scripts/lbc_delete_favorite_only_conversations.py <audit.json> --commit` under the browser lock. The script revalidates every history immediately before deletion and verifies every conversation is absent afterward; a changed conversation is skipped. Never delete genuine buyer messages, offers, transactions, or replied threads.
- Verify the unread counter before and after an audit; reading via direct GET should not change it.
- For buyer replies, the standard line is "paiement via Leboncoin" (secure payment), not "envoi via Leboncoin": the emphasis is on the payment channel. Mention shipping only when relevant; offer local handoff only for material that cannot reasonably be shipped. This is a content preference, not blanket authorization to send: outbound replies still require the operator's approval.

## Weekly reporting

- The account owner may be both seller AND buyer on the same account. Every conversation in the collector output has `side`: `buyer` means the partner owns the ad (`item.owner_id` ∈ partner ids) and any « offre » there is the owner's OWN offer. Never report buyer-side threads as incoming interest or recommend replying to them; list them only under « Mes achats » if they need the owner's action.
- Deliver the weekly audit only to the dedicated Leboncoin alert channel (`<your-alert-channel>`, e.g. one Telegram topic for all Leboncoin buying/selling). When run/rerun from another chat, do not paste or summarise the report there; just say it was delivered to the alert channel.
- Use the object's human-readable listing title as the heading and identifier in reports; do not make the operator decode Leboncoin IDs.

## Listing intake

When the operator sends one item per message with a brief description and photos, take ownership of the rest: inspect the photos, identify the exact product cautiously, run the mandatory Leboncoin comps search before choosing a price and negotiation floor, and draft a polished Leboncoin title, category, condition, description, shipping/hand-off terms, and photo order. Retrieve purchase details or proof from available sources when useful instead of asking. Ask only for facts that cannot be verified or safely inferred, such as functional defects, missing accessories, dimensions not visible, or impact history. Never invent a model, condition claim, warranty, test result, or safety fact.

### Photo masking for personal info

When login screens, usernames, avatars, or personal text are visible in photos:
- Use OpenCV `seamlessClone()` for natural blending (not rectangular overlays or simple inpainting). See `scripts/mask_personal_info.py` in this skill for the reference implementation.
- Clone a similar region of the background (e.g., more of the screensaver) into the target box via `cv2.seamlessClone(source, img, mask, center, cv2.NORMAL_CLONE)`.
- Create an elliptical mask (not rectangular) for smooth edges: `cv2.ellipse(mask, center, (width/2 - 2, height/2 - 2), 0, 0, 360, 255, -1)` preserves the natural texture and makes the edit invisible.
- Always verify the result with a 2× zoomed preview; flat or duplicated regions indicate poor clone source alignment or small offsets. Adjust the source offset and box dimensions iteratively until the masked region looks like natural continuation.
- For screenshots with text/UI elements, the background surrounding the text is almost always a usable clone source (sky, water, beach, wallpaper pattern).
- Never let login credentials, full names, or avatars pass through to published photos, even when partially obscured or small.
- For box labels with printed serials: a 50-pixel blur or pixelation is acceptable; you do not need to clone over serials unless they are legible at normal viewing distance.

Once an exact listing is ready, publish it without another approval checkpoint when no critical test, account reset, privacy cleanup, safety issue, or delivery constraint remains. Limit test requests to cases where failure is plausible or materially changes safety/value (powered high-value appliances, networking/account-bound devices, mains equipment, batteries with meaningful uncertainty); do not block ordinary low-risk items such as keyboards or passive adapters on routine testing. If untested, omit any claim that it was tested rather than inventing one. Explicit operator instructions to review first or keep a draft always override this default.

## Seller offers and ad deletion

- Formal counter-offer: in the conversation, button « Faire une offre » opens « Proposer un nouveau prix » (presets -10 % / -20 %, « Autre prix » → `input#price`, then « Proposer »). Result is a system message « Offre envoyée … L'acheteur a 48 heures pour payer. » Script: `scripts/lbc_send.py <conv_id> <title> <msg_file|-> [--offer EUR] --commit`.
- Accept a pending incoming offer with `scripts/lbc_accept_offer.py <conversation_id> <exact_title> <EUR> --commit` under the browser lock, then reread the conversation and require « Vous avez accepté l'offre de … ». Clicking « Accepter N € » commits immediately and may show only the informational dialog « Votre réponse a bien été envoyée. »; do not click or retry after that dialog. Acceptance is not payment: keep the ad active until a fresh paid/order-confirmed event authorizes pausing.
- For a seller-side single-item listing, a freshly verified paid/confirmed purchase (order confirmed, shipping label available, or request to confirm shipment) authorizes immediate automatic pausing to prevent double-selling. A simple offer or interest message does not. Use `scripts/lbc_pause_ad.py <ad_id> <exact_title> --commit` under the browser lock and verify fresh status with `scripts/lbc_ad_status.py <ad_id>`. Keep the listing paused through shipment/receipt; delete only after transaction completion, or reactivate deliberately after cancellation/return.
- After a buyer cancels a transaction (« Votre acheteur a annulé la transaction »), the conversation no longer shows « Faire une offre »: the seller cannot re-send a formal offer there. Do not promise « je vous renvoie l'offre »; ask the buyer to make the offer from the ad and accept it (or lower the ad price).
- A cancelled paid sale leaves the auto-paused ad paused: buyers then cannot buy or offer. Flag reactivation to the operator immediately on the cancellation event (an intercom kit once sat paused 3 days while the buyer was waiting). Reactivate with `scripts/lbc_reactivate_ad.py <ad_id> <exact_title> [--commit]` under the lock (free PUT, verified by the « Mettre en pause » control reappearing).
- While a buyer's offer is pending, only « Accepter N € » / « Refuser l'offre » show — no « Faire une offre ». To counter: refuse, then « Faire une nouvelle offre ». Script: `scripts/lbc_counter.py <conv_id> <title> <EUR> --commit` (or `scripts/lbc_send_offer.py`, which also sends a message first).
- Delete a sold ad from its own page `/vi/{id}.htm`: « Supprimer l’annonce » → confirm dialog showing title+price → « Valider » → reason step « Pourquoi supprimez-vous cette annonce ? » (vendu sur leboncoin / vendu sur une autre plateforme / ne souhaite plus vendre / Autre) → « Valider ». Pick the reason that matches how it actually sold; a sale made outside LBC is « autre plateforme », not « leboncoin ». Script: `scripts/lbc_delete_ad.py <id> <title> [lbc|ailleurs|retrait|autre] --commit` (dry run without `--commit`); verify with `scripts/lbc_ad_status.py <id>`. A Gimii promo overlay (`#gimii-root`) can intercept clicks: remove it from the DOM and use a DOM `click()`. Verify with HTTP 410 « Cette annonce est désactivée » and the « En ligne (N) » count dropping.
- The dashboard's first screen is paginated: `a[href*=id]` missing there does NOT mean the ad is inactive; check the ad page for owner actions (« Modifier l’annonce », « Supprimer l’annonce »).

## Replacing listing photos

- Use `scripts/lbc_replace_photos.py <ad_id> <exact_title> <photo...> [--commit]` under the browser lock: it removes every current photo via the « Retirer la photo numéro N » buttons (DOM click), uploads the new set in order through the edit page's file input, asserts title/body/price unchanged, then commits « Valider les modifications » → « Modifier sans booster mon annonce ». Always dry-run first and check the thumbnail order in the saved screenshot.
- Audit what is actually online with `scripts/lbc_dashboard_photos.py <ad_id...>` (captures the dashboard API `images.urls_large` and downloads them) plus a contact sheet. Do not use photo lists from the public ad page: it also renders other listings' thumbnails.
- An ad with a paid or in-progress transaction cannot be edited: `/annonce/{id}/editer` shows « Votre annonce est en cours de validation, cette action ne peut être effectuée pour le moment ». Fix wrong photos before a sale, or after a cancellation.
- Verify photo-to-title match visually for every multi-component listing (intercoms, kits): a mixed-up photo set on an intercom kit confused three buyers. See the `leboncoin-multicomponent-listing-photos` skill.

## Buyer-facing voice and watcher alerts

- Buyer-facing text (messages and descriptions): always first person singular (« je », « je l'utilise »), never « on »/« nous » — a private seller sells alone and « on » confuses buyers. This includes price justifications, product history, and condition notes: not "on l'utilise", "on a utilisé", or "nous faisons", always "je", "j'utilise", "j'ai utilisé".
- Watcher alerts: silent unless the operator must act or decide; one short message per wake-up (≈ 1-3 lines per event, recommendation + ready-to-send text), no analysis/verification narrative. Prompt template: `watcher/leboncoin_watcher_prompt.md` (fill in `{{LBC_HOME}}` and load it as the scheduler job's prompt).
- Parallel formal offers to several buyers on the same ad are fine: Leboncoin locks the item at the first payment and blocks the others. Do not hold back an offer because another buyer has an open/accepted-unpaid offer; in-person cash deals remain the real double-sale risk.

## Shipping carriers

- Default carrier policy of this toolkit (edit `WANT` in `scripts/lbc_set_carriers.py` to change it): shipped listings offer only **Shop2Shop by Chronopost** and **Colissimo** (La Poste). **Mondial Relay is OFF**; Courrier suivi / Autres moyens are left as they are.
- Edit page: section « Remise du bien » → button `aria-label="Modifier les transporteurs"` (DOM click) opens dialog « Vos moyens de livraison » with one `button[role=checkbox]` per carrier (`aria-checked`) and a « Valider » button; then the usual free two-step commit.
- Script: `scripts/lbc_set_carriers.py <ad_id> [--commit]` under the browser lock (dry run by default, asserts title/body/price unchanged, prints ALREADY OK / SKIP when no shipping). Batch: `scripts/lbc_carriers_batch.sh ad_ids.txt` (one lock per ad, 90 s spacing, stops on CAPTCHA, log in `$LBC_TMP/lbc_carriers_batch.log`).
- New listings: the publish prompt in `integrations/hermes/enqueue_listing.py` enforces the same carrier set before **Continuer**.
- Pitfall: on hand-delivery-only ads the carrier dialog still exists; checking carriers there silently turns shipping ON. `lbc_set_carriers.py` SKIPs ads whose toggle reads « Activer la livraison »; fix such accidents with `scripts/lbc_disable_shipping.py <id> --commit`.
- Bulky items (e.g. a robot vacuum with its base station) can have Colissimo unavailable: run with `--allow-no-colissimo` to keep Shop2Shop only.
- Ads with a pending offer/payment are locked (« en cours de validation »): retry after the transaction.

## Compatibility claims

- Never use Leboncoin's built-in AI description generator: it once invented a wrong compatibility list for a drone remote, the buyer's drone turned out incompatible and the sale had to be reversed at a loss.
- Every compatibility claim (drones, robots, platines/moniteurs, chargers) comes from the manufacturer's official list or a reference printed on the item/box. When unsure, list only what is confirmed and add « Vérifiez la compatibilité avec votre modèle avant achat. »
- Put key compatibility in the title when it is the main purchase criterion (remotes, attachments, batteries).

## Manufacturer photos

Add a manufacturer visual when it helps buyers picture the product (bedding rolled in plastic, items photographed only folded/boxed, products whose use or scale is unclear from the seller's photos).

- Source the official gallery from the exact product page (e.g. a retailer's high-resolution gallery URLs; fetching through a residential connection avoids most retailer captchas). Match the exact model/size/variant.
- Put the cleanest in-use visual as cover, keep the seller's real photos next, and add at most one explanatory visual (layers, dimensions). Skip text-heavy marketing infographics and visuals of other variants.
- Always disclose in the body: « Photos X et Y : visuels du fabricant. » Never let a stock visual stand in for the item's actual condition.
- On the edit page, new photos append at the end (`scripts/lbc_edit_listing.py --add-photo`); reorder with the « Échanger l’ordre des photos numéro N et N-1 » buttons via DOM click (`el.click()`), because a hover overlay intercepts Playwright pointer clicks.

## Listing copy style

- Handle the entire Leboncoin workflow in French: buyer messages, listings, recommendations, reports, and operator-facing summaries, unless the operator explicitly asks for another language.
- Sell the item positively and directly. Do not define it by nearby models it is not (for example, omit “ce n’est pas le modèle Max”) unless confusion would create a safety or compatibility problem.
- State verified facts and known defects, but do not volunteer speculative downsides such as reduced used-battery autonomy when no defect was observed. Keep stronger caveats for real safety, compatibility, account-lock, missing-part, or known-failure risks.
- For local handoff, write only “Remise en main propre” or “Remise en main propre privilégiée.” Never promise or invite an on-site demonstration.
- Write « filetage pour trépied », never « pas de vis (pour) trépied »: buyers read « pas de » as a negation (no tripod screw).
- Avoid URL-shaped merchant names in the description. Write `Amazon`, not `Amazon.fr`, because Leboncoin replaces domain-like text with `[URL masquée pour votre sécurité]`.

## Multi-agent listing pipeline (optional)

For many items, use a task board and the toolkit working directory instead of carrying the whole inventory in one conversation. `integrations/hermes/enqueue_listing.py` is a reference implementation for the Hermes Agent Kanban board.

- The operator-facing coordinator owns conversation, prioritization, negotiation policy, test questions, and final optimization. It creates one listing manifest and one task graph per physical item.
- Intake workers handle exactly one item per task: inspect photos, recover purchase evidence, identify the model, research current comps, choose price/floor, prepare photos, and write the manifest. They never publish.
- The publisher worker consumes only manifests marked `ready_to_publish`, acquires `$LBC_STATE_DIR/browser.lock`, and performs the browser write through the shared authenticated profile. Only one browser writer may run at once; never parallelize Leboncoin form submissions against the same account.
- Run `scripts/validate_manifest.py` before publication. It must reject a publishable/submitted/verified manifest while `tests.blocked_reason` is non-empty; never bypass this gate.
- The verifier worker independently reads the fresh dashboard/public listing and verifies title, price, body, photo count/order, condition, shipping, status, and public URL before completion.
- Subscribe the operator-facing chat to intake terminal events and final verifier events in `wake` mode so the coordinator can handle blockers and summarize verified completion.
- A listing needing a critical test, privacy cleanup, safety check, missing model identity, or operator decision must be blocked with the exact gate. Routine items should proceed without a test gate.
- Device factory reset / account unlink (trackers, cameras, intercom apps) is never a publication gate. **Never promise seller-side handoff work in the copy** (no « réinitialisation usine », « mise à zéro », « retiré de mon compte », « dissocié », « testé à la remise », re-powering): the seller does not do it, and for wired gear such as intercoms re-powering at the panel is impossible. `validate_manifest.py` rejects such bodies. Optionally note a private `workflow.handoff_gate` reminder for the operator, never in buyer-facing text, and never present it as a mandatory step. Block publication only if photos expose credentials or the device is account-locked in a way that changes value.
- Persist canonical state in `items/<slug>/manifest.json`; task comments and chat summaries are not the source of truth. Every mutation must update the manifest with listing ID, URL, timestamp, and verified fields.
- Use one dependency chain per item: intake → publisher → verifier. Intake can fan out across multiple worker profiles; publisher tasks remain serialized.
- Use medium reasoning for routine intake, publisher, and verifier work; escalate ambiguous/high-value identification, pricing, compatibility, or safety analysis to an expert profile on a stronger model.

## Live event monitoring

- `watcher/leboncoin_event_watch.py` is the read-only seller-event collector; `watcher/leboncoin_event_watch.sh` runs it under the shared browser lock. It paginates the complete dashboard and all conversation summaries, diffs against `$LBC_STATE_DIR/event-watch.json` (0600), and fetches message history only for changed seller conversations.
- Schedule `watcher/leboncoin_event_signal.py` every 15 minutes in an agent-backed **monitor** mode (the scheduler wakes the agent only when the script's output changes). The signal wrapper persists the latest non-empty event output so no-event polls remain byte-stable: unchanged output costs no LLM call, while a new event wakes the agent. Shorter intervals combined with heavy daytime browsing triggered DataDome captchas.
- The awakened agent loads this skill, rereads the fresh conversation/ad/manifest, and delivers an actionable French note: event, recommendation, and exact proposed reply. It never replies, accepts/refuses an offer, or marks a message read. Its sole pre-authorized listing mutation is pausing an exact single-item ad after a freshly verified paid/confirmed seller-side purchase; every other mutation still requires the operator's explicit approval.
- If the scheduler offers cross-run "continuity", keep it disabled: raw alerts can otherwise be mistaken for already-analyzed events. Output-hash deduplication is sufficient. If it can attach alerts to a chat session, enable that so the operator can reply directly to an alert.
- Alert on incoming buyer messages, offers, payment/shipping/system events, listing status changes, and removals; ignore outgoing messages and stay silent without changes.
- Message-history checks use authenticated GET only and never invoke `_links.read`; verify the unread counter before/after while testing. The initial baseline may use the latest weekly snapshot as cutoff so post-audit events are not lost.

## Recommendation standard

Prioritize:

1. Active buyer questions and time-sensitive negotiations.
2. High-value ads with real interest but no conversion.
3. High-view/low-conversion ads needing price, trust, or specification fixes.
4. Stale low-value inventory to bundle, donate, pause, or delete.

Recommend concrete title, description, photo, price, and reply changes grounded in live data. Do not recommend paid boosts while pricing, trust, or listing quality is still the bottleneck.

## Writes

Edits, price changes, relisting, offers, and replies are external side effects. Present the exact batch and obtain confirmation before execution. After each write, read back the target listing or conversation before claiming success.

The create flow also has two commits: submit the completed form with **Continuer**, then choose **Déposer sans booster mon annonce**. Replace Leboncoin's generated description and predicted price with the approved values before the first commit, and assert them exactly. The generator can fire after photos/category are set and silently overwrite a body typed earlier (two listings shipped with AI text this way): type the body LAST and re-assert it right before **Continuer**. The publish prompt in `integrations/hermes/enqueue_listing.py` encodes this. The same AI autofill also sets attributes: it enabled Mondial Relay shipping on a hand-off-only item and set a wrong brand on a piece of children's furniture. Before **Continuer**, also assert shipping on/off matches `listing.shipping` and the brand attribute matches the item (or « Autre »). Leboncoin enables delivery by default: for hand-off-only items, positively locate the delivery control and assert it is OFF. A missing control is a failure, never a silent pass: an early publish script returned early when no checkbox matched and shipped a hand-off-only item with Mondial Relay on. A hand-off-only listing reads back as `shippable=false`, `shipping_type=face_to_face` in the dashboard; `purchase_cta_visible=true` still appears, because Leboncoin keeps secure payment for in-person hand-off, and is expected. Leboncoin sanitizes domain-like merchant names such as `Amazon.fr` into `[URL masquée pour votre sécurité]`; write `Amazon` instead, then verify the stored body from a fresh dashboard response.

The edit page URL is `https://www.leboncoin.fr/annonce/{id}/editer` (from the dashboard's “Modifier gratuitement” link); `/editer/{id}` returns 404. The edit flow has two commits: submit **Valider les modifications**, then choose **Modifier sans booster mon annonce** on the options page. Complete both in the same browser page; navigating directly back to `/editer/options` loses the flow authorization. Treat the confirmation page as acceptance only, then verify title, price, body, photos, and status through a fresh dashboard response.

For React-controlled edit fields, especially `textarea[name=body]`, use keyboard events (`Ctrl+A`, `press_sequentially`, then `Tab`) and assert the exact title/body/price values before submitting. Playwright `fill()` can visually change the description while failing to persist it, even when title and price do persist.

Optional paid boost prices are normally displayed on the options page. Never select one; the only permitted commit is the explicit **Modifier sans booster mon annonce** action. If that free action is missing, disabled, or replaced by a paid action, stop.

After a free edit, verify ranking separately. A confirmation email and changed content do not prove a bump: compare dashboard/public Finder `index_date` and position under `sort_by: time`. On one catalogue rotation, six confirmed free edits retained their original `index_date` and remained old in public time-sorted results, so they were not bumped.

Leboncoin's official rule is category-specific: without an existing promotion, a validated edit normally returns an ad to the top while preserving its original expiry, but not for Vacances, Mode, Multimédia et Loisirs, Décoration, Linge de maison, or Arts de la table. Re-check the current official help page before relying on this because the policy may change. Also reconcile the help page's pricing statement with the live per-ad `free_edit` flag and the options page: they can disagree. Never authorize a paid edit implicitly; stop before the final commit if any charge appears.

When consolidating listings, update and verify the surviving listing first; delete the redundant listing only after the replacement is visible and exact. Verify deletion by refreshing the dashboard and confirming the old ID/card is absent.
