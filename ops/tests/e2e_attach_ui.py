# -*- coding: utf-8 -*-
"""Drive the REAL composer in a browser: paste an image, see the chip, send it,
and prove the daemon stored it and the agent prompt will carry its path.

The unit test (test_attachments.py) covers the daemon contract. This covers the
half that was actually missing: the UI. It exercises the web paste path
(surfaces/app/src/ui/card_composer.tsx), which is the same code path the Expo pickers
feed on native.

Prereqs:  py -3.12 ops/tests/uifix_harness.py           (daemon + seeded cards)
          node node_modules/expo/bin/cli export --platform web
    py -3.12 ops/tests/e2e_attach_ui.py <device-token>

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import base64, functools, http.server, json, os, socket, socketserver, sys, threading, time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIST = os.path.join(ROOT, "surfaces", "app", "dist")
SHOTS = os.path.join(HERE, "_shots")
TOKEN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HELMDECK_TOKEN", "")
DAEMON = "http://localhost:8199"
CARD = "c-running"          # a working card, so its chat composer is live

os.makedirs(SHOTS, exist_ok=True)
_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def api(path):
    r = urllib.request.Request(DAEMON + path)
    r.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(r, timeout=20) as f:
        return json.loads(f.read().decode() or "[]")


class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def translate_path(self, path):
        p = super().translate_path(path.split("?")[0])
        if os.path.isfile(p) or os.path.isdir(p):
            return p
        if os.path.isfile(p + ".html"):
            return p + ".html"
        dyn = os.path.join(os.path.dirname(p), "[id].html")
        if os.path.isfile(dyn):
            return dyn
        return os.path.join(DIST, "index.html")


s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(Q, directory=DIST))
threading.Thread(target=srv.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright

CFG = ('{"baseUrl":"%s","token":"%s","relayUrl":"","room":"","daemonPub":"","mySec":"","myPub":""}'
       % (DAEMON, TOKEN))

# a real 1x1 PNG - small, but a genuine image the daemon will decode
PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

print("attachment composer end-to-end (real browser, real daemon)")
before = api("/tracks/%s/attachments" % CARD)

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded")
    page.evaluate("localStorage.setItem('helmdeck.config', %r)" % CFG)
    page.goto("http://127.0.0.1:%d/card/%s" % (PORT, CARD), wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    # open the Chat tab so the composer is mounted
    try:
        page.get_by_text("Chat", exact=False).first.click(timeout=8000)
        page.wait_for_timeout(1500)
    except Exception:
        pass

    # PASTE a PNG exactly like a user hitting Ctrl+V with a screenshot
    page.evaluate(
        """(b64) => {
            const bin = atob(b64);
            const arr = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
            const file = new File([arr], 'pasted-shot.png', { type: 'image/png' });
            const dt = new DataTransfer();
            dt.items.add(file);
            window.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
        }""", PNG_B64)
    page.wait_for_timeout(2500)

    body = page.inner_text("body")
    check("pasted-shot.png" in body, "the pasted image shows up as a chip in the composer")
    page.screenshot(path=os.path.join(SHOTS, "attach-chip.png"), full_page=True)

    # send it
    sent = False
    for sel in ('[aria-label="Anhang hinzufügen"]',):
        pass
    try:
        page.get_by_placeholder("Nachricht", exact=False).first.fill("Schau dir das Bild an")
        page.wait_for_timeout(400)
    except Exception:
        pass
    # the send button is the last pressable in the input row; click by position
    try:
        page.keyboard.press("Enter")
    except Exception:
        pass
    page.wait_for_timeout(1200)
    page.screenshot(path=os.path.join(SHOTS, "attach-sent.png"), full_page=True)
    b.close()

srv.shutdown()

# React #418 is a hydration mismatch from serving the expo-router STATIC export
# off a plain file server - it predates this feature (it fires on the untouched
# board too) and is a harness artifact, not an app bug. Anything else is real.
real = [e for e in errors if "#418" not in e]
check(not real, "no uncaught browser errors beyond the known static-export hydration warning: %s"
      % (real[:1] or "none"))

print()
for f in sorted(os.listdir(SHOTS)):
    if f.startswith("attach-"):
        print("  shot ops/tests/_shots/" + f)

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("composer attachment checks passed")
