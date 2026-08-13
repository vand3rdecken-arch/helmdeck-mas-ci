# -*- coding: utf-8 -*-
"""Screenshot the More tab with the new 'Feedback geben' row (Userjot board
link) so the UI can be JUDGED (CLAUDE.md). Uses DEMO MODE, no daemon needed.

Prereqs:  npx expo start --web --offline --port <port>   (dev server, app/)
Run:      py -3.12 tests/uifix_feedback_shoot.py [port]   (default 3722)
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "_shots")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3722
os.makedirs(SHOTS, exist_ok=True)

from playwright.sync_api import sync_playwright

errors = []
popups = []

with sync_playwright() as p:
    b = p.chromium.launch()

    def shoot(name, width, height, wait=3500, click=None, scroll=0):
        page = b.new_page(viewport={"width": width, "height": height},
                          device_scale_factor=2)
        # first hit after --clear waits on Metro's initial bundle (minutes)
        page.set_default_navigation_timeout(240000)
        page.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.on("popup", lambda pp: popups.append(pp.url))
        page.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('helmdeck.demo', '1')")
        page.goto("http://127.0.0.1:%d/more" % PORT, wait_until="domcontentloaded")
        page.wait_for_timeout(wait)
        if scroll:
            page.mouse.wheel(0, scroll)
            page.wait_for_timeout(600)
        for label in (click or []):
            # RN-web re-renders under the pointer - dispatch directly.
            try:
                page.get_by_text(label, exact=False).first.dispatch_event("click", timeout=8000)
                page.wait_for_timeout(1200)
            except Exception as e:
                errors.append("click %r failed: %s" % (label, e))
        out = os.path.join(SHOTS, name + ".png")
        page.screenshot(path=out)
        print("shot " + out)
        page.close()

    # the links panel with the new row (bottom of the list -> scroll down)
    shoot("feedback-more-phone", 420, 1100, scroll=900)
    shoot("feedback-more-wide", 1440, 1000)
    # 2nd tap: the row itself - on web WebBrowser opens a popup/new tab;
    # we only assert the press wires through to the board URL.
    # browser context is en-US -> the row says "Give feedback"
    shoot("feedback-tapped", 420, 1100, scroll=900, click=["Give feedback"])
    b.close()

print("popups: %s" % (popups or "none"))
if errors:
    print("\nBROWSER ERRORS (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
else:
    print("\nno browser errors")
