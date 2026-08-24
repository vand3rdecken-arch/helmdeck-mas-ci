# -*- coding: utf-8 -*-
"""Screenshot the Phase 2 card states so the UI can be JUDGED (CLAUDE.md).

Prereqs:  py -3.12 ops/tests/uifix_question_harness.py    (daemon + cards on :8199)
          node node_modules/expo/bin/cli export --platform web   (surfaces/app/dist)

    py -3.12 ops/tests/uifix_question_shoot.py <device-token>
"""
import functools, http.server, os, socket, socketserver, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIST = os.path.join(ROOT, "surfaces", "app", "dist")
SHOTS = os.path.join(HERE, "_shots")
TOKEN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HELMDECK_TOKEN", "")
DAEMON = "http://localhost:8199"


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

CONFIG = ('{"baseUrl":"%s","token":"%s","relayUrl":"","room":"","daemonPub":"",'
          '"mySec":"","myPub":""}' % (DAEMON, TOKEN))

errors = []

with sync_playwright() as p:
    b = p.chromium.launch()

    def shoot(name, width, height, path="/", wait=4000, click=None, chat=True):
        page = b.new_page(viewport={"width": width, "height": height},
                          device_scale_factor=2)
        page.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('helmdeck.config', %r)" % CONFIG)
        # NOT networkidle: the app holds a 22s transcript long-poll open by design
        page.goto("http://127.0.0.1:%d%s" % (PORT, path), wait_until="domcontentloaded")
        page.wait_for_timeout(wait)
        if chat:
            # the question panel lives in the card's CHAT tab; the card opens on
            # the overview tab, so switch before shooting
            try:
                page.get_by_text("Chat", exact=False).first.click()
                page.wait_for_timeout(1500)
            except Exception as e:
                errors.append("chat tab click failed: %s" % e)
        for label in (click or []):
            try:
                page.get_by_text(label, exact=False).first.click()
                page.wait_for_timeout(900)
            except Exception as e:
                errors.append("click %r failed: %s" % (label, e))
        out = os.path.join(SHOTS, name + ".png")
        page.screenshot(path=out, full_page=True)
        print("shot " + out)
        page.close()

    # the priority state: one question, four options with descriptions
    shoot("q-single-phone", 420, 1100, "/card/c-question")
    shoot("q-single-wide", 1440, 1000, "/card/c-question")
    # a selected option (the confirm button must come alive)
    shoot("q-single-picked", 420, 1100, "/card/c-question", click=["Magic-Link"])
    # the wizard + multi-select: select, advance, then tick two checkboxes
    shoot("q-multi-phone", 420, 1100, "/card/c-multi")
    shoot("q-multi-step2", 420, 1100, "/card/c-multi",
          click=["Closed Beta", "Weiter", "Unit-Tests", "Lint + Typen"])
    # the compact two-option case
    shoot("q-short-phone", 420, 1100, "/card/c-short")
    # the new background cue vs the ordinary "your move" control
    shoot("cue-background", 420, 1100, "/card/c-bg")
    shoot("cue-needsyou", 420, 1100, "/card/c-needsyou")
    b.close()

srv.shutdown()
if errors:
    print("\nBROWSER ERRORS (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
else:
    print("\nno browser errors")
