# -*- coding: utf-8 -*-
"""LOOK at the merged engineer cell's tab gating (process+connectors merge,
owner directive 2026-09-03): ONE switch (engineerEnabled) must hide THREE
navigation entries - Board, Prozesse, Connectoren - because the merged cell
now declares its absorbed systems' surfaces (Cell.surfaces, manifest
"surfaces" list, _layout.tsx iterating it).

This is the one claim the python tests cannot prove: the daemon can serve a
perfect surfaces list and the app can still hide only surfaces.board if the
client iterates the singular field. Only a browser shows the tabs.

Prereqs:
  py -3.12 ops/tools/storedconfig_verify_daemon.py 8154
  cd surfaces/app && npx expo start --web --port 3892 --offline

  py -3.12 ops/tests/e2e_cell_tab_gating.py [web-port] [daemon-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3892
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8154
DAEMON = "http://127.0.0.1:%d" % DAEMON_PORT
PW = "hunter2hunter2"

CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                            # noqa: BLE001
    pass

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def login(page):
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    for sel in ('input[placeholder*="ame"]', 'input[type="text"]'):
        if page.locator(sel).count():
            page.locator(sel).first.fill("owner")
            break
    page.locator('input[type="password"]').first.fill(PW)
    page.keyboard.press("Enter")
    page.wait_for_timeout(3500)
    # First-ever login on a fresh sandbox account shows the one-time language
    # picker ("In welcher Sprache?") before the app - dismiss it or every
    # later body-text assertion runs against that screen instead.
    deutsch = page.get_by_text("Deutsch", exact=True)
    if deutsch.count():
        deutsch.first.click()
        page.wait_for_timeout(2000)


def swap(token, patch, note):
    import urllib.request
    req = urllib.request.Request(
        DAEMON + "/policy/swap",
        data=json.dumps({"section": "policies", "patch": patch,
                         "actor": "user", "note": note}).encode(),
        method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + token)
    urllib.request.urlopen(req, timeout=10)


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # Desktop: the sidebar lists every nav surface by label.
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000},
                                  device_scale_factor=2)
        page = ctx.new_page()
        login(page)
        token = json.loads(page.evaluate(
            "() => localStorage.getItem('helmdeck.config')") or "{}").get("token", "")

        # 1. daemon truth: three cells, engineer carries the full surface list.
        import urllib.request
        req = urllib.request.Request(DAEMON + "/cells")
        req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=10) as r:
            manifest = json.loads(r.read().decode())
        ids = {c["id"] for c in manifest.get("cells", [])}
        check(ids == {"engineer", "copilot", "buildloop"},
              "GET /cells: exactly three cells (got %s)" % sorted(ids))
        eng = next((c for c in manifest["cells"] if c["id"] == "engineer"), {})
        check(set(eng.get("surfaces") or []) == {"surfaces.board",
              "surfaces.processes", "surfaces.connectors"},
              "engineer's manifest carries the full surface list")

        # 2. all three tabs visible while engineer is on.
        body = page.locator("body").inner_text()
        for label in ("Board", "Prozesse", "Connectoren"):
            check(label in body, "tab %r visible while engineer is on" % label)
        page.screenshot(path=os.path.join(SHOTS, "tab_gating_on.png"))
        print("  shot  " + os.path.join(SHOTS, "tab_gating_on.png"))

        # 3. ONE switch off -> all three gone (the surfaces-list gating).
        swap(token, {"engineerEnabled": False}, "e2e tab gating")
        try:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            body_off = page.locator("body").inner_text()
            for label in ("Board", "Prozesse", "Connectoren"):
                check(label not in body_off,
                      "tab %r HIDDEN while engineer is off" % label)
            # the coordinator's world is untouched by the builder's switch
            check("Einstellungen" in body_off or "Settings" in body_off,
                  "the rest of the nav survives (not a global hide)")
            page.screenshot(path=os.path.join(SHOTS, "tab_gating_off.png"))
            print("  shot  " + os.path.join(SHOTS, "tab_gating_off.png"))
        finally:
            swap(token, {"engineerEnabled": True}, "restore")

        ctx.close()
        browser.close()

    print("\n%d check(s) failed" % len(_fails))
    for m in _fails:
        print("  FAIL " + m)
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
