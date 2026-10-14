---
name: leboncoin-multicomponent-listing-photos
description: "Use when managing photos for bundled/kit Leboncoin listings."
---

# Leboncoin multi-component listing photos

Bundled listings (kits, sets of several screens, intercom packages) are error-prone because photo confusion causes buyer complaints and returns. Prevent mix-ups through systematic photo assignment and cross-verification.

## Prevention

**Before uploading photos**:

1. Record one entry per physical sub-item (in your inventory tool, or one folder per sub-item next to the manifest), e.g. three intercom screens = three entries.
2. For each sub-item, keep photos labeled by component ("Écran 1 — face avant", "Écran 1 — arrière", etc.).
3. In the Leboncoin manifest, create a photo assignment table mapping each public listing photo number to the corresponding sub-item and file.
   - Example: "Photos 1–3 = écran intérieur (réf. fabricant); photos 4–5 = platine de rue; photos 6–7 = alimentation + adaptateur."

4. When writing the listing description, include the photo assignment as a key section:
   ```
   Photo 1–3 : écran intérieur Wi-Fi, réf. XXXXX (7", boîtier blanc)
   Photo 4–5 : platine de rue (caméra, haut-parleur)
   Photo 6–7 : alimentation 24 V et adaptateur
   ```

**When uploading**:

1. Use `scripts/lbc_replace_photos.py <ad_id> <exact_title> <photo...> [--commit]` under the browser lock (dry run first).
2. After upload, capture the dashboard API response via `scripts/lbc_dashboard_photos.py <ad_id>` and verify thumbnail order.
3. Open the public Leboncoin listing and walk the carousel photo-by-photo to confirm the assignment matches the description.

## Audit after complaints

If a buyer claims a photo doesn’t match the description, or you suspect a photo mix-up:

1. Reread the live Leboncoin listing (both dashboard and public carousel) and the original sub-item photos side-by-side.
2. Identify which photo (number N) is misassigned.
3. Correct via `lbc_replace_photos.py` with the photos in the right order, or use the reorder buttons on the edit page (« Échanger l'ordre des photos numéro N et N-1 » via DOM click).
4. Verify the correction is live before replying to the buyer.

## Pitfalls

- **Photo confusion on an intercom kit caused three confused buyers and returns**: buyers thought unrelated items were part of the kit because photos were not grouped by component. Always number and label by sub-item.
- **Photo list on public page is unreliable**: it renders thumbnails from other sellers' listings if scrolling blends them. Use only the carousel on the individual listing page and the dashboard API for verification.
- **Edit page photo order is persistent**: reordering via « Échanger » commits immediately and is reflected in the next dashboard read. There is no draft or preview before final order — get the order right before clicking the reorder button.
- **Stock/manufacturer photos can mask real condition**: if you add a stock photo of an unfolded bed or fully assembled item, mark it clearly in the description ("Photo X : visuel du fabricant") and keep real photos first so the buyer’s first impression is accurate condition.
