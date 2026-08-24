# -*- coding: utf-8 -*-
"""Screenshot the Automatik hub + Loop-Map for the CLAUDE.md UI judgement.

Not a test - a CAMERA. It drives the real web build against the real sandbox
daemon (no demo fixtures), so what gets judged is the payload the daemon
actually serves. Both themes and both widths, because "readable" is a claim
about the worst combination, not the one that happened to be open.

    py -3.12 docs/shots/shoot_harness.py [--port 3599] [--cfg <base64>]
"""
import argparse, base64, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "harness")

SHOTS = [
    # (name, route, viewport, scroll-to selector-ish text, theme)
    ("hub-top",       "/automation", (430, 932)),
    ("hub-harness",   "/automation", (430, 932)),
    ("loopmap",       "/loopmap",    (430, 932)),
    ("hub-wide",      "/automation", (1280, 1000)),
    ("loopmap-wide",  "/loopmap",    (1280, 1000)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="3599")
    ap.add_argument("--cfg", required=True, help="base64 {baseUrl,token}")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    from playwright.sync_api import sync_playwright

    base = "http://localhost:%s" % a.port
    errors = []

    # DARK ONLY, on purpose. app/src/app/_layout.tsx mounts <ThemeProvider
    # name="dark"> at both call sites: tokens.light exists but nothing can
    # select it, so shooting a "light" pass produced two identical files and a
    # false claim that both themes had been judged. Restore the second pass here
    # the day the app grows a real theme switch.
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for theme in ("dark",):
            ctx = br.new_context(viewport={"width": 430, "height": 932},
                                 device_scale_factor=2,
                                 color_scheme=theme)
            pg = ctx.new_page()
            pg.on("console", lambda m: errors.append("console.%s: %s" % (m.type, m.text))
                  if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))

            # bootstrap the daemon URL + token through the #cfg hash the desktop uses
            pg.goto("%s/#cfg=%s" % (base, a.cfg), wait_until="load", timeout=90000)
            pg.wait_for_timeout(9000)

            for name, route, vp in SHOTS:
                pg.set_viewport_size({"width": vp[0], "height": vp[1]})
                pg.goto("%s%s#cfg=%s" % (base, route, a.cfg), wait_until="load", timeout=90000)
                # /loop/map takes ~6s: loop_state.transitions() shells out to git.
                # A 5s wait screenshotted the spinner and looked like a bug in the
                # screen. Wait for the spinner to be GONE rather than guessing.
                pg.wait_for_timeout(3000)
                for _ in range(30):
                    if pg.locator('[role="progressbar"], .css-progressbar').count() == 0:
                        break
                    pg.wait_for_timeout(1000)
                pg.wait_for_timeout(3500)
                # Expand the hook matrix - a collapsed panel proves nothing about
                # whether its rows are readable.
                if name == "hub-harness":
                    try:
                        pg.get_by_text("Hooks:", exact=False).first.click(timeout=8000)
                        pg.wait_for_timeout(1200)
                    except Exception as e:
                        errors.append("expand(%s): %s" % (name, str(e)[:120]))
                p = os.path.join(OUT, "%s-%s.png" % (name, theme))
                # full_page everywhere: the Harness block sits far below the fold
                # on a phone, and an unjudged section is an unshipped one.
                pg.screenshot(path=p, full_page=True)
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
