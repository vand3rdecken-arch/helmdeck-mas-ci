# -*- coding: utf-8 -*-
"""Emergency regression LOOK: owner reported "alle Buttons und Einstellungen
scheinen kaputt zu sein" and "kein Prozess wirklich erstellen" after today's
process-template + rbac work. Screenshots the real screens against a real
sandbox daemon to find out what's actually broken, before guessing.

  py -3.12 ops/tests/shot_regression_check.py [web-port] [daemon-port]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3895
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8158
DAEMON = "http://127.0.0.1:%d" % DAEMON_PORT
PW = "hunter2hunter2"
CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

console_errors = []


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 900, "height": 1400},
                                  device_scale_factor=2)
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append("PAGEERROR: " + str(e)))

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
        deutsch = page.get_by_text("Deutsch", exact=True)
        if deutsch.count():
            deutsch.first.click()
            page.wait_for_timeout(2000)

        # 1. Board (the landing screen)
        page.wait_for_timeout(2000)
        page.screenshot(path=os.path.join(SHOTS, "regcheck_1_board.png"))
        print("  shot  regcheck_1_board.png")

        # 2. Settings hub root
        page.goto("http://127.0.0.1:%d/settings" % WEB, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(SHOTS, "regcheck_2_settings_root.png"))
        print("  shot  regcheck_2_settings_root.png")

        # 3. Settings -> cells door
        page.goto("http://127.0.0.1:%d/settings?door=cells" % WEB, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.screenshot(path=os.path.join(SHOTS, "regcheck_3_settings_cells.png"))
        print("  shot  regcheck_3_settings_cells.png")

        # 4. Processes screen - the one the owner said is actually broken
        page.goto("http://127.0.0.1:%d/processes" % WEB, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(SHOTS, "regcheck_4_processes.png"))
        print("  shot  regcheck_4_processes.png")

        # 5. Try to actually create a process, like the owner described.
        ta = page.locator("textarea, input[type='text']").last
        if ta.count():
            ta.fill("Testprozess fuer den Regressions-Check")
        btn = page.get_by_text("Schritte vorschlagen", exact=False)
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(SHOTS, "regcheck_5_process_create_attempt.png"))
        print("  shot  regcheck_5_process_create_attempt.png")

        ctx.close()
        browser.close()

    print()
    print("console/page errors captured: %d" % len(console_errors))
    for e in console_errors[:40]:
        print("  ERR:", e[:300])


if __name__ == "__main__":
    main()
