# -*- coding: utf-8 -*-
"""Drive the PRIMARY onboarding button in a real browser (fresh-PC scenario).

Why this exists: the connect button was dead on a fresh machine and one repair
pass already missed it, because the pass only exercised the "Spaeter einrichten"
skip path. Rendering was never the problem - the CLICK was - so nothing short of
clicking it in a browser and watching what leaves the page proves the fix.

The daemon is deliberately absent. What stands in for surfaces/desktop/setup.js
is a mock control plane that copies the ONE thing under test verbatim from that
file's request handler - the nonce gate

    if (url.searchParams.get("n") !== nonce) return send(403, ...)

- so a client that mis-joins the nonce is rejected here exactly as it is by the
real Electron shell. It reports the reported environment: claude installed, no
daemon, nothing running.

What is checked:
  1. the screen shows the primary button (not the skip path)
  2. clicking it puts a REQUEST on the wire that PASSES the nonce gate, with the
     picker's engine selection intact - the regression itself: the old client
     built ".../provision?engines=claude?n=<nonce>", where the second "?" is a
     literal, so `n` was absent and every click 403'd
  3. the click produces VISIBLE feedback - the button switches to its loading
     state - and does not silently snap back to idle while the run is starting
  4. progress from the control plane reaches the screen
  5. no console/page error

Prereq (background, detached):
  cd surfaces/app && npx expo start --web --port 3611 --offline

  py -3.12 ops/tests/e2e_onboard_connect.py [web-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3611
NONCE = "e2e0nonce0for0onboard"

os.makedirs(SHOTS, exist_ok=True)
_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# ---------------------------------------------------------------- mock plane --
# Mirrors surfaces/desktop/setup.js: same paths, same nonce gate, same shapes.
class Plane:
    def __init__(self):
        self.running = False
        self.done = False
        self.log = []
        self.hits = []        # every request seen: (path, query, accepted)


plane = Plane()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        ok = q.get("n", [None])[0] == NONCE
        plane.hits.append((u.path, u.query, ok))
        # setup.js gates EVERY route on the nonce before it looks at the path.
        if not ok:
            return self._send(403, {"error": "forbidden"})
        if u.path == "/setup/state":
            return self._send(200, {
                "python": True, "pythonBundled": False,
                "claude": True, "claudeVersion": "2.0.1",
                "daemon": False,
                "running": plane.running, "done": plane.done,
            })
        if u.path == "/setup/log":
            return self._send(200, {"log": plane.log,
                                    "running": plane.running, "done": plane.done})
        if u.path == "/setup/engines":
            return self._send(200, {"engines": [
                {"id": "claude", "label": "Claude Code", "tier": "full",
                 "installed": True, "version": "2.0.1"},
                {"id": "codex", "label": "Codex CLI", "tier": "npm-install",
                 "installed": False, "version": ""},
            ]})
        if u.path == "/setup/provision":
            already = plane.running
            plane.running = True
            plane.log.append({"ts": int(time.time() * 1000), "kind": "info",
                              "line": "Claude Code gefunden - starte Einrichtung."})
            return self._send(200, {"started": not already, "alreadyRunning": already})
        return self._send(404, {"error": "not found"})


srv = HTTPServer(("127.0.0.1", 0), Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

CFG = base64.b64encode(json.dumps({
    # No daemon, on purpose - a high port with nothing on it. NOT a low one:
    # Chrome refuses those outright (ERR_UNSAFE_PORT), which would show up as a
    # console error from the harness rather than from the app.
    "baseUrl": "http://127.0.0.1:65001",
    "token": "",
    "setup": {"port": PORT, "nonce": NONCE},
}).encode()).decode()
URL = "http://127.0.0.1:%d/#cfg=%s" % (WEB, CFG)

from playwright.sync_api import sync_playwright   # noqa: E402

print("onboarding connect button end-to-end (real browser, no daemon)")
print("  mock control plane on 127.0.0.1:%d" % PORT)

# A fresh PC HAS no daemon, so the app's polls to baseUrl failing is the
# scenario, not a defect - the whole point of this screen is to be the thing
# that works when nothing else is up. Uncaught exceptions and every other
# console error still count.
IGNORE = ("ERR_CONNECTION_REFUSED", "Failed to fetch")
errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1180, "height": 860})
    # Metro compiles the bundle on the first request - minutes, not seconds.
    page.set_default_timeout(180000)
    page.set_default_navigation_timeout(180000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(9000)

    # The browser's own locale decides the language (i18n picks it up), so match
    # both rather than pinning one - the claim is about the BUTTON, not the copy.
    body = page.inner_text("body")
    btn = page.get_by_text("Mit Claude einrichten", exact=True)
    if not btn.count():
        btn = page.get_by_text("Set up with Claude", exact=True)
    check(btn.count() > 0, "the primary button is on screen (body: %r)" % body[:90])
    check("Claude Code" in body, "the engine picker shows the detected engine")
    page.screenshot(path=os.path.join(SHOTS, "onboard_1_before_click.png"))

    # pick up an optional extra so claim 2 can prove the selection survives
    if page.get_by_text("Codex CLI", exact=True).count():
        page.get_by_text("Codex CLI", exact=True).first.click()
        page.wait_for_timeout(400)

    before = len([h for h in plane.hits if h[0] == "/setup/provision"])
    btn.first.click()
    page.wait_for_timeout(600)          # inside one poll interval (1200ms)
    mid = page.inner_text("body")
    page.screenshot(path=os.path.join(SHOTS, "onboard_2_just_clicked.png"))

    provisions = [h for h in plane.hits if h[0] == "/setup/provision"]
    check(len(provisions) > before, "the click put a provision request on the wire")
    accepted = [h for h in provisions if h[2]]
    check(bool(accepted), "that request PASSED the nonce gate (403 = the old bug)")
    if accepted:
        q = parse_qs(accepted[-1][1])
        check(q.get("n", [None])[0] == NONCE, "the nonce arrived as its own param: %r" % accepted[-1][1])
        check("claude" in (q.get("engines", [""])[0]), "the engine selection survived: %r" % q.get("engines"))

    def working(txt):
        return "Richte ein" in txt or "Setting up" in txt

    check(working(mid), "the button shows its loading state right after the click")

    page.wait_for_timeout(3000)
    after = page.inner_text("body")
    check(working(after), "it is still showing the run 3s later (no snap back to idle)")
    check("starte Einrichtung" in after, "the control plane's progress reaches the screen")
    check("Konnte die Einrichtung nicht starten" not in after
          and "Could not start setup" not in after, "no start-failed error")
    page.screenshot(path=os.path.join(SHOTS, "onboard_3_running.png"))

    b.close()

real = [e for e in errors if not any(i in e for i in IGNORE)]
check(not real, "no console/page errors beyond the absent daemon: %s" % real[:3])
srv.shutdown()

print("")
if _fails:
    print("FAILED (%d): %s" % (len(_fails), "; ".join(_fails)))
    sys.exit(1)
print("all checks passed - the primary onboarding button starts a real run")
