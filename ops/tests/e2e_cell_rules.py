# -*- coding: utf-8 -*-
"""Drive the harness page's CELLS section and LOOK at it.

The contract test (test_behavior_rules.test_cell_references_resolve) proves the
derivation; this proves the one thing it cannot: that an owner opening the
harness page sees the agents IN the harness - each with its switch, and,
selected, the rules that govern it, labelled in his language with the same
rows the theme blocks draw.

Prereqs (same two sandboxed background processes as e2e_stored_config.py):
  py -3.12 ops/tools/storedconfig_verify_daemon.py 8152
  cd surfaces/app && npx expo start --web --port 3891 --offline

  py -3.12 ops/tests/e2e_cell_rules.py [web-port] [daemon-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import json
import os
import re
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


def has(body, needle):
    """Case-insensitive contains: SectionLabel/NavGroup render with CSS
    text-transform uppercase, and Chromium's innerText reflects that."""
    return needle.lower() in body.lower()


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
            page.goto("http://127.0.0.1:%d/loopmap" % WEB, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            body = page.locator("body").inner_text()

            # 1. the navigation carries the cells, right on the harness page
            check(has(body, "Zellen") or has(body, "Cells"),
                  "the navigation carries a cells group")
            nav = page.locator('[data-testid="nav-cell-copilot"]')
            check(nav.count() > 0, "the copilot cell is a navigation entry")
            if nav.count():
                nav.first.click()
                page.wait_for_timeout(1500)
            body = page.locator("body").inner_text()

            # 2. no raw i18n key survives - a dict miss renders the dotted key.
            for key in ("harness.navCells", "harness.cellHint", "harness.cellNoRules"):
                check(key not in body, "no raw key '%s' on the page" % key)

            # 3. the detail pane: switch + rules together
            check(has(body, "copilot"), "the cell header is shown")
            check(page.locator('input[type="checkbox"], [role="switch"]').count() > 0,
                  "the cell's enable switch is a real control")
            check(has(body, "Nachfass-Versuche") or has(body, "Follow-up attempts"),
                  "a copilot rule renders with its real label")
            check(has(body, "Fest") or has(body, "Fixed"),
                  "a fixed rule shows its lock instead of a dead control")
            check('rule-report.followup_attempts' in page.content(),
                  "the followup-attempts row is a real RuleRow (testID present)")

            # 4. a cell WITHOUT rules says so instead of rendering a hole.
            # buildloop, not connectors: connectors merged into engineer
            # (2026-09-03) and is no longer its own nav-cell entry.
            nav2 = page.locator('[data-testid="nav-cell-buildloop"]')
            check(nav2.count() > 0, "the buildloop cell is a navigation entry")
            if nav2.count():
                nav2.first.click()
                page.wait_for_timeout(1200)
                b2 = page.locator("body").inner_text()
                check(has(b2, "keine einstellbaren Regeln") or has(b2, "no adjustable rules"),
                      "a rule-less cell explains itself")
                nav.first.click()
                page.wait_for_timeout(1200)

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
