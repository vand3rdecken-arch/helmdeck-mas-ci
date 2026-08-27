# -*- coding: utf-8 -*-
"""Screenshot the board/PM chat with the demo board active - judging aid for
the card-parity context meter + PM-session usage line above the composer
(surfaces/app/src/app/chat.tsx). Phone width (route) and desktop width (overlay-as-
route fallback) both land in ChatBody, so one route covers the shared UI."""
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "3987"
BASE = "http://localhost:%s" % PORT

with sync_playwright() as pw:
    b = pw.chromium.launch()
    for name, w, h in (("phone", 390, 844), ("desktop", 1280, 820)):
        ctx = b.new_context(viewport={"width": w, "height": h})
        pg = ctx.new_page()
        pg.set_default_timeout(180000)   # first hit compiles the Metro bundle
        pg.goto(BASE, wait_until="domcontentloaded")
        pg.evaluate("localStorage.setItem('helmdeck.demo','1')")
        pg.goto(BASE + "/chat", wait_until="networkidle")
        pg.wait_for_timeout(2500)
        out = "shot_pm_chat_%s.png" % name
        pg.screenshot(path=out)
        print("saved", out)
        ctx.close()
    b.close()
