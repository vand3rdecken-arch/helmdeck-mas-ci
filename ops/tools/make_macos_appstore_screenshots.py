# -*- coding: utf-8 -*-
"""Capture real macOS App Store screenshots from the actual React UI (the ONE
frontend surfaces/app ships to phone/web/desktop) against the sandboxed
boards_verify_daemon - same recipe as ops/tests/e2e_boards_ui.py's sign_in()/
open_board(), reused here for pixels instead of assertions so nothing in the
shot is invented or is a real/private board.

Viewport 1280x800 @2x = 2560x1600 output, one of Apple's exact accepted mac
screenshot canvases (no crop/pad needed).

Prereqs (both already running when this was written):
  py -3.12 ops/tools/boards_verify_daemon.py 8149
  cd surfaces/app && npx expo start --web --port 8199

  py -3.12 ops/tools/make_macos_appstore_screenshots.py [web-port] [daemon-port]
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "ops", "docs", "store", "screenshots", "appstore", "macos-1280x800")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 8199
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8149
DAEMON = "http://127.0.0.1:%d" % DAEMON_PORT
PW = "hunter2hunter2"

from playwright.sync_api import sync_playwright  # noqa: E402

CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})


def sign_in(page):
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded", timeout=180000)
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded", timeout=180000)
    page.wait_for_timeout(4000)
    for user_ph, pw_ph, cta in (("Benutzername", "Passwort", "Anmelden"),
                                ("Username", "Password", "Sign in")):
        if page.get_by_placeholder(user_ph).count():
            page.get_by_placeholder(user_ph).first.fill("owner")
            page.get_by_placeholder(pw_ph).first.fill(PW)
            page.get_by_text(cta, exact=True).last.click()
            page.wait_for_timeout(5000)
            break
    for _ in range(20):
        if "Sprache" not in page.inner_text("body") and "language" not in page.inner_text("body"):
            break
        try:
            page.get_by_text("Deutsch", exact=True).first.click(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
    page.wait_for_timeout(2500)


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
        page = ctx.new_page()
        sign_in(page)

        page.screenshot(path=os.path.join(OUT, "01-dashboard.png"))
        print("wrote 01-dashboard.png")

        page.goto("http://127.0.0.1:%d/board" % WEB, wait_until="domcontentloaded", timeout=180000)
        page.wait_for_timeout(5000)
        page.screenshot(path=os.path.join(OUT, "02-board.png"))
        print("wrote 02-board.png")

        try:
            page.get_by_text("Relay-Reconnect härten", exact=True).first.click(timeout=5000)
            page.wait_for_timeout(3000)
            page.screenshot(path=os.path.join(OUT, "03-card.png"))
            print("wrote 03-card.png")
        except Exception as e:
            print("!!! card-detail shot skipped: %r" % e)

        b.close()


if __name__ == "__main__":
    main()
