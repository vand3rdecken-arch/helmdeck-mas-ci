# -*- coding: utf-8 -*-
"""Screenshot the Loop-Map for the CLAUDE.md UI judgement.

A CAMERA, not a test: it drives the real web build against
ops/docs/shots/repo_pipeline_sandbox.py (no demo fixtures), so what gets judged
is the payload the daemon really serves.

    py -3.12 ops/docs/shots/repo_pipeline_sandbox.py --port 8869 --repo-mode

It used to name loopmap_sandbox.py, which is deleted: that file only booted a
throwaway daemon and seeded nothing ON PURPOSE (/loop/map reads the graph out of
the CODE), so it was pure boilerplate the sandbox above already does. Keep
--repo-mode - it is what makes the build loop report all seven states instead of
the four a card worktree has, and an unrendered row is an unjudged one.

The interesting states of this screen are BEHIND A TAP - a fixed stage's reason
and source line, a policy stage's knobs - so the collapsed page proves nothing.
Each shot below opens exactly one of them:

    default   the page as it lands (gate selected, everything collapsed)
    lane      a POLICY lane picked: its knobs, one editable, one settings.json-only
    fixed     a FIXED stage expanded: the reason + the file:line it cites
    policy    a POLICY stage expanded: the reason + an env-var knob (not a link)
    wide      1280px, everything the phone shot showed, re-judged for centering

    py -3.12 ops/docs/shots/shoot_loopmap.py --port 3852 --cfg <base64 {baseUrl,token}>
"""
import argparse, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "harness")

# (name, viewport, [testIDs to click], where to scroll before the shot)
#
# testIDs, NOT visible text. get_by_text("COMMIT") matches the "-> COMMIT" EDGE
# label of the state above before it reaches the COMMIT row, so the driver
# clicked a plain Text, expanded nothing, and reported success. The first run of
# this script produced two screenshots of collapsed rows that looked correct.
#
# `scroll` exists because full_page is a LIE on this page. React-Native-Web
# renders <ScrollView> as an inner overflow:auto div, so the document itself
# never grows and Playwright's full_page capture returns one viewport of
# whatever that inner container happens to be scrolled to. The first run
# screenshotted the laws and the charter exactly never, while looking for all
# the world like a whole-page capture. Every region is now scrolled to
# explicitly - "an unjudged section is an unshipped one" only holds if the
# camera can actually reach it.
SHOTS = [
    # `station-*`, not `lane-*`: the lane row became the shared pipeline
    # component (ui/repo_pipeline.tsx) and its testIDs were renamed with it.
    # Left as `lane-backlog` this shot would match 0 nodes and photograph an
    # unclicked page while reporting success - which is exactly how the first
    # run of the sibling camera lied.
    ("loopmap2-default", (430, 932),  [], "top"),
    ("loopmap2-lane",    (430, 932),  ["station-backlog"], "top"),
    ("loopmap2-fixed",   (430, 932),  ["loopstate-EXECUTE"], "loopstate-EXECUTE"),
    ("loopmap2-policy",  (430, 932),  ["loopstate-COMMIT"], "loopstate-COMMIT"),
    # the section-level "why is this locked / where ARE the knobs" note, which
    # sits directly above the first stage row
    ("loopmap2-buildnote", (430, 932), [], "loopstate-ALIGN"),
    ("loopmap2-laws",    (430, 932),  [], "bottom"),
    ("loopmap2-wide",    (1280, 1000), ["station-backlog"], "top"),
    ("loopmap2-wide-note", (1280, 1000), [], "loopstate-ALIGN"),
    ("loopmap2-wide-bottom", (1280, 1000), ["loopstate-COMMIT"], "bottom"),
]

# The RN-Web ScrollView: the tallest element that actually scrolls.
FIND_SCROLLER = """() => {
  const all = [...document.querySelectorAll('div')].filter(e => {
    const s = getComputedStyle(e);
    return /auto|scroll/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 40;
  });
  return all.length ? all.sort((a, b) => b.scrollHeight - a.scrollHeight)[0] : null;
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="3852")
    ap.add_argument("--cfg", required=True, help="base64 {baseUrl,token}")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    from playwright.sync_api import sync_playwright

    base = "http://localhost:%s" % a.port
    errors = []

    # DARK ONLY: _layout.tsx mounts <ThemeProvider name="dark"> at both call
    # sites, so tokens.light is unreachable and a "light" pass would write a
    # byte-identical second file - a false claim of coverage. See shoot_harness.py.
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 430, "height": 932},
                             device_scale_factor=2, color_scheme="dark")
        pg = ctx.new_page()
        pg.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))

        # bootstrap the daemon URL + token through the #cfg hash the desktop uses
        pg.goto("%s/#cfg=%s" % (base, a.cfg), wait_until="load", timeout=90000)
        pg.wait_for_timeout(9000)

        for name, vp, clicks, scroll in SHOTS:
            pg.set_viewport_size({"width": vp[0], "height": vp[1]})
            pg.goto("%s/loopmap#cfg=%s" % (base, a.cfg), wait_until="load", timeout=90000)
            # /loop/map takes ~6s: loop_state.transitions() shells out to git.
            # Wait for the spinner to be GONE rather than guessing a duration.
            pg.wait_for_timeout(3000)
            for _ in range(30):
                if pg.locator('[role="progressbar"], .css-progressbar').count() == 0:
                    break
                pg.wait_for_timeout(1000)
            pg.wait_for_timeout(2500)
            for tid in clicks:
                # strict: exactly one node must carry this testID. A missing or
                # ambiguous one is a REAL failure of the shot, not a warning -
                # the picture would otherwise claim to show an open row.
                loc = pg.locator('[data-testid="%s"]' % tid)
                try:
                    if loc.count() != 1:
                        raise RuntimeError("matched %d nodes" % loc.count())
                    loc.first.click(timeout=8000)
                    pg.wait_for_timeout(900)
                except Exception as e:                       # noqa: BLE001
                    errors.append("click(%s/%s): %s" % (name, tid, str(e)[:140]))
            if scroll == "bottom":
                ok = pg.evaluate("(fn) => { const el = eval('(' + fn + ')')(); "
                                 "if (!el) return false; el.scrollTop = el.scrollHeight; "
                                 "return true; }", FIND_SCROLLER)
                if not ok:
                    errors.append("scroll(%s): no scroll container found" % name)
                pg.wait_for_timeout(900)
            elif scroll != "top":
                try:
                    pg.locator('[data-testid="%s"]' % scroll).first \
                      .scroll_into_view_if_needed(timeout=8000)
                    pg.wait_for_timeout(900)
                except Exception as e:                       # noqa: BLE001
                    # record and carry on: one unreachable anchor must not cost
                    # the remaining shots, but it must not pass silently either
                    errors.append("scroll(%s/%s): %s" % (name, scroll, str(e)[:140]))
            p = os.path.join(OUT, "%s.png" % name)
            pg.screenshot(path=p)
            print("wrote", os.path.relpath(p, os.path.dirname(HERE)).replace("\\", "/"))
        ctx.close()
        br.close()

    if errors:
        print("\n--- PAGE ERRORS (%d) ---" % len(errors))
        for e in dict.fromkeys(errors):
            print(" ", e[:300])
    else:
        print("\nno console/page errors")


if __name__ == "__main__":
    main()
