# -*- coding: utf-8 -*-
"""Screenshot the compact background-task track (Paseo SubagentsTrack parity)
so the UI can be JUDGED (CLAUDE.md). Uses DEMO MODE (card d4 is parked on a
running background task and carries finished/canceled history), so no daemon
is needed.

Prereqs:  node node_modules/expo/bin/cli export --platform web   (surfaces/app/dist)
Run:      py -3.12 ops/tests/uifix_bgtrack_shoot.py
"""
import functools, http.server, os, socket, socketserver, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIST = os.path.join(ROOT, "surfaces", "app", "dist")
SHOTS = os.path.join(HERE, "_shots")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = _free_port()
os.makedirs(SHOTS, exist_ok=True)
if not os.path.isdir(DIST):
    sys.exit("no surfaces/app/dist - run the expo web export first")


class Quiet(http.server.SimpleHTTPRequestHandler):
    """expo-router SPA fallback: dynamic routes export as literal '[id].html'."""

    def log_message(self, *a):
        pass

    def translate_path(self, path):
        p = super().translate_path(path)
        if os.path.isfile(p) or os.path.isdir(p):
            return p
        if os.path.isfile(p + ".html"):
            return p + ".html"
        dyn = os.path.join(os.path.dirname(p), "[id].html")
        if os.path.isfile(dyn):
            return dyn
        return os.path.join(DIST, "index.html")


socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(Quiet, directory=DIST))
threading.Thread(target=srv.serve_forever, daemon=True).start()
print("serving %s on :%d" % (DIST, PORT))

from playwright.sync_api import sync_playwright

errors = []

with sync_playwright() as p:
    b = p.chromium.launch()

    def shoot(name, width, height, path="/", wait=3500, click=None):
        page = b.new_page(viewport={"width": width, "height": height},
                          device_scale_factor=2)
        page.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('helmdeck.demo', '1')")
        page.goto("http://127.0.0.1:%d%s" % (PORT, path), wait_until="domcontentloaded")
        page.wait_for_timeout(wait)
        for label in (click or []):
            # RN-web re-renders under the pointer, so Playwright's actionability
            # wait times out even though the press lands - dispatch directly.
            try:
                page.get_by_text(label, exact=False).first.dispatch_event("click", timeout=8000)
                page.wait_for_timeout(900)
            except Exception as e:
                errors.append("click %r failed: %s" % (label, e))
        out = os.path.join(SHOTS, name + ".png")
        page.screenshot(path=out)
        print("shot " + out)
        page.close()

    # collapsed: ONE compact line, no pill, no permanent list
    shoot("bg-collapsed-phone", 420, 1100, "/card/d4", click=["Chat"])
    shoot("bg-collapsed-wide", 1440, 1000, "/card/d4", click=["Chat"])
    # expanded: the rows incl. finished/canceled history
    shoot("bg-expanded-phone", 420, 1100, "/card/d4", click=["Chat", "waiting on"])
    # expanded + one row opened (detail/result)
    shoot("bg-row-open", 420, 1100, "/card/d4", click=["Chat", "waiting on", "pytest"])
    b.close()

srv.shutdown()
if errors:
    print("\nBROWSER ERRORS (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
else:
    print("\nno browser errors")
