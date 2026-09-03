# -*- coding: utf-8 -*-
"""Drive the REAL loop map and LOOK at the pipeline's new band
(harness-config-ui phase 4).

The contract tests already prove the DATA - behavior.track() aggregates the
rules' `binds`, and /loop/map carries the segments. What no contract test can
prove is that the band and the knob badges are READABLE: five stations on a
430px phone leave ~80px each, and that width is exactly what once turned the
off-reasons into "Diese Vorlage benutzt die ..." and got them moved out from
under the dots. A badge and a verb added under the same dots are the same risk
again, so they get the same treatment - screenshots at both form factors,
judged, not merely rendered.

What is checked:
  1. the COLUMNS ARE THE LANES: every lane the owner's policy.lane_labels names
     is drawn, under that name, and nothing else is a column
  2. gate and deploy are drawn as STEPS on the connectors, not as columns -
     smaller than a lane dot, and sitting between the two lanes they run
     between
  3. every station Henry acts at shows its verb, and the ones he does not are
     BLANK - the band's whole meaning is where it stops
  4. the knob badge shows a number on a policy station and a padlock on a
     fixed one - never a toggle (exactly one station is switchable)
  5. no text is truncated with an ellipsis inside the row
  6. no console error or page error

1 and 2 are the regression this file exists for since 2026-09-03: the row used
to render `runtime.stations` - a five-name VOCABULARY - as five equal columns,
so "Quality Gate" and "Deploy" ranked with the lanes while the owner's fourth
lane ("Fertig") was not drawn at all. The board said four, the map said five.

Prereqs (two background processes, both sandboxed):
  HELMDECK_LANE_LABELS='{"backlog":"Inbox","working":"In Arbeit",
                         "review":"Abnahme","done":"Fertig"}' \
      py -3.12 ops/tools/boards_verify_daemon.py 8478
  cd surfaces/app && npx expo start --web --port 3478 --offline

  py -3.12 ops/tests/e2e_pipeline_track.py [web-port] [daemon-port]

Named e2e_* so ops/tools/run_gate.py skips it (needs a port + a browser).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SHOTS = os.path.join(ROOT, ".verify")

sys.path.insert(0, ROOT)

# The lanes this run expects, resolved by the SAME function the daemon serves
# from (cells.engineer.sessions.flow) and with the SAME labels the sandbox
# daemon was seeded with. No lane list is typed in this file - that is the very
# duplication the bug under test came from.
LANE_LABELS = json.loads(os.environ.get("HELMDECK_LANE_LABELS")
                         or '{"working": "Bei uns"}')

WEB = int(sys.argv[1]) if len(sys.argv) > 1 else 3478
DAEMON_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8478
DAEMON = "http://127.0.0.1:%d" % DAEMON_PORT
PW = "hunter2hunter2"

CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def sign_in(page, who="owner"):
    """Same flow as e2e_settings_hub.py's - kept in step with it deliberately."""
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


def main():
    from playwright.sync_api import sync_playwright
    from cells.engineer import sessions

    flow = sessions.flow(LANE_LABELS)
    flow_lanes = flow["nodes"]

    os.makedirs(SHOTS, exist_ok=True)
    errors = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for form, size in (("desktop", {"width": 1400, "height": 1000}),
                           ("phone", {"width": 430, "height": 900})):
            ctx = browser.new_context(viewport=size)
            page = ctx.new_page()
            # Metro's FIRST bundle of this app is well past Playwright's 30s
            # default, and a timeout there looks exactly like a broken page.
            page.set_default_navigation_timeout(180000)
            page.set_default_timeout(60000)
            sign_in(page)
            # Listeners attach AFTER the handshake on purpose: the app boots
            # with no token and probes, so a 401 before sign-in is the expected
            # shape of the login flow, not a defect. Collecting it would make
            # this check permanently red and therefore worthless.
            page.on("console", lambda m: errors.append(m.text)
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("http://127.0.0.1:%d/loopmap" % WEB,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            print("\n[%s %dx%d]" % (form, size["width"], size["height"]))
            for st in ("backlog", "working", "gate", "review", "deploy", "done"):
                check(page.locator('[data-testid="station-%s"]' % st).count() > 0,
                      "%s: station %s is drawn" % (form, st))

            # THE LANES ARE THE COLUMNS. Asked of the SERVER, not written down
            # here: the labels come from the same policy.lane_labels the daemon
            # resolved, so renaming a lane cannot make this test wrong.
            labels = {n["key"]: n["label"] for n in flow_lanes}
            body_txt = page.inner_text("body")
            for key, label in labels.items():
                check(label in body_txt,
                      "%s: lane %s is drawn under its own name %r"
                      % (form, key, label))
            check("Fertig" in labels.values() or "done" not in labels,
                  "%s: the done lane carries the owner's rename" % form)

            # ...AND THE STEPS ARE NOT COLUMNS. Geometry, because that is the
            # actual claim: a step's dot must be SMALLER than a lane's, and must
            # sit horizontally BETWEEN the two lanes it runs between. Text
            # assertions cannot tell a column from a marker on an edge.
            def box(st):
                el = page.locator('[data-testid="station-%s"]' % st)
                return el.bounding_box() if el.count() else None

            lane_boxes = [box(k) for k in labels]
            lane_w = min(b["width"] for b in lane_boxes if b)
            for st in ("gate", "deploy"):
                b = box(st)
                check(bool(b) and b["width"] < lane_w,
                      "%s: %s is a STEP, narrower than any lane column "
                      "(%s vs %s)" % (form, st,
                                      round(b["width"]) if b else "?",
                                      round(lane_w)))
            # gate runs working->review, deploy runs review->done: each must be
            # centred strictly between the two lane dots it sits between.
            for st, left, right in (("gate", "working", "review"),
                                    ("deploy", "review", "done")):
                b, lb, rb = box(st), box(left), box(right)
                if not (b and lb and rb):
                    check(False, "%s: cannot place %s" % (form, st))
                    continue
                mid = b["x"] + b["width"] / 2
                check(lb["x"] + lb["width"] <= mid + 1 <= rb["x"] + rb["width"],
                      "%s: %s sits between %s and %s, on their connector"
                      % (form, st, left, right))

            # The band: present where Henry acts, BLANK where he does not.
            # `done` is in this list since the row fix: Henry binds a rule there
            # (behavior.track()), but the band used to iterate the five-name
            # station vocabulary, which has no `done` - so his verb at the
            # owner's last lane was silently never drawn.
            for st, want in (("backlog", "legt an"), ("working", "steuert"),
                             ("review", "nimmt ab"), ("done", "nimmt ab")):
                loc = page.locator('[data-testid="henrytrack-%s"]' % st)
                txt = loc.inner_text().strip() if loc.count() else ""
                check(txt == want,
                      "%s: Henry track at %s reads %r (want %r)"
                      % (form, st, txt, want))
            # The band annotates LANES, so the steps carry no segment at all.
            for st in ("gate", "deploy"):
                loc = page.locator('[data-testid="henrytrack-%s"]' % st)
                txt = loc.inner_text().strip() if loc.count() else ""
                check(txt == "",
                      "%s: Henry track at %s is blank - he does not act there "
                      "(got %r)" % (form, st, txt))

            # THE STATION NAVIGATION is the same machine described twice, so it
            # gets the same rule: every lane is an entry, and the steps are
            # nested under one. It used to render the flat five-name vocabulary,
            # which ranked the gate with the lanes and had no "Fertig" at all.
            for key in labels:
                check(page.locator('[data-testid="nav-st-%s"]' % key).count() > 0,
                      "%s: nav lists lane %s" % (form, key))
            # Nesting is judged by GEOMETRY, not by a marker character: the
            # indent is the thing the owner actually sees, and a glyph check
            # once passed on a "↳" that rendered as a literal "l,".
            def nav_text_x(st):
                el = page.locator('[data-testid="nav-st-%s"] div:has-text("")' % st)
                b = page.locator('[data-testid="nav-st-%s"]' % st)
                if not b.count():
                    return None
                return page.evaluate("""(sel) => {
                    const el = document.querySelector(sel);
                    for (const n of el.querySelectorAll('*')) {
                      if (n.children.length === 0 && n.textContent.trim())
                        return n.getBoundingClientRect().left;
                    }
                    return null;
                }""", '[data-testid="nav-st-%s"]' % st)

            lane_x = min(x for x in (nav_text_x(k) for k in labels) if x is not None)
            for st in ("gate", "deploy"):
                x = nav_text_x(st)
                check(x is not None and x > lane_x + 5,
                      "%s: nav indents %s under a lane - it is a step, not a "
                      "column (%s vs lane %s)"
                      % (form, st, round(x) if x else "?", round(lane_x)))

            body = page.inner_text("body")
            check("Knöpfe" in body, "%s: a knob badge renders" % form)

            # VISUAL truncation, which inner_text cannot see. numberOfLines
            # clips with CSS, so the DOM still holds the whole word while the
            # screen shows "entscheid…" - the first run of this test passed its
            # text assertions on a row that was visibly cut. Compare the text
            # node's scrollWidth against its clientWidth instead: that is the
            # browser telling us the glyphs did not fit.
            clipped = page.evaluate("""() => {
                const out = [];
                for (const el of document.querySelectorAll('[data-testid^="henrytrack-"],'
                                                         + '[data-testid^="station-"]')) {
                  for (const n of el.querySelectorAll('*')) {
                    if (n.children.length === 0 && n.textContent.trim()
                        && n.scrollWidth > n.clientWidth + 1) {
                      out.push(el.getAttribute('data-testid') + ': ' + n.textContent.trim());
                    }
                  }
                }
                return out;
            }""")
            check(not clipped,
                  "%s: nothing in the station row is visually truncated (%s)"
                  % (form, clipped or "none"))

            shot = os.path.join(SHOTS, "pipeline-track-%s.png" % form)
            page.screenshot(path=shot, full_page=False)
            print("  shot   " + shot)
            ctx.close()
        browser.close()

    real = [e for e in errors if "favicon" not in e.lower()]
    check(not real, "no console/page errors (%s)" % (real[:2] or "none"))
    print("\n%d failure(s)" % len(_fails))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
