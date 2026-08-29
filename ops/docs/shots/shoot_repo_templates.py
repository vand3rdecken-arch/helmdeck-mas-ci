# -*- coding: utf-8 -*-
"""Camera for the Phase-1 repo-template mockup (ops/docs/repo-templates-mockup.html).

A design mockup that is never LOOKED AT is just a file. This drives the real
page in a real browser and captures the states a reviewer has to judge:
the two template choices, and the two chat outcomes (an accepted change and a
refused one). Static HTML, so - unlike shoot_loopmap.py - it needs no daemon,
no token and no dev server: file:// is enough.

    py -3.12 ops/docs/shots/shoot_repo_templates.py

Writes PNGs next to this file in shots/repo-templates/.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(os.path.dirname(HERE), "repo-templates-mockup.html")
OUT = os.path.join(HERE, "repo-templates")

# (name, viewport, [js clicks to run first])
SHOTS = [
    ("01-dev-default", (1180, 1500), []),
    ("02-docs", (1180, 1500), ["pick('docs')"]),
    ("03-chat-accepted", (1180, 1500), ["pick('dev')", "say('nodeploy')"]),
    ("04-chat-refused", (1180, 1500), ["pick('dev')", "say('gate')", "say('noreview')"]),
    ("05-narrow", (760, 1500), []),
]


def main():
    from playwright.sync_api import sync_playwright

    if not os.path.exists(PAGE):
        sys.exit("mockup not found: " + PAGE)
    os.makedirs(OUT, exist_ok=True)

    with sync_playwright() as p:
        b = p.chromium.launch()
        errs = []
        for name, vp, clicks in SHOTS:
            pg = b.new_page(viewport={"width": vp[0], "height": vp[1]},
                            device_scale_factor=2, color_scheme="dark")
            pg.on("pageerror", lambda e, n=name: errs.append(n + ": " + str(e)))
            pg.on("console", lambda m, n=name: errs.append(n + ": " + m.text)
                  if m.type == "error" else None)
            pg.goto("file:///" + PAGE.replace("\\", "/"))
            for js in clicks:
                pg.evaluate(js)
            pg.wait_for_timeout(180)
            path = os.path.join(OUT, name + ".png")
            pg.screenshot(path=path, full_page=True)
            print("wrote", path)
            pg.close()
        b.close()

    if errs:
        print("\n!! page errors:")
        for e in errs:
            print("  ", e)
        sys.exit(1)
    print("\nno page errors")


if __name__ == "__main__":
    main()
