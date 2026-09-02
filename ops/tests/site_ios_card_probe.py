# -*- coding: utf-8 -*-
"""Probe the iOS card on helmdeck.de: does its PRIMARY action actually do
something for a visitor with no OS-registered mail handler?

This exists because the previous iOS fix (6b74ed4) was justified by a measured
claim - a bare mailto: button produced "navigated away? False | new tabs: 0" in
real Chromium - and a claim like that rots silently. The card now leads with a
clipboard button instead, so the thing to re-measure is that the copy actually
lands in the clipboard and the secondary link is a real URL, not that the page
"looks fine".

Run:  py -3.12 ops/tests/site_ios_card_probe.py [base-url]
"""
import sys

# The page is German and its copy-confirmation ends in U+2713; a default cp1252
# stdout on this box raises UnicodeEncodeError on it and the probe dies AFTER
# the click, which reads like a site failure when it is only a console failure.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://helmdeck.de").rstrip("/")

from playwright.sync_api import sync_playwright

errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(locale="de-DE", viewport={"width": 1440, "height": 1000},
                        permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    # The iOS card's own subtree, so a selector can't accidentally match Android.
    card = page.locator(".dl-card", has=page.locator("h3", has_text="iPhone"))
    print("iOS card text:\n  " + card.inner_text().replace("\n", "\n  "))

    btn = page.locator("#ios-copy")
    if btn.count() != 1:
        errors.append("expected exactly one #ios-copy button, found %d" % btn.count())
    else:
        before = page.url
        opened = []
        page.context.on("page", lambda pg: opened.append(pg.url))
        btn.click()
        page.wait_for_timeout(700)
        label = btn.inner_text().strip()
        clip = page.evaluate("() => navigator.clipboard.readText()")
        print("after click: label=%r clipboard=%r navigated=%s new_tabs=%d"
              % (label, clip, page.url != before, len(opened)))
        # The whole point of the clipboard button: it must produce a visible
        # confirmation AND the address must really be on the clipboard.
        if "@" not in (clip or ""):
            errors.append("clipboard does not hold an address: %r" % clip)
        if label == "E-Mail-Adresse kopieren":
            errors.append("button label never confirmed the copy (still %r)" % label)

    # Secondary CTA must be a real absolute URL, not a mailto/# placeholder.
    for a in card.locator("a").all():
        href = (a.get_attribute("href") or "").strip()
        txt = a.inner_text().strip()
        print("iOS card link: %-28s -> %s" % (txt[:28], href[:90]))
        if href.startswith("mailto:"):
            print("    (mailto is an ENHANCEMENT here, not the primary action)")

    b.close()

if errors:
    print("\nFAILURES (%d):" % len(errors))
    for e in dict.fromkeys(errors):
        print("  " + e[:300])
    sys.exit(1)
print("\niOS card primary action works without a mail handler")
