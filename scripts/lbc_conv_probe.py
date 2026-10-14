"""Read-only: list buttons/links and offer-related text in a Leboncoin conversation."""
import sys

from playwright.sync_api import sync_playwright
from lbc_config import CDP, tmp_path

CID = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp(CDP)
    pg = b.contexts[0].new_page()
    try:
        pg.goto(f'https://www.leboncoin.fr/messages/id/{CID}', wait_until='domcontentloaded', timeout=90000)
        pg.wait_for_timeout(6000)
        for el in pg.locator('button, a[role=button]').all():
            try:
                t = (el.inner_text() or el.get_attribute('aria-label') or '').strip().replace('\n', ' ')
                if t:
                    print('BTN', el.is_enabled(), '|', t[:80])
            except Exception:
                pass
        txt = pg.inner_text('body')
        print('---- last 1200 chars ----')
        print(txt[-1200:])
        pg.screenshot(path=str(tmp_path(f'lbc_conv_{CID[:8]}.png')))
    finally:
        pg.close()
