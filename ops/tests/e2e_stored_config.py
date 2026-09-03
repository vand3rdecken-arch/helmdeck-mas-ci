# -*- coding: utf-8 -*-
"""Drive the "what is actually stored" view and LOOK at it.

The contract tests prove the reader and the route. What they cannot prove is
the only thing this panel exists for: that an owner opening it can TELL THE
FOUR STATES APART at a glance. Each of these is invisible to every test that
does not open a browser:

  1. a row rendering its own i18n key instead of a label (the phase-2 failure,
     which is why every new key here is checked by name)
  2. the ORPHAN badge reading as decoration rather than as a warning - the row
     it marks is a value the daemon has silently stopped honouring, and if it
     looks like every other row the panel has failed at its one job
  3. an unlabelled board column rendering as a blank gap, which reads as a bug
     rather than as "this column shows its station's own name"
  4. the refused legacy key being indistinguishable from a pending one

Prereqs (two background processes, both sandboxed - the second seeds all four
states on purpose, see the tool's own docstring):
  py -3.12 ops/tools/storedconfig_verify_daemon.py 8152
  cd surfaces/app && npx expo start --web --port 3891 --offline

  py -3.12 ops/tests/e2e_stored_config.py [web-port] [daemon-port]

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


def clipped(page):
    """Anything visually cut off. inner_text cannot see a CSS clip, which is how
    the phase-4 band shipped truncated - so this measures instead of reading."""
    return page.evaluate("""() => {
      const bad = [];
      for (const el of document.querySelectorAll('div,span,p')) {
        if (el.children.length) continue;
        if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 30)
          bad.push((el.innerText || '').slice(0, 60));
      }
      return bad.slice(0, 8);
    }""")


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
            # POST-LOGIN ONLY, and that is a real distinction rather than a way
            # to hide noise. The app mounts its queries before a token exists,
            # so the LOGIN screen legitimately produces 401s on /me, /tracks,
            # /presence, /dashboard/data, /stream/wait and a 403 on /cells -
            # measured, every run, on an unmodified build. Counting those would
            # make this check permanently red and therefore permanently ignored.
            # After login the count must be exactly zero, which is the assertion
            # worth having: verified 0 on both screens this card touches.
            armed = {"v": False}
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" and armed["v"] else None)
            page.on("pageerror", lambda e: errors.append(str(e)) if armed["v"] else None)

            print("\n=== %s ===" % label)
            login(page)
            armed["v"] = True
            page.goto("http://127.0.0.1:%d/loopmap" % WEB, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            nav = page.locator('[data-testid="nav-stored"]')
            check(nav.count() > 0, "the navigation carries a 'Gespeicherte Werte' entry")
            if nav.count():
                nav.first.click()
                page.wait_for_timeout(1500)

            body = page.locator("body").inner_text()

            # 1. no raw i18n key survives. Every string this panel adds is
            #    checked BY NAME - a dict miss renders the dotted key, which
            #    looks like a label until you read it.
            for key in ("stored.title", "stored.intro", "stored.boards",
                        "stored.undeclared", "stored.thisProject",
                        "stored.emptyLabel", "stored.legacy", "stored.refused",
                        "harness.navStored"):
                check(key not in body, "no raw key '%s' on the page" % key)

            # 2. the four seeded states are each legible
            check("rule.report.followup_attempts.all" in body,
                  "a row for the SELECTED project is listed")
            check("rule.initiative.estimate.pm" in body,
                  "a row for a project this screen is NOT resolving is listed too")
            check("rule.report.retired_knob.all" in body,
                  "the orphaned row is listed rather than filtered out")
            check("verwaist" in body or "orphaned" in body,
                  "and it is BADGED as orphaned, not shown as an ordinary row")
            check("still on disk" in body, "its stored value is shown verbatim")

            # 3. the board scope's real store, incl. the deliberately empty label
            check("Inbox" in body and "In Arbeit" in body,
                  "the board's stored column labels are shown")
            check("Stationsname" in body or "station name" in body,
                  "an EMPTY column label reads as 'show the station's own name', "
                  "not as a blank gap")

            # 4. the refused legacy key says WHY
            check("henry_permission_mode" in body, "the unadopted legacy key is listed")
            check("abgelehnt" in body or "refused" in body,
                  "and it is marked refused rather than merely pending")
            check("plan, acceptEdits" in body,
                  "with the validator's own reason, so the owner can fix it")

            cut = clipped(page)
            check(not cut, "nothing is visually truncated (%s)" % cut)

            shot = os.path.join(SHOTS, "stored_config_%s.png" % label)
            page.screenshot(path=shot, full_page=True)
            print("  shot  %s" % shot)

            # The Boards door, where the badge that started all this now has to
            # tell the truth: the per-board labels under "Board", the station
            # registry under "Workspace".
            page.goto("http://127.0.0.1:%d/settings?door=boards" % WEB,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            bbody = page.locator("body").inner_text()
            check("Inbox" in bbody,
                  "the Boards door shows the board's OWN column labels, not a count")
            check("Workspace" in bbody,
                  "the station-name registry is badged Workspace (it was 'Board')")
            bshot = os.path.join(SHOTS, "boards_door_%s.png" % label)
            page.screenshot(path=bshot, full_page=True)
            print("  shot  %s" % bshot)

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
