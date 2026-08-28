# -*- coding: utf-8 -*-
"""Screenshot the unsent-message strip so a human can JUDGE it (CLAUDE.md: UI
changes are judged, not merely confirmed to render).

Drives the real app on the Expo web dev server in DEMO mode - the one way to
reach the chat without a paired daemon - and seeds data/outbox.ts's storage key
directly, which is exactly the state a send that never reached the daemon
leaves behind. Shoots light and dark.

Usage:  py -3.12 ops/tools/shot_outbox.py <port> <outdir>
"""
import json
import sys

from playwright.sync_api import sync_playwright

port = sys.argv[1] if len(sys.argv) > 1 else "3560"
out = sys.argv[2] if len(sys.argv) > 2 else "."
base = "http://localhost:%s" % port

# The shape data/outbox.ts writes. Two rows so grouping/spacing is visible, and
# one long German message so wrapping and the 2-line clamp are judgeable.
ROWS = [
    {"id": "1-aaa", "scope": "board",
     "text": "Henry, bitte deploy die Karte chat-bug-zwei-symptome und pruef "
             "danach den Gate-Report - ich will wissen ob der Deploy-Hook "
             "diesmal gruen durchlaeuft.",
     "opts": {"model": "auto", "to": "henry"}, "at": 1, "tries": 1,
     "error": "Direktverbindung (LAN) fehlgeschlagen"},
    {"id": "2-bbb", "scope": "board", "text": "und danach bitte Status",
     "opts": {}, "at": 2, "tries": 3, "error": "Relay nicht erreichbar (Netzwerk/DNS)"},
    {"id": "3-ccc", "scope": "board", "text": "dritte Nachricht", "opts": {},
     "at": 3, "tries": 1, "error": "Desktop offline"},
    # rows 4+ must NOT render as rows - they must collapse into a "+N" line, or
    # the strip would push the composer off a phone screen.
    {"id": "4-ddd", "scope": "board", "text": "vierte Nachricht", "opts": {},
     "at": 4, "tries": 1, "error": "Desktop offline"},
    {"id": "5-eee", "scope": "board", "text": "fuenfte Nachricht", "opts": {},
     "at": 5, "tries": 1, "error": "Desktop offline"},
]


def shoot(theme):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 420, "height": 900})
        # The app is dark-only for now (src/theme/index.tsx: "Dark by default...
        # we can add the light theme later"), so `theme` names the FILE, not a
        # switch - there is nothing yet to switch to.
        pg.add_init_script("localStorage.setItem('helmdeck.demo','1');")
        pg.goto(base, wait_until="domcontentloaded")
        pg.wait_for_timeout(6000)
        # AsyncStorage on web is localStorage, prefixed by the RN shim.
        pg.evaluate(
            "rows => { const v = JSON.stringify(rows);"
            "  localStorage.setItem('helmdeck.outbox.v1', v);"
            "  localStorage.setItem('@helmdeck.outbox.v1', v); }", ROWS)
        pg.goto(base + "/chat", wait_until="domcontentloaded")
        pg.wait_for_timeout(7000)
        path = "%s/outbox-%s.png" % (out, theme)
        pg.screenshot(path=path, full_page=False)
        print("wrote", path)
        # Assert on the strip in a LANGUAGE-AGNOSTIC way: the app renders in the
        # browser's locale, so matching German text silently "passed" as absent
        # when the page came up English. Count the rendered rows instead.
        body = pg.inner_text("body")
        rows_shown = sum(1 for r in ROWS if r["text"][:18] in body)
        print("  rows rendered      = %d (expect 3 - the strip is capped)" % rows_shown)
        print("  overflow line      = %s" % ("+2" in body or "2 " in body))
        print("  4th row hidden     = %s" % ("vierte Nachricht" not in body))
        b.close()


try:
    shoot("dark")
except Exception as e:
    print("SHOT FAILED: %s" % str(e)[:300])
