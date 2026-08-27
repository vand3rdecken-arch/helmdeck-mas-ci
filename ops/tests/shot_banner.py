# -*- coding: utf-8 -*-
"""Screenshot the HealthBanner: load the Expo web app with NO daemon running
(direct mode -> every request is a transport failure), wait for the banner,
capture. Run: py -3.12 ops/tests/shot_banner.py [port]"""
import sys, time
from playwright.sync_api import sync_playwright

port = sys.argv[1] if len(sys.argv) > 1 else "8085"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 420, "height": 860})
    pg.goto("http://127.0.0.1:%s" % port, timeout=120000)
    pg.wait_for_timeout(12000)   # hydrate + first failed round-trips
    pg.screenshot(path="ops/tests/banner_offline.png")
    print("saved ops/tests/banner_offline.png")
    print("banner text present:", "nicht erreichbar" in pg.content())
    b.close()
