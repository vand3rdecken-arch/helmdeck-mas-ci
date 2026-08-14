# -*- coding: utf-8 -*-
"""Screenshot the public waitlist landing page with the new footer 'Feedback'
link so the UI can be JUDGED (CLAUDE.md). Requires the Cloudflare Worker dev
server running locally.

Prereqs:  cd deploy/waitlist && npx wrangler dev --port 8787
Run:      py -3.12 tests/uifix_waitlist_feedback_shoot.py [port]
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "_shots")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
os.makedirs(SHOTS, exist_ok=True)

from playwright.sync_api import sync_playwright

errors = []
popups = []

with sync_playwright() as p:
    b = p.chromium.launch()

    def shoot(name, width, height, path="/", wait=1200, click=None):
        page = b.new_page(viewport={"width": width, "height": height},
                          device_scale_factor=2)
        page.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.on("popup", lambda pp: popups.append(pp.url))
        page.goto("http://127.0.0.1:%d%s" % (PORT, path), wait_until="domcontentloaded")
        page.wait_for_timeout(wait)
        for label in (click or []):
            try:
                page.get_by_text(label, exact=True).first.click(timeout=8000)
                page.wait_for_timeout(600)
            except Exception as e:
                errors.append("click %r failed: %s" % (label, e))
        out = os.path.join(SHOTS, name + ".png")
        page.screenshot(path=out)
        print("shot " + out)
        page.close()

    shoot("waitlist-de-phone", 420, 900)
    shoot("waitlist-de-wide", 1440, 960)
    # DE default -> footer link text is plain "Feedback" already (no i18n key)
    shoot("waitlist-en-phone", 420, 900, click=["EN"])
    shoot("waitlist-footer-tapped", 420, 900, click=["Feedback"])
    b.close()

print("popups: %s" % (popups or "none"))
if errors:
    print("\nBROWSER ERRORS (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
else:
    print("\nno browser errors")
