# -*- coding: utf-8 -*-
"""Screenshot helmdeck.de's download section so the four-platform layout can be
JUDGED (CLAUDE.md), not just confirmed to render.

Points at a URL, so the SAME script shoots the local worker before a deploy and
the live origin after one - which is the whole lesson of card proc-20260814-s7:
a merged commit proves nothing, only the live origin does.

Prereqs (local mode):  cd deploy/waitlist && npx wrangler dev --port <port>
Run:  py -3.12 tests/site_platforms_shoot.py [base-url] [tag]
      py -3.12 tests/site_platforms_shoot.py http://127.0.0.1:3483 local
      py -3.12 tests/site_platforms_shoot.py https://helmdeck.de live
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "_shots")
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3483").rstrip("/")
TAG = sys.argv[2] if len(sys.argv) > 2 else "local"
os.makedirs(SHOTS, exist_ok=True)

from playwright.sync_api import sync_playwright

errors = []

# The claim under test: the page leads with shippable apps, and every platform
# the project actually ships is on it. Checked in the DOM so a screenshot that
# "looks fine" cannot hide a missing card.
WANT_HEADINGS = ["Windows", "macOS", "iPhone & iPad", "Android"]

with sync_playwright() as p:
    b = p.chromium.launch()

    def shoot(name, width, height, wait=1400, toggle=False, full=False,
              locale="de-DE", scroll=0):
        # locale drives the page's OWN language pick (navigator.language), so a
        # de-DE context is what an actual German visitor sees - the default.
        ctx = b.new_context(viewport={"width": width, "height": height},
                            device_scale_factor=2, locale=locale)
        page = ctx.new_page()
        page.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(wait)
        if toggle:
            # the button's label is the language it switches TO, so click by id
            page.locator("#lang").click(timeout=8000)
            page.wait_for_timeout(500)
        if scroll:
            page.mouse.wheel(0, scroll)
            page.wait_for_timeout(500)
        out = os.path.join(SHOTS, "%s-%s.png" % (TAG, name))
        page.screenshot(path=out, full_page=full)
        print("shot " + out)
        return page

    page = shoot("wide", 1440, 1000, full=True)
    heads = [h.strip() for h in page.locator("#downloads h3").all_inner_texts()]
    print("platform cards: %s" % heads)
    for want in WANT_HEADINGS:
        if want not in heads:
            errors.append("MISSING platform card: %s" % want)
    title = page.title()
    print("title: %s" % title)
    # Every download CTA must resolve somewhere real - a dead href is the exact
    # failure the live-release lookup exists to prevent.
    hrefs = page.eval_on_selector_all(
        "#downloads a", "els => els.map(e => e.getAttribute('href'))")
    for h in hrefs:
        if not h or h.strip() in ("", "#"):
            errors.append("empty download href: %r" % h)
    print("download hrefs:")
    for h in hrefs:
        print("  " + (h or "")[:110])
    page.close()

    shoot("phone", 420, 900, full=True).close()
    shoot("wide-en", 1440, 1000, toggle=True, full=True).close()
    # viewport-only, and again scrolled onto the download grid: the sticky
    # topbar is translucent, so content bleeding through it only shows up in a
    # real scrolled viewport - a full-page capture would hide it.
    shoot("fold", 1440, 1000).close()
    shoot("scrolled", 1440, 1000, scroll=900).close()
    b.close()

if errors:
    print("\nFAILURES (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
    sys.exit(1)
print("\nno browser errors, all four platform cards present, no dead hrefs")
