# -*- coding: utf-8 -*-
"""Screenshot Modules & Rules + the sign-in screen in BOTH languages, so the
i18n pass on those screens can be JUDGED (CLAUDE.md) - English labels are the
longer ones, so the stat rows and section hints are where overflow would show.

Runs against a REAL daemon, not demo mode: the demo fixture models neither
/policy nor /cells (data/demo.ts), so every row this screen is made of would
come up empty - a green-looking screenshot of nothing.

    py -3.12 -m daemon.swarm serve 8607                 # from the repo root
    cd app && node node_modules/expo/bin/cli start --web --port 3607 --offline
    py -3.12 tests/shot_modules_i18n.py <owner-token> [daemon-port] [web-port]

Two things that are NOT the browser locale:
  - the workspace language wins (useLang reads /me), so this flips
    policy.lang through /settings between passes and restores it at the end;
  - the sign-in screen runs before there IS a token, so /me 401s and the
    DEVICE locale decides - which is why that pass uses a bogus token.
full_page is useless here (the screen is an RN ScrollView, the document never
grows), so the long screen is shot at fixed scroll stops instead.
"""
import base64
import json
import os
import sys
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "_shots")
TOKEN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HELMDECK_TOKEN", "")
DAEMON = "http://127.0.0.1:%s" % (sys.argv[2] if len(sys.argv) > 2 else "8607")
WEB = "http://localhost:%s" % (sys.argv[3] if len(sys.argv) > 3 else "3607")
STOPS = (0, 900, 1800, 2700)
PHONE = {"width": 430, "height": 950}

if not TOKEN:
    sys.exit("usage: shot_modules_i18n.py <owner-token> [daemon-port] [web-port]")
os.makedirs(SHOTS, exist_ok=True)


def cfg(token):
    """The desktop's hash seam (data/config.ts hydrate): #cfg=base64{baseUrl,token}."""
    return base64.b64encode(json.dumps({"baseUrl": DAEMON, "token": token}).encode()).decode()


def set_lang(lang):
    urllib.request.urlopen(urllib.request.Request(
        DAEMON + "/settings", method="POST",
        data=json.dumps({"policy": {"lang": lang}}).encode(),
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})).read()


def shot(page, name):
    page.wait_for_timeout(900)
    page.screenshot(path=os.path.join(SHOTS, name))


with sync_playwright() as p:
    browser = p.chromium.launch()
    for lang in ("de", "en"):
        set_lang(lang)
        ctx = browser.new_context(locale="de-DE" if lang == "de" else "en-US",
                                  viewport=PHONE, device_scale_factor=2)
        page = ctx.new_page()
        page.goto("%s/modules#cfg=%s" % (WEB, cfg(TOKEN)), wait_until="load", timeout=180_000)
        # The first web bundle takes minutes - wait for real copy, not a delay.
        page.wait_for_selector("text=/Module & Regeln|Modules & rules/", timeout=300_000)
        page.wait_for_timeout(4000)
        for i, y in enumerate(STOPS):
            page.evaluate("""(y) => {
                const els = [...document.querySelectorAll('div')]
                  .filter(e => e.scrollHeight > e.clientHeight + 200);
                const sc = els.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
                if (sc) sc.scrollTop = y;
            }""", y)
            shot(page, "modules_%s_%d.png" % (lang, i))
        # cell_diagram's empty-state leaf ("no routes"): buildloop is the cell
        # with zero routes, and that column sits past the diagram's own
        # horizontal scroller.
        page.click("text=buildloop")
        page.wait_for_timeout(1500)
        page.get_by_text("buildloop").first.scroll_into_view_if_needed()
        page.evaluate("""() => {
            const h = [...document.querySelectorAll('div')].filter(e => e.scrollWidth > e.clientWidth + 100);
            const sc = h.sort((a, b) => b.scrollWidth - a.scrollWidth)[0];
            if (sc) sc.scrollLeft = sc.scrollWidth;
        }""")
        shot(page, "modules_celldiagram_%s.png" % lang)

        # Sign-in: a bad token 401s, client.ts reports it, authgate mounts the
        # LoginScreen - the same path a stale token takes on a real device.
        page.goto("%s/board#cfg=%s" % (WEB, cfg("bogus")), wait_until="load", timeout=180_000)
        page.wait_for_selector("text=/Anmelden|Sign in/", timeout=120_000)
        shot(page, "login_%s.png" % lang)
        print("%s: modules + diagram + login" % lang)
        ctx.close()
    browser.close()

set_lang("de")     # leave the workspace as it was found
print("shots in tests/_shots/")
