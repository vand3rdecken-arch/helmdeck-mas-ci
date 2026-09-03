# -*- coding: utf-8 -*-
"""LOOK at the settings hub's Zellen door after the buildloop reclassification
(owner decree 2026-09-03: 2 cells/ folders = 2 cells; buildLoopEnabled is a
seeded RULE now). Screenshots to JUDGE, not just render:
  - the cell list holds exactly engineer + copilot
  - the REGELN section carries the new Build-Loop toggle next to the others

Prereqs (same pair as e2e_cell_tab_gating.py):
  py -3.12 ops/tools/storedconfig_verify_daemon.py 8154
  cd surfaces/app && npx expo start --web --port 3892 --offline

  py -3.12 ops/tests/shot_cells_door.py [web-port] [daemon-port]

Named shot_* so nothing recurring picks it up (gate stays light).
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


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 900, "height": 1400},
                                  device_scale_factor=2)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
        page.evaluate("([k, v]) => localStorage.setItem(k, v)",
                      ["helmdeck.config", CFG])
        page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        for sel in ('input[placeholder*="ame"]', 'input[type="text"]'):
            if page.locator(sel).count():
                page.locator(sel).first.fill("owner")
                break
        page.locator('input[type="password"]').first.fill(PW)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3500)
        deutsch = page.get_by_text("Deutsch", exact=True)
        if deutsch.count():
            deutsch.first.click()
            page.wait_for_timeout(2000)

        page.goto("http://127.0.0.1:%d/settings?door=cells" % WEB,
                  wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        body = page.locator("body").inner_text()

        check("engineer" in body and "copilot" in body,
              "both real cells render")
        check("buildloop" not in body,
              "buildloop no longer renders as a cell")
        check("Build-Loop" in body or "Build loop" in body,
              "the Build-Loop RULE toggle renders in the rules section")
        check("Gate vor Review" in body or "Gate before review" in body,
              "the seeded rules section is present (Build-Loop sits among peers)")

        page.screenshot(path=os.path.join(SHOTS, "cells_door_top.png"))
        print("  shot  " + os.path.join(SHOTS, "cells_door_top.png"))
        # scroll the rules section into view for the second shot
        target = page.get_by_text("Build-Loop", exact=False)
        if target.count():
            target.first.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
        page.screenshot(path=os.path.join(SHOTS, "cells_door_rules.png"))
        print("  shot  " + os.path.join(SHOTS, "cells_door_rules.png"))
        ctx.close()
        browser.close()

    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        sys.exit(1)
    print("cells-door shots: PASS")


if __name__ == "__main__":
    main()
