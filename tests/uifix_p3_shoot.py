# -*- coding: utf-8 -*-
"""Screenshot the P3 transcript model (4 tool states + turn lifecycle +
compaction) so it can be JUDGED (CLAUDE.md), not just confirmed to render.

Prereqs:  py -3.12 tests/uifix_p3_harness.py   (daemon + seeded c-p3 on :8199)
          node node_modules/expo/bin/cli export --platform web   (app/dist)

    py -3.12 tests/uifix_p3_shoot.py <device-token>

Serves app/dist on a free port, injects direct-mode config (baseUrl + Bearer
token), shoots the c-p3 card detail phone-narrow and desktop-wide.
"""
import functools, http.server, os, socket, socketserver, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "app", "dist")
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
    sys.exit("no app/dist - run the expo web export first")


class Quiet(http.server.SimpleHTTPRequestHandler):
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

    def shoot(name, width, height, path="/", wait=4500, tab=None):
        page = b.new_page(viewport={"width": width, "height": height},
                          device_scale_factor=2)
        page.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
        page.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('helmdeck.config', %r)" % CONFIG)
        # NOT networkidle: transcript long-poll + SSE keep the network busy.
        page.goto("http://127.0.0.1:%d%s" % (PORT, path), wait_until="domcontentloaded")
        page.wait_for_timeout(wait)
        if tab:                       # the transcript lives under the Chat tab
            try:
                page.get_by_text(tab).first.click(timeout=8000)
            except Exception as e:
                print("tab click via locator failed (%s) - JS fallback" % str(e)[:80])
                hit = page.evaluate("""(label) => {
                    const els = [...document.querySelectorAll('div,span')];
                    const el = els.find(e => e.childElementCount === 0 &&
                                             e.textContent.includes(label));
                    if (!el) return false;
                    el.closest('[role=button],[tabindex]')?.click() ?? el.click();
                    return true;
                }""", tab)
                print("JS fallback hit: %s" % hit)
            page.wait_for_timeout(2500)
        out = os.path.join(SHOTS, name + ".png")
        page.screenshot(path=out, full_page=True)
        print("shot " + out)
        page.close()

    shoot("p3-card-phone", 420, 1400, "/card/c-p3", tab="Chat")
    shoot("p3-card-wide", 1100, 1400, "/card/c-p3", tab="Chat")
    b.close()

srv.shutdown()
if errors:
    print("\nBROWSER ERRORS (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
else:
    print("\nno browser errors")
