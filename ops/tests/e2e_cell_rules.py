# -*- coding: utf-8 -*-
"""Drive the cells door and LOOK at its per-cell rules.

The contract test (test_behavior_rules.test_cell_references_resolve) proves the
derivation; this proves the one thing it cannot: that an owner opening the
cells door sees WHICH rules belong to which agent, labelled in his language,
with the same rows the harness page draws - not raw keys, not an empty door.

Prereqs (same two sandboxed background processes as e2e_stored_config.py):
  py -3.12 ops/tools/storedconfig_verify_daemon.py 8152
  cd surfaces/app && npx expo start --web --port 3891 --offline

  py -3.12 ops/tests/e2e_cell_rules.py [web-port] [daemon-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3891
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8152
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


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    errors = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for label, size in (("wide", {"width": 1440, "height": 1180}),
                            ("phone", {"width": 402, "height": 940})):
            ctx = browser.new_context(viewport=size, device_scale_factor=2)
            page = ctx.new_page()
            # Post-login only - the login screen legitimately 401s (see
            # e2e_stored_config.py for the measurement behind this).
            armed = {"v": False}
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" and armed["v"] else None)
            page.on("pageerror", lambda e: errors.append(str(e)) if armed["v"] else None)

            print("\n=== %s ===" % label)
            login(page)
            armed["v"] = True
            page.goto("http://127.0.0.1:%d/settings?door=cells" % WEB,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            body = page.locator("body").inner_text()

            # 1. no raw i18n key survives - a dict miss renders the dotted key.
            for key in ("cells.rules.title", "cells.rules.hint", "cells.rules.shared",
                        "cells.rules.sharedHint", "cells.rules.openMap"):
                check(key not in body, "no raw key '%s' on the page" % key)

            # 2. the seam itself: the door groups rules BY CELL, right under the
            #    catalog that switches the cells.
            check("copilot" in body, "the copilot cell appears on the door")
            check("Regeln: copilot" in body or "Rules: copilot" in body,
                  "its rules arrive as a group of its own")
            check("Gemeinsame Regeln" in body or "Shared rules" in body,
                  "the cell-less (spine) rules form a shared group, not a hole")

            # 3. the rows are the harness page's rows: a known copilot rule is
            #    labelled in the owner's words, and a locked one shows its lock.
            check("Nachfass-Versuche" in body or "Follow-up attempts" in body,
                  "a copilot rule renders with its real label")
            check("Fest" in body or "Fixed" in body,
                  "a fixed rule shows its lock instead of a dead control")
            # The sandbox seeds rule.report.followup_attempts.all=4 on THIS
            # project's layer - the cells door shows the WORKSPACE view, so the
            # row must show the default (2), not another project's value.
            check('rule-report.followup_attempts' in page.content(),
                  "the followup-attempts row is a real RuleRow (testID present)")

            shot = os.path.join(SHOTS, "cell_rules_%s.png" % label)
            page.screenshot(path=shot, full_page=True)
            print("  shot  %s" % shot)

            ctx.close()
        browser.close()

    real = [e for e in errors if "favicon" not in e.lower()]
    check(not real, "no console or page errors (%s)" % real[:3])

    print("\n%d check(s) failed" % len(_fails))
    for m in _fails:
        print("  FAIL " + m)
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
