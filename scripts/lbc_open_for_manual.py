#!/usr/bin/env python3
"""Open the LBC dashboard in a foreground tab and leave it open for manual CAPTCHA solving
through a remote viewer (e.g. VNC). Run with LBC_KEEP_TABS=1 so the lock wrapper does not close it."""
from playwright.sync_api import sync_playwright
from lbc_config import CDP

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(CDP)
    page = browser.contexts[0].new_page()
    page.goto("https://www.leboncoin.fr/compte/part/mes-annonces", wait_until="domcontentloaded", timeout=60000)
    page.bring_to_front()
    page.wait_for_timeout(5000)
    print("tab left open:", page.url)
