# -*- coding: utf-8 -*-
"""Drive the REAL harness screen and LOOK at it (harness-config-ui phase 3).

The contract tests prove the data and the route. What they cannot prove is the
thing the owner actually complained about: that Henry's rules are VISIBLE and
CHANGEABLE on a screen. Three failure modes in this card are invisible to every
test that does not open a browser:

  1. A rule row rendering its own i18n KEY ("rule.tone.length") instead of a
     label. Phase 2 declared 64 keys and shipped none of them, so this is not a
     hypothetical - it is the state this card found.
  2. A knob that MOVED out of its door and did not arrive at its station. The
     placement functions drop a row they do not match, silently, so a botched
     move looks exactly like a screen that renders fine.
  3. A write that reports success while the row does not move - the whole point
     of the inheritance badge is that the owner can SEE which layer answered.

What is checked, at both form factors:
  - the navigation carries the daemon's stations AND Henry's five blocks
  - opening a block shows real labels and one-sentence descriptions, and NO row
    renders a raw key
  - a locked rule shows a lock with its reason and its source file, never a
    dead control
  - THE ROUND TRIP: toggle a rule -> the badge flips to "gesetzt" -> reset ->
    the badge returns to inherited. Driven through the UI, read back off the UI.
  - the four MOVED knobs are on their station page and GONE from their old
    doors (the "kein Knopf an zwei Orten" acceptance, checked in both places)
  - tapping a station on the pipeline selects it in the navigation
  - nothing is visually truncated (scrollWidth vs clientWidth - inner_text
    cannot see a CSS clip, which is how the phase-4 band shipped cut off)
  - no console or page errors

Prereqs (two background processes, both sandboxed):
  py -3.12 ops/tools/boards_verify_daemon.py 8487
  cd surfaces/app && npx expo start --web --port 3887 --offline

  py -3.12 ops/tests/e2e_harness_screen.py [web-port] [daemon-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3887
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8487
DAEMON = "http://127.0.0.1:%d" % DAEMON_PORT
PW = "hunter2hunter2"

CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})

# The page's own text lands in these messages, and a toggle renders a U+2713.
# Windows' default cp1252 stdout raises on it, which kills the run MID-SUITE and
# looks exactly like a crash in the thing under test.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                            # noqa: BLE001
    pass

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def sign_in(page, who="owner"):
    """Same flow as e2e_pipeline_track.py's - kept in step with it on purpose."""
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
        except Exception:
            pass
        page.wait_for_timeout(1500)
    page.wait_for_timeout(2000)
    return page


def raw_keys_on(page):
    """Any i18n key that leaked onto the screen as its own label. The single
    highest-value assertion in this file: a missing dict entry renders the key,
    which looks like a typo in a screenshot and like nothing at all in a test
    that only asserts the row EXISTS."""
    return page.evaluate("""() => {
        const out = [];
        for (const n of document.querySelectorAll('*')) {
          if (n.children.length) continue;
          const s = (n.textContent || '').trim();
          if (/^(rule|harness|hub|cfg|loopmap)\\.[a-zA-Z0-9_.]+$/.test(s)) out.push(s);
        }
        return Array.from(new Set(out));
    }""")


def clipped_on(page, sel):
    """Text the browser says did not fit. numberOfLines clips with CSS, so the
    DOM keeps the whole word while the screen shows an ellipsis - the phase-4
    band shipped truncated under a GREEN inner_text assertion."""
    return page.evaluate("""(sel) => {
        const out = [];
        for (const el of document.querySelectorAll(sel)) {
          for (const n of el.querySelectorAll('*')) {
            if (n.children.length === 0 && n.textContent.trim()
                && n.scrollWidth > n.clientWidth + 1) {
              out.push((el.getAttribute('data-testid') || el.tagName) + ': '
                       + n.textContent.trim());
            }
          }
        }
        return out;
    }""", sel)


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    errors = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for form, size in (("desktop", {"width": 1400, "height": 1000}),
                           ("phone", {"width": 430, "height": 900})):
            ctx = browser.new_context(viewport=size)
            page = ctx.new_page()
            page.set_default_navigation_timeout(180000)
            page.set_default_timeout(60000)
            sign_in(page)
            # Listeners AFTER the handshake: the app boots tokenless and probes,
            # so a 401 before sign-in is the shape of the login flow, not a
            # defect. Counting it would make this permanently red and worthless.
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            # The URL too, not just the message: "Failed to load resource" names
            # no resource, and a long-poll cut at teardown looks identical to a
            # route that 500s until you can see which one it was.
            page.on("requestfailed",
                    lambda r: errors.append("REQFAIL %s %s" % (r.url, r.failure)))
            page.goto("http://127.0.0.1:%d/loopmap" % WEB, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)

            print("\n[%s %dx%d]" % (form, size["width"], size["height"]))

            # -- the navigation, from the daemon's own lists ------------------
            for st in ("backlog", "working", "gate", "review", "deploy"):
                check(page.locator('[data-testid="nav-st-%s"]' % st).count() > 0,
                      "%s: station %s is in the navigation" % (form, st))
            for blk in ("tone", "initiative", "hands", "report", "memory"):
                check(page.locator('[data-testid="nav-blk-%s"]' % blk).count() > 0,
                      "%s: Henry block %s is in the navigation" % (form, blk))

            # -- a Henry block, opened ----------------------------------------
            page.locator('[data-testid="nav-blk-tone"]').first.click()
            page.wait_for_timeout(1500)
            body = page.inner_text("body")
            check("Antwortlänge" in body, "%s: the length rule renders its LABEL" % form)
            check("Anrede" in body, "%s: the address rule renders its label" % form)
            check("gesprochen und auf der Uhr" in body,
                  "%s: the one-sentence description renders" % form)
            leaked = raw_keys_on(page)
            check(not leaked, "%s: no row renders a raw i18n key (%s)" % (form, leaked[:3] or "none"))

            # the per-surface detail - the whole reason this screen exists
            check(page.locator('[data-testid="rule-surfaces-tone.length"]').count() > 0,
                  "%s: the length rule offers its per-surface detail" % form)
            page.locator('[data-testid="rule-surfaces-tone.length"]').first.click()
            page.wait_for_timeout(800)
            body = page.inner_text("body")
            check("Uhr" in body and "Sprache" in body,
                  "%s: the four surfaces are named side by side" % form)

            # a LOCKED rule shows its reason, not a dead control
            check(page.locator('[data-testid="rule-tone.examples"]').count() > 0,
                  "%s: the fixed example-dialogues rule is shown" % form)
            lock = page.locator('[data-testid="rule-tone.examples"]').first.inner_text()
            # The badge is rendered .toUpperCase(), so match case-insensitively
            # rather than pinning the casing - the assertion is about the row
            # SAYING it is fixed, not about a text-transform.
            check("fest" in lock.lower(), "%s: it is marked fixed" % form)
            check("board-copilot.md" in lock,
                  "%s: and cites the file that holds it (%r)" % (form, lock[-60:]))

            # -- THE ROUND TRIP ------------------------------------------------
            # Toggle a workspace rule and read the badge back off the screen.
            # Start from a KNOWN state. The sandbox daemon outlives a single run
            # of this file (that is the point - a failed run stays inspectable),
            # so a rule left set by the previous run would make "starts
            # inherited" fail for a reason that has nothing to do with the code.
            row = page.locator('[data-testid="rule-tone.humor"]').first
            if page.locator('[data-testid^="rule-reset-rule.tone.humor"]').count():
                page.locator('[data-testid^="rule-reset-rule.tone.humor"]').first.click()
                page.wait_for_timeout(2500)
            before = page.locator('[data-testid="rule-tone.humor"]').first.inner_text()
            check("Standard" in before,
                  "%s: the humour rule starts at its default (%r)" % (form, before[:70]))
            row.locator("text=Trockener Humor").first.click()
            page.wait_for_timeout(2500)
            after = page.locator('[data-testid="rule-tone.humor"]').first.inner_text()
            # "gesetzt", not "geerbt": tone.humor IS a workspace rule, so the
            # workspace is where it lives. Badging a value the owner had just
            # changed as inherited is the bug this assertion exists to hold shut.
            check("Für den Arbeitsbereich gesetzt" in after,
                  "%s: after the write the badge says SET, not inherited (%r)"
                  % (form, after[:110]))
            check("zurücksetzen" in after,
                  "%s: and a way back appears - a set row offers exactly one" % form)
            page.locator('[data-testid^="rule-reset-rule.tone.humor"]').first.click()
            page.wait_for_timeout(2500)
            back = page.locator('[data-testid="rule-tone.humor"]').first.inner_text()
            check("zurücksetzen" not in back,
                  "%s: reset restores inheritance, the link goes away (%r)" % (form, back[:90]))

            check(not clipped_on(page, '[data-testid^="rule-"]'),
                  "%s: no rule row is visually truncated (%s)"
                  % (form, clipped_on(page, '[data-testid^="rule-"]') or "none"))
            if form == "desktop":
                page.screenshot(path=os.path.join(SHOTS, "harness-rules-%s.png" % form))

            # -- the MOVED knobs are at their station --------------------------
            # inner_text returns the RENDERED text, and a section heading is
            # text-transform: uppercase - so compare case-insensitively rather
            # than pinning a CSS decision into the assertion.
            page.locator('[data-testid="nav-st-backlog"]').first.click()
            page.wait_for_timeout(2500)
            body = page.inner_text("body").lower()
            check("wann eine karte losläuft" in body,
                  "%s: the moved knobs arrived under their own section" % form)
            check("auto-dispatch ab priorität" in body,
                  "%s: and render as real controls, not as links elsewhere" % form)
            # The chip pointing at door Automation must be GONE for a knob that
            # now renders right here - after the move it named a door the knob
            # had left, while the control sat directly underneath it.
            check("im automatik-hub ändern" not in body,
                  "%s: no knob on this page still points at the old door" % form)
            page.locator('[data-testid="nav-st-review"]').first.click()
            page.wait_for_timeout(2000)
            check("wenn die arbeit fertig ist" in page.inner_text("body").lower(),
                  "%s: the acceptance station carries its knob" % form)

            # -- the pipeline IS the table of contents -------------------------
            page.locator('[data-testid="station-gate"]').first.click()
            page.wait_for_timeout(1500)
            sel = page.evaluate("""() => {
                const el = document.querySelector('[data-testid="nav-st-gate"]');
                if (!el) return "missing";
                return el.textContent.trim();
            }""")
            check(sel != "missing", "%s: tapping the pipeline reaches the nav entry" % form)
            check("Quality" in page.inner_text("body") or "Gate" in page.inner_text("body"),
                  "%s: and the gate's detail is what is shown" % form)

            shot = os.path.join(SHOTS, "harness-screen-%s.png" % form)
            page.screenshot(path=shot, full_page=False)
            print("  shot   " + shot)
            ctx.close()

        # -- no knob is editable in TWO places ------------------------------
        # Checked in the door the knobs LEFT, not only in the station they
        # arrived at: "kein Knopf ist an zwei Orten editierbar" is a claim about
        # the old place, and only looking at the new one would never catch it.
        ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        page.set_default_navigation_timeout(180000)
        page.set_default_timeout(60000)
        sign_in(page)
        page.goto("http://127.0.0.1:%d/settings?door=automation" % WEB,
                  wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        auto = page.inner_text("body").lower()
        check("wann eine karte losläuft" not in auto,
              "the moved section is GONE from door Automation")
        check("auto-dispatch ab priorität" not in auto,
              "and so is the knob itself - no key is editable in two places")
        page.screenshot(path=os.path.join(SHOTS, "harness-door-automation.png"))
        ctx.close()
        browser.close()

    # /stream/wait is the SSE long-poll and /presence the activity beacon: both
    # are open when the context closes, so both ALWAYS abort at teardown. Named
    # explicitly rather than filtering ERR_ABORTED wholesale - a genuine failure
    # on any other route still fails this check, which is the point of having it.
    def teardown(e):
        low = e.lower()
        return ("favicon" in low
                or (("/stream/wait" in low or "/presence" in low) and "err_aborted" in low))
    real = [e for e in errors if not teardown(e)]
    check(not real, "no console/page errors (%s)" % (real[:3] or "none"))
    print("\n%d failure(s)" % len(_fails))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
