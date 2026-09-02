# -*- coding: utf-8 -*-
"""Prove helmdeck.de serves the CURRENT brand mark - not a stale copy of it.

This exists because the site carried its own hand-written SVG of the logo. When
the logo was redesigned on 2026-08-26 every generated surface changed and the
site's copy did not, so helmdeck.de served the superseded mark for a week and
nothing failed. A screenshot review would not have caught it either: the old
mark looked perfectly fine, it was just the wrong logo.

So the check is not "is there a logo" but "is it THE logo": the mark is
re-derived here from ops/tools/assets/logo_h_mask.png - the same mask every
app/desktop icon is generated from - and compared against what the origin
actually served.

Points at a URL, so the SAME script checks the local worker before a deploy and
the live origin after one (see site_platforms_shoot.py for the same rule).

Prereqs (local mode):  cd ops/deploy/waitlist && npx wrangler dev --port 3483
Run:  py -3.12 ops/tests/site_logo_probe.py [base-url] [tag]
      py -3.12 ops/tests/site_logo_probe.py http://127.0.0.1:3483 local
      py -3.12 ops/tests/site_logo_probe.py https://helmdeck.de live
"""
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # ops/tests/ -> repo root
SHOTS = os.path.join(HERE, "_shots")
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3483").rstrip("/")
TAG = sys.argv[2] if len(sys.argv) > 2 else "local"
os.makedirs(SHOTS, exist_ok=True)

from PIL import Image  # noqa: E402
import make_icon  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

errors = []


def want_svg():
    """The mark as the icon generator would emit it, right now, from the mask."""
    mask = Image.open(make_icon.MASK_PATH).convert("L")
    return make_icon.site_logo_svg(make_icon.binary_rows(mask))


def path_d(svg):
    """The glyph outline out of an SVG string - the part that IS the logo.

    Compared separately from the whole document so a failure says which half
    drifted: the shape, or the tile colours around it.
    """
    marker = ' d="'
    i = svg.find(marker)
    if i < 0:
        return ""
    j = svg.find('"', i + len(marker))
    return svg[i + len(marker):j]


def fetch(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "helmdeck-logo-probe"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8"), r.headers.get("content-type", "")


expected = want_svg()
expected_d = path_d(expected)
print("expected glyph path: %d chars, %d subpaths"
      % (len(expected_d), expected_d.count("Z")))

# 1. the standalone mark (this is also the favicon)
served, ctype = fetch("/icon.svg")
print("GET /icon.svg -> %d chars, content-type: %s" % (len(served), ctype))
if "image/svg+xml" not in ctype:
    errors.append("/icon.svg content-type is %r, expected image/svg+xml" % ctype)
if path_d(served) != expected_d:
    errors.append("/icon.svg glyph outline does NOT match the current logo mask "
                  "- the site is serving a stale mark (run: py -3.12 ops/tools/make_icon.py)")
elif served.strip() != expected.strip():
    errors.append("/icon.svg glyph matches but the surrounding tile drifted "
                  "(gradient/corner radius) - regenerate via make_icon.py")
else:
    print("OK  /icon.svg is byte-identical to the generated mark")

# 2. the mark as actually painted in the page, in a real browser
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900},
                        device_scale_factor=2, locale="de-DE")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
    page.on("console", lambda m: errors.append("console.error: %s" % m.text)
            if m.type == "error" else None)
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    lockup = page.locator(".lockup svg")
    if lockup.count() != 1:
        errors.append("expected exactly 1 lockup mark in the page, found %d" % lockup.count())
    else:
        inline_d = page.eval_on_selector(
            ".lockup svg path", "el => el.getAttribute('d')") or ""
        if inline_d != expected_d:
            errors.append("the header lockup renders a DIFFERENT mark than the "
                          "current logo mask")
        else:
            print("OK  header lockup renders the current mark")
        # A mark that is in the DOM but collapsed/invisible is still a broken
        # logo, and the outline comparison above cannot see that.
        box = lockup.bounding_box()
        print("lockup box: %s" % box)
        if not box or box["width"] < 12 or box["height"] < 12:
            errors.append("lockup mark is present but not visibly sized: %s" % box)

    # favicon must point at the mark, not at a leftover file
    icon_href = page.eval_on_selector(
        "link[rel~='icon']", "el => el.getAttribute('href')") or ""
    print("favicon href: %r" % icon_href)
    if icon_href != "/icon.svg":
        errors.append("favicon href is %r, expected /icon.svg" % icon_href)

    # Screenshots for the human judgement CLAUDE.md asks for: the mark in its
    # real context (topbar), and big, where any tracing artefact would show.
    page.locator(".lockup").screenshot(path=os.path.join(SHOTS, "%s-logo-lockup.png" % TAG))
    page.locator(".topbar-fixed").screenshot(path=os.path.join(SHOTS, "%s-logo-topbar.png" % TAG))
    print("shot %s-logo-lockup.png / %s-logo-topbar.png" % (TAG, TAG))

    big = ctx.new_page()
    big.set_viewport_size({"width": 420, "height": 420})
    big.goto(BASE + "/icon.svg", wait_until="load")
    big.wait_for_timeout(400)
    big.screenshot(path=os.path.join(SHOTS, "%s-logo-large.png" % TAG))
    print("shot %s-logo-large.png" % TAG)
    b.close()

if errors:
    print("\nFAILURES (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
    sys.exit(1)
print("\nsite serves the current HelmDeck mark (matches ops/tools/assets/logo_h_mask.png)")
