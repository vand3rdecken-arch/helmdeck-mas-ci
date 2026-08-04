# -*- coding: utf-8 -*-
"""Drive the exported Expo web build against the sandboxed daemon and SCREENSHOT
the states this branch changed, so the UI can be JUDGED (CLAUDE.md) and not just
assumed to render.

Prereqs:  py -3.12 tests/uifix_harness.py    (daemon + seeded cards on :8199)
          node node_modules/expo/bin/cli export --platform web   (app/dist)

    py -3.12 tests/uifix_shoot.py <device-token>

Serves app/dist on :3300, injects the direct-mode config into localStorage
(baseUrl + Bearer token - the same path desktop/main.js uses), then shoots the
board wide (desktop kanban) and narrow (phone lanes) plus the card detail.
"""
import functools, http.server, os, socket, socketserver, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "app", "dist")
SHOTS = os.path.join(HERE, "_shots")
TOKEN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HELMDECK_TOKEN", "")
DAEMON = "http://localhost:8199"


def _free_port():
    """Windows reserves chunks of the ephemeral range (WinError 10013 on 3300),
    so ask the OS for one that is actually bindable."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = _free_port()

os.makedirs(SHOTS, exist_ok=True)
if not os.path.isdir(DIST):
    sys.exit("no app/dist - run the expo web export first")


class Quiet(http.server.SimpleHTTPRequestHandler):
    """Static server with expo-router SPA fallback: the export writes dynamic
    routes as literal '[id].html', so /card/c-epic must resolve to
    card/[id].html (else the screenshot is a 404 page, not the app)."""

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
srv = socketserver.TCPServer(("127.0.0.1", PORT),
                             functools.partial(Quiet, directory=DIST))
threading.Thread(target=srv.serve_forever, daemon=True).start()
print("serving %s on :%d" % (DIST, PORT))

from playwright.sync_api import sync_playwright

CONFIG = ('{"baseUrl":"%s","token":"%s","relayUrl":"","room":"","daemonPub":"",'
          '"mySec":"","myPub":""}' % (DAEMON, TOKEN))

errors = []

with sync_playwright() as p:
    b = p.chromium.launch()

    def shoot(name, width, height, path="/", wait=3500):
        page = b.new_page(viewport={"width": width, "height": height},
                          device_scale_factor=2)
        page.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('helmdeck.config', %r)" % CONFIG)
        # NOT networkidle: the app holds a transcript long-poll (22s) and an SSE
        # stream open by design, so the network never goes idle.
        page.goto("http://127.0.0.1:%d%s" % (PORT, path), wait_until="domcontentloaded")
        page.wait_for_timeout(wait)
        out = os.path.join(SHOTS, name + ".png")
        page.screenshot(path=out, full_page=True)
        print("shot " + out)
        page.close()

    shoot("board-wide", 1440, 1000)      # desktop kanban (wide >= 900)
    shoot("board-phone", 420, 1000)      # phone single-scroll lanes
    shoot("card-epic", 420, 1000, "/card/c-epic")       # the PMP description
    b.close()

srv.shutdown()
if errors:
    print("\nBROWSER ERRORS (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
else:
    print("\nno browser errors")
