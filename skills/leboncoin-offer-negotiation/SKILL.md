---
name: leboncoin-offer-negotiation
description: "Use when handling buyer offers and negotiations."
---

# Leboncoin offer negotiation

Buyer offers arrive as system messages « Votre bien intéresse quelqu'un. Il vous propose une nouvelle offre de X €. ». Never accept an opening offer without grounding the counter in live comps data.

## Workflow

1. **Assess the offer against comps and age**: run `scripts/lbc_comps.py` if comps are unavailable; compute listing age in days; note the median asking price and the p25/p75 range. Assign the offer to a bracket: reasonable (within p25–median), aspirational (median–p75), or lowball (below p25).

2. **Apply the seller floor from the manifest** (typically near p25 or stale-30d median, set at publication). If the offer is below floor, reject and counter with a price above floor or withdraw the counter if the buyer is unmoved.

3. **Counter with a reasoned intermediate** (not a placating counter): if an opening offer is below median but above floor, counter 5 €–10 € above floor (or median −1–0% if higher). State price rationale in chat before sending, e.g. "Comps median is 50 €, floor 40 €, offer is 35 €, counter at 45 €."

4. **Script and verify**: use `scripts/lbc_counter.py <conv_id> <title> <EUR> --commit` under the browser lock (it refuses a pending buyer offer first, then sends the counter), then reread the conversation to confirm « Offre envoyée … L'acheteur a 48 heures pour payer. ». To send a message together with the counter, use `scripts/lbc_send_offer.py`.

5. **Set a negotiation ceiling**: if the buyer does not accept within 2 offers, recommend the operator make a final take-it-or-leave-it at 1 € above their best bid OR withdraw the counter and let the listing age naturally. Avoid negotiation loops; they erode margins and signal desperation.

## Automatic pausing after verified purchase

For a **single-item seller listing** (not a multi-unit lot or wholesale batch):
- **Pause immediately** only when one of these is verified: order confirmed (via dashboard), shipping label visible/available in conversation, or the operator explicitly approved the sale.
- **Never pause on**: a pending buyer offer, an interest message, or acceptance of the seller's counter-offer before payment confirmation. The buyer has 48h to pay on a countered offer; until then, the listing must remain active.
- Use `scripts/lbc_pause_ad.py <ad_id> <exact_title> --commit` under the browser lock. Verify fresh status with `scripts/lbc_ad_status.py <ad_id>` immediately after.

## Pitfalls

- **Negotiation loops erode margins**: after 2 back-and-forth offers, if no agreement, make a final bottom-line counter and hold it, or withdraw and delist. Endless haggling signals weakness and reduces perceived value.
- **Age hurts leverage**: an ad that has been active 30+ days attracts lowball openers because the buyer suspects the seller is motivated. Adjust the floor downward only if the listing is genuinely stale (no views/messages for 2 weeks), not because of the offer alone.
- **Pending offer blocks new counter**: the UI hides « Faire une offre » while a buyer's offer is active. Always refuse first if you need to make a counter that differs from the buyer's offer.
