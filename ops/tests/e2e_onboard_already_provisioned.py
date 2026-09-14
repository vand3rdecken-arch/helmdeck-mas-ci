# -*- coding: utf-8 -*-
"""Prove the desktop onboarding gate no longer skips itself on a machine that
already has Python + Claude installed.

Root cause (owner report + DevTools photo, 2026-09-14): useShowOnboard()
(surfaces/app/src/ui/onboard.tsx) asked the LOCAL installer's own
`running`/`done` bookkeeping whether onboarding was still needed, instead of
asking the daemon the real question (does an owner account exist yet -
/auth/state's `setup_needed`). surfaces/desktop/main.js starts the daemon
unconditionally on every launch, so on a machine with nothing left to
install, the control plane answers `daemon: true, running: false, done:
false` on the VERY FIRST poll - and the old condition (`!s.daemon ||
s.running || s.done`) went false before the user ever got routed through the
onboarding flow's OWN create-owner step. The app still ended up showing a
create-owner form (the app-wide needsLogin 401 fallback catches it), which is
why this was easy to miss - onboarding was silently bypassed, not visibly
broken.

This drives the real gate (real onboard.tsx, real daemon, real browser)
against exactly that state shape - daemon already up on tick 1, nothing to
install - against a daemon with no owner account yet.

The create-owner screen ends up showing EITHER way, pre-fix or post-fix -
that is exactly what made the bug easy to miss by eye: the pre-fix app fell
through to the app-wide needsLogin 401 fallback, which also lands on
LoginScreen. So a screenshot alone does not pin this. What actually differs
is the PATH: pre-fix, showOnboard was false, so _layout.tsx mounted the
NORMAL app tree first (Dashboard/board queries: /tracks, /cells,
/dashboard/data, ...), which then 401'd/403'd into needsLogin - real traffic
to endpoints a first-run screen has no business calling yet (measured live in
the original repro). Post-fix, showOnboard is true from the first tick
(daemon already up -> ask /auth/state -> setup_needed -> owns=true) and
_layout.tsx returns <Onboard/> before the normal app tree ever mounts, so
those endpoints are never requested at all. This test captures every request
the page makes and asserts none of them hit the normal-app-only endpoints.

Prereqs: `npm --prefix surfaces/app run build:web` (surfaces/app/dist must
exist) and a clean git checkout (this script makes its own detached worktree
so it never touches the real daemon/users.json or helmdeck.db).

Named e2e_* so ops/tools/run_gate.py skips it (needs ports + a browser + git
worktree).

    py -3.12 ops/tests/e2e_onboard_already_provisioned.py
"""
import functools
import http.server
import json
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIST = os.path.join(ROOT, "surfaces", "app", "dist")
# OUTSIDE the repo tree on purpose: spine/storage/db.py's
# _refuse_live_db_from_tests() sniffs the CALLER'S OWN FILE PATH (daemon/
# swarm.py's location) for "test"/"tests" and refuses to open the db from
# anywhere that matches - a worktree nested under ops/tests/ trips that guard
# even though it is a real, isolated checkout with its own empty db. Placing
# it in the OS temp dir sidesteps the guard the same way the real repro in
# this session's transcript did (git worktree add outside ops/tests).
WORKTREE = os.path.join(tempfile.gettempdir(), "helmdeck-e2e-onboard-worktree")
SHOTS = os.path.join(HERE, "_shots")
os.makedirs(SHOTS, exist_ok=True)

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


class _StaticSPA(http.server.SimpleHTTPRequestHandler):
    """Serves surfaces/app/dist with an index.html SPA fallback, same shape
    as surfaces/desktop/main.js's own local UI server."""

    def log_message(self, *a):
        pass

    def translate_path(self, path):
        p = super().translate_path(path.split("?")[0])
        if os.path.isfile(p) or os.path.isdir(p):
            return p
        if os.path.isfile(p + ".html"):
            return p + ".html"
        return os.path.join(DIST, "index.html")


def _fake_setup_handler(nonce, already_provisioned):
    """Mirrors surfaces/desktop/setup.js's /setup/state|log|engines shape.
    `already_provisioned=True` reports the exact laptop scenario: the daemon
    answers from the very first poll, with nothing installed by US (running
    and done both false) - Python + Claude were already on the machine."""

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            from urllib.parse import urlparse, parse_qs
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            if qs.get("n", [None])[0] != nonce:
                return self._send(403, {"error": "forbidden"})
            if u.path == "/setup/state":
                return self._send(200, {
                    "python": True, "pythonBundled": False,
                    "claude": True, "claudeVersion": "2.0",
                    "daemon": True,
                    "running": False, "done": False,
                })
            if u.path == "/setup/log":
                return self._send(200, {"log": [], "running": False, "done": False})
            if u.path == "/setup/engines":
                return self._send(200, {"engines": [
                    {"id": "claude", "label": "Claude Code", "tier": "full", "installed": True, "version": "2.0"},
                ]})
            return self._send(404, {"error": "not found"})

        def _send(self, code, body):
            b = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b)

    return H


def main():
    if not os.path.isdir(DIST):
        print("SKIP: no %s - run `npm --prefix surfaces/app run build:web` first" % DIST)
        return 0
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright not installed")
        return 0

    print("onboarding gate: daemon already up on tick 1, nothing to provision")

    shutil.rmtree(WORKTREE, ignore_errors=True)
    subprocess.run(["git", "worktree", "add", "--detach", WORKTREE, "HEAD"],
                    cwd=ROOT, check=True, capture_output=True)
    daemon_port = free_port()
    daemon = subprocess.Popen(
        [sys.executable, "-m", "daemon.swarm", "serve", str(daemon_port)],
        cwd=WORKTREE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_http("http://127.0.0.1:%d/auth/state" % daemon_port), "sandbox daemon never came up"
        auth_state = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/auth/state" % daemon_port).read())
        check(auth_state.get("setup_needed") is True, "sandbox daemon has no owner account yet (setup_needed)")

        web_port = free_port()
        socketserver.TCPServer.allow_reuse_address = True
        web_srv = socketserver.TCPServer(("127.0.0.1", web_port),
                                          functools.partial(_StaticSPA, directory=DIST))
        threading.Thread(target=web_srv.serve_forever, daemon=True).start()

        nonce = "test-nonce"
        setup_port = free_port()
        setup_srv = socketserver.TCPServer(("127.0.0.1", setup_port), _fake_setup_handler(nonce, True))
        threading.Thread(target=setup_srv.serve_forever, daemon=True).start()

        import base64
        cfg = {"baseUrl": "http://localhost:%d" % daemon_port,
               "setup": {"port": setup_port, "nonce": nonce}}
        b64 = base64.b64encode(json.dumps(cfg).encode()).decode()

        NORMAL_APP_ONLY = ("/tracks", "/cells", "/dashboard/data")
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(viewport={"width": 1360, "height": 900})
            seen = []
            page.on("request", lambda r: seen.append(r.url))
            page.goto("http://127.0.0.1:%d/?v=1#cfg=%s" % (web_port, b64), wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            body = page.inner_text("body")
            page.screenshot(path=os.path.join(SHOTS, "onboard-already-provisioned.png"), full_page=True)

            # The app must not be stuck: SOME real screen is showing, not a
            # blank canvas (useCacheGate's pre-hydrate placeholder).
            check(len(body.strip()) > 20, "the page rendered real content, not a blank canvas")
            check("Create the owner account" in body or "Owner-Konto anlegen" in body,
                  "reached the create-owner screen")
            # The actual regression: did it get there by mounting the normal
            # app tree first (pre-fix) or by going straight through onboarding
            # (post-fix)?
            hit = [u for u in seen if any(e in u for e in NORMAL_APP_ONLY)]
            check(not hit, "never requested a normal-app-only endpoint (%s)"
                  % (", ".join(sorted(set(hit))) or "none hit"))
            b.close()

        web_srv.shutdown()
        setup_srv.shutdown()
    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=10)
        except subprocess.TimeoutExpired:
            daemon.kill()
        subprocess.run(["git", "worktree", "remove", "--force", WORKTREE],
                        cwd=ROOT, capture_output=True)

    print()
    if _fails:
        print("FAILED: %d" % len(_fails))
        for f in _fails:
            print("  - " + f)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
