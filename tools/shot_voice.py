# -*- coding: utf-8 -*-
"""Screenshot the voice mode surface so a human can JUDGE it (CLAUDE.md: UI
changes are judged, not merely confirmed to render).

Drives the real app on the Expo web dev server in DEMO mode, which is the one
way to reach the chat without a paired daemon. Grants microphone permission up
front so voice mode opens in its listening state rather than its denied state -
the state the owner will actually see.

Usage:  py -3.12 tools/shot_voice.py <port> <outdir>
"""
import sys

from playwright.sync_api import sync_playwright

port = sys.argv[1] if len(sys.argv) > 1 else "3531"
out = sys.argv[2] if len(sys.argv) > 2 else "."
base = "http://localhost:%s" % port


def shoot(page, name, theme):
    page.screenshot(path="%s/voice-%s-%s.png" % (out, name, theme))
    print("shot: voice-%s-%s.png" % (name, theme))


with sync_playwright() as p:
    for theme in ("dark",):
        b = p.chromium.launch()
        ctx = b.new_context(
            viewport={"width": 430, "height": 932},      # phone-shaped: the surface this is for
            color_scheme=theme,
            permissions=["microphone"],
        )
        page = ctx.new_page()
        page.goto(base + "/", wait_until="domcontentloaded")
        # demo flag must be set BEFORE the app reads it, then reload
        page.evaluate("localStorage.setItem('helmdeck.demo', '1')")
        page.goto(base + "/chat", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        shoot(page, "chat", theme)

        # the composer's mic button (empty composer -> voice)
        mic = page.get_by_label("Sprachmodus", exact=True).or_(
            page.get_by_label("Voice mode", exact=True))
        try:
            mic.first.click(timeout=8000)
        except Exception as e:                                # noqa: BLE001
            print("MIC BUTTON NOT REACHED (%s): %s" % (theme, str(e)[:160]))
            ctx.close(); b.close(); continue
        page.wait_for_timeout(2500)
        shoot(page, "mode", theme)

        # transcript toggle - the second state worth judging
        try:
            page.get_by_label("Verlauf", exact=True).or_(
                page.get_by_label("Transcript", exact=True)).first.click(timeout=5000)
            page.wait_for_timeout(1200)
            shoot(page, "transcript", theme)
        except Exception as e:                                # noqa: BLE001
            print("transcript toggle not reached: %s" % str(e)[:120])
        ctx.close()
        b.close()
print("done")
