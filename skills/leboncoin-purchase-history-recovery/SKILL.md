---
name: leboncoin-purchase-history-recovery
description: "Use when recovering purchase history from email archives."
---

# Leboncoin purchase history recovery

When an item's purchase date or price is unknown and the original receipt is absent, run targeted mailbox searches to recover the transaction. Purchase data is context for the listing (age, accessories, warranty, proof of origin) — it never sets the price; Leboncoin comps do.

## Workflow

1. **Retailer-based search**: search by sender with a date window, e.g. `from:<retailer> after:YYYY/MM/DD before:YYYY/MM/DD`, to capture order-confirmation and delivery emails. For seasonal goods use the season boundary ± 2 months.

2. **Search by item clue** (brand, model name, size or reference visible in photos): e.g. `("<brand>" OR "<model>") (commande OR order) after:YYYY/MM/DD`, to find the retailer and the order in one pass. Several keywords from the item reduce false positives.

3. **Extract from confirmation emails**: parse the HTML body for item lines, total, and date. If your mail client/API returns an empty body, walk the MIME tree recursively (fetch the full/raw message and parse every `multipart/*` part): many retailers send nested multipart MIME with the content in inner parts or attachments.

4. **Cross-check with the item**: when a recovered purchase matches the expected period but contradicts the item identity (the email names a different model than the photos show), reread the photos, the email subject and body together. Record the verified facts and leave unresolved questions in the manifest notes rather than guessing.

5. **Declare absence plainly**: if no email trace exists despite searches by retailer, period, and item keywords, note in the manifest that the purchase source is unknown ("probablement d'occasion", "achat non retrouvé", etc.). Do NOT infer a purchase price from comps or retail; missing purchase history is a data-quality issue, not a reason to synthesize a number.

## Useful query patterns

- **Seasonal window**: `(<retailer1> OR <retailer2>) after:YYYY/08/01 before:YYYY/10/31`
- **Sales period**: `(<retailer>) after:YYYY/01/01 before:YYYY/03/31 (soldes OR vente)`
- **Earlier Leboncoin purchases** (the item may itself have been bought on Leboncoin): `leboncoin ("Votre paiement" OR "commande") after:YYYY/MM/DD before:YYYY/MM/DD`

## Pitfalls

- **Nested MIME bodies**: a high-level "get message" helper may return an empty `body` even when the message has content. Fall back to the full message format and parse `payload.parts` recursively.
- **Retailer masking**: some orders put only a reference number in the subject, not the store name. Check the `From` header and sender domain to identify the retailer.
- **Purchase vs. shipment**: an order confirmation (date X) and a shipment notification (date X+3 days) are two different emails; use the order date for purchase history, not the shipment date.
- **Exchanges and returns**: a returned or exchanged item may have two confirmations (original + replacement). Cross-check model and size across both emails to identify the active purchase.
- **Privacy**: keep recovered receipts in the manifest's private fields (`purchase.evidence_private`); never paste order numbers, addresses or prices paid into buyer-facing text.
