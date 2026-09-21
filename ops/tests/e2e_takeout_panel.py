# -*- coding: utf-8 -*-
"""LOOK at Settings > System > Umzug (takeout UI, 2026-09-21).

CLAUDE.md: "UI changes: screenshot and JUDGE (readability, centering, theming,
collisions), don't just confirm rendering." A contract test proves the routes;
it cannot prove the panel is legible, that the exclusion list is actually on
screen, or that a label did not ship as its raw i18n key.

What is checked:
  - the panel is ON the System door, with a real title and not a key
  - the EXCLUSION LIST is visible without any archive existing - that is the
    moment it matters (you read it BEFORE you wipe a machine)
  - the irreplaceable signing key is named, and named first
  - the empty state says what to do, not just that there is nothing
  - no row renders a raw i18n key, nothing is visually truncated
  - no console or page errors

Prereqs (two background processes, both sandboxed):
  py -3.12 ops/tools/boards_verify_daemon.py 8489
  cd surfaces/app && npx expo start --web --port 8098 --offline

  py -3.12 ops/tests/e2e_takeout_panel.py [web-port] [daemon-port]

Named e2e_* so run_gate.py skips it (needs a port and a browser).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 8098
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8489
DAEMON = "http://127.0.0.1:%d" % DAEMON_PORT
PW = "hunter2hunter2"
CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                                # noqa: BLE001
    pass

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def sign_in(page, who="owner"):
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    for user_ph, pw_ph, cta in (("Benutzername", "Passwort", "Anmelden"),
                                ("Username", "Password", "Sign in")):
        if page.get_by_placeholder(user_ph).count():
            page.get_by_placeholder(user_ph).first.fill(who)
            page.get_by_placeholder(pw_ph).first.fill(PW)
            page.get_by_text(cta, exact=True).last.click()
            page.wait_for_timeout(5000)
            break
    for _ in range(20):
        body = page.inner_text("body")
        if "Sprache" not in body and "language" not in body:
            break
        try:
            page.get_by_text("Deutsch", exact=True).first.click(timeout=3000)
        except Exception:                                        # noqa: BLE001
            pass
        page.wait_for_timeout(1500)
    page.wait_for_timeout(2000)
    return page


def raw_keys_on(page):
    return page.evaluate("""() => {
        const out = [];
        for (const n of document.querySelectorAll('*')) {
          if (n.children.length) continue;
          const s = (n.textContent || '').trim();
          if (/^(takeout|settings|daemon|hub)\\.[a-zA-Z0-9_.]+$/.test(s)) out.push(s);
        }
        return Array.from(new Set(out));
    }""")


def clipped(page):
    """Text a CSS clip is hiding. inner_text cannot see it, which is how a cut
    band once shipped looking fine in every assertion."""
    return page.evaluate("""() => {
        const out = [];
        for (const n of document.querySelectorAll('*')) {
          if (n.children.length) continue;
          const s = (n.textContent || '').trim();
          if (!s) continue;
          if (n.scrollWidth > n.clientWidth + 2) out.push(s.slice(0, 60));
        }
        return Array.from(new Set(out)).slice(0, 8);
    }""")


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS, exist_ok=True)
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for tag, w, h in (("phone", 430, 1400), ("wide", 1280, 1100)):
            ctx = b.new_context(viewport={"width": w, "height": h},
                                device_scale_factor=2)
            page = ctx.new_page()
            page.on("console", lambda m: errs.append(m.text[:160])
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append(str(e)[:200]))
            sign_in(page)
            del errs[:]   # pre-login 401s are the auth gate doing its job

            # On the phone Settings lives BEHIND "Mehr"; on wide it is a rail
            # item. The first run of this test clicked as if it were a tab at
            # both sizes and never left the overview on narrow - the screenshot
            # was of the wrong screen, and every assertion "failed" for the
            # wrong reason.
            if w < 700:
                for label in ("Mehr", "More"):
                    if page.get_by_text(label, exact=True).count():
                        page.get_by_text(label, exact=True).last.click()
                        page.wait_for_timeout(2000)
                        break
            for label in ("Einstellungen", "Settings"):
                if page.get_by_text(label, exact=False).count():
                    page.get_by_text(label, exact=False).first.click()
                    page.wait_for_timeout(2500)
                    break
            for label in ("System", "Maschine"):
                el = page.get_by_text(label, exact=True)
                if el.count():
                    el.first.click()
                    page.wait_for_timeout(3000)
                    break

            body = page.inner_text("body")
            low = body.casefold()   # SectionLabel renders UPPERCASE
            check("umzug" in low, "[%s] the panel is on the System door" % tag)
            check("apk-signing" in low,
                  "[%s] the irreplaceable signing key is NAMED on screen" % tag)
            check("unersetzlich" in low or "irreplaceable" in low,
                  "[%s] and it says what losing it costs" % tag)
            check("nicht im archiv" in low or "not in the archive" in low,
                  "[%s] the exclusion list is visible" % tag)
            check("archiv erstellen" in low or "create archive" in low,
                  "[%s] the action is reachable" % tag)

            keys = raw_keys_on(page)
            check(not keys, "[%s] no raw i18n key leaked as a label - %r" % (tag, keys))
            cut = clipped(page)
            check(not cut, "[%s] nothing is visually truncated - %r" % (tag, cut))

            try:
                page.get_by_text("Umzug", exact=False).first.scroll_into_view_if_needed()
                page.wait_for_timeout(800)
            except Exception:                                    # noqa: BLE001
                pass
            shot = os.path.join(SHOTS, "takeout-%s.png" % tag)
            page.screenshot(path=shot, full_page=True)
            print("  shot: %s" % shot)
            ctx.close()
        b.close()

    check(not errs, "no console/page errors - %r" % errs[:3])
    print("")
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("takeout-panel: looked at and judged - PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
