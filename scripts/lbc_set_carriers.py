#!/usr/bin/env python3
"""Set the carrier list of a Leboncoin ad (free edit, never boosts).

Default target: Shop2Shop by Chronopost + Colissimo ON, Mondial Relay OFF; other carriers left as they are.

Usage: lbc_set_carriers.py <ad_id> [--commit]
Dry run: opens « Modifier les transporteurs », applies toggles, validates the dialog, asserts, then closes WITHOUT submitting.
Run under scripts/with_browser_lock.py.
"""
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP

CAPTCHA = 'iframe[src*="captcha-delivery.com"], #ddChallengeContainer'
AD = sys.argv[1]
COMMIT = "--commit" in sys.argv
WANT = {"Shop2Shop by Chronopost": True, "Colissimo": True, "Mondial Relay": False}

STATE_JS = """() => {
  const d = document.querySelector('[role=dialog]');
  if (!d) return null;
  const out = {};
  for (const b of d.querySelectorAll('button[role=checkbox]')) {
    let n = b, label = null;
    for (let k = 0; k < 6 && n; k++) {
      n = n.parentElement;
      const t = (n && n.innerText) || '';
      const hits = ['Courrier suivi','Shop2Shop by Chronopost','Mondial Relay','Colissimo','Autres moyens de livraison'].filter(x => t.includes(x));
      if (hits.length === 1) { label = hits[0]; break; }
      if (hits.length > 1) break;
    }
    if (label) out[label] = b.getAttribute('aria-checked') === 'true';
  }
  return out;
}"""

CLICK_JS = """(want) => {
  const d = document.querySelector('[role=dialog]');
  for (const b of d.querySelectorAll('button[role=checkbox]')) {
    let n = b;
    for (let k = 0; k < 6 && n; k++) {
      n = n.parentElement;
      const t = (n && n.innerText) || '';
      const hits = ['Courrier suivi','Shop2Shop by Chronopost','Mondial Relay','Colissimo','Autres moyens de livraison'].filter(x => t.includes(x));
      if (hits.length === 1) { if (hits[0] === want) { b.click(); return true; } break; }
      if (hits.length > 1) break;
    }
  }
  return false;
}"""


def summary(page):
    return page.evaluate("""() => {
      const s = [...document.querySelectorAll('section, div')].find(d => d.innerText && d.innerText.startsWith('Remise du bien'));
      return s ? s.innerText.slice(0, 600) : '';
    }""")


with sync_playwright() as p:
    ctx = p.chromium.connect_over_cdp(CDP).contexts[0]
    page = ctx.new_page()
    try:
        page.goto(f"https://www.leboncoin.fr/annonce/{AD}/editer", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        if page.locator(CAPTCHA).count():
            raise RuntimeError("CAPTCHA before mutation")
        if "en cours de validation" in page.inner_text("body"):
            raise RuntimeError("Ad locked (transaction in progress)")
        page.evaluate("() => document.querySelector('#gimii-root')?.remove()")
        title = page.locator('input[name="subject"]').input_value()
        body = page.locator('textarea[name="body"]').input_value()
        price = page.locator('input[name="price_cents"]').input_value()
        has_btn = page.evaluate("() => !!document.querySelector('button[aria-label=\"Modifier les transporteurs\"]')")
        if not has_btn:
            print(f"SKIP {AD} {title!r}: shipping not enabled (no carrier editor)")
            sys.exit(0)
        ship_on = page.evaluate("() => !![...document.querySelectorAll('button')].find(x => x.getAttribute('aria-label') === 'Désactiver la livraison')")
        if not ship_on:
            print(f"SKIP {AD} {title!r}: shipping is OFF (hand delivery only) — never enable it here")
            sys.exit(0)
        page.evaluate("() => document.querySelector('button[aria-label=\"Modifier les transporteurs\"]').click()")
        page.wait_for_timeout(2500)
        before = page.evaluate(STATE_JS)
        print(AD, title, "| before:", before)
        if not before or not all(k in before for k in WANT):
            raise AssertionError(f"carrier mapping incomplete: {before}")
        if all(before[k] == v for k, v in WANT.items()):
            print("ALREADY OK — nothing to change")
            sys.exit(0)
        for k, v in WANT.items():
            if before[k] != v:
                if not page.evaluate(CLICK_JS, k):
                    raise RuntimeError(f"cannot toggle {k}")
                page.wait_for_timeout(500)
        after = page.evaluate(STATE_JS)
        print("after:", after)
        if "--allow-no-colissimo" in sys.argv and not after["Colissimo"]:
            print("WARN: Colissimo unavailable for this ad (size/weight); keeping Shop2Shop only")
            WANT["Colissimo"] = False
        if any(after[k] != v for k, v in WANT.items()):
            raise AssertionError(f"toggle failed: {after}")
        for k in before:
            if k not in WANT and after.get(k) != before[k]:
                raise AssertionError(f"unexpected change on {k}")
        page.get_by_role("dialog").get_by_role("button", name="Valider", exact=True).click()
        page.wait_for_timeout(2000)
        if page.get_by_role("dialog").count():
            raise RuntimeError("carrier dialog did not close")
        if (page.locator('input[name="subject"]').input_value(), page.locator('textarea[name="body"]').input_value(), page.locator('input[name="price_cents"]').input_value()) != (title, body, price):
            raise AssertionError("title/body/price changed")
        print("section:", summary(page).replace("\n", " | ")[:300])
        if not COMMIT:
            print("DRY RUN OK — not submitted")
        else:
            btn = page.get_by_role("button", name="Valider les modifications", exact=True)
            if btn.count() != 1 or not btn.is_enabled():
                raise RuntimeError("first commit unavailable")
            btn.click()
            page.wait_for_timeout(9000)
            if page.locator(CAPTCHA).count():
                raise RuntimeError("CAPTCHA after first commit")
            free = page.get_by_role("button", name="Modifier sans booster mon annonce", exact=True)
            if free.count() != 1 or not free.is_enabled():
                raise RuntimeError("free second commit unavailable; refusing paid action")
            free.click()
            page.wait_for_timeout(9000)
            print("accepted", page.url)
    finally:
        page.close()
