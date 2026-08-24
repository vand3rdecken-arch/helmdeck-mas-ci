# -*- coding: utf-8 -*-
"""Screenshot-judge harness for the flat-billing cost display (this card).
Drives the DEMO board (ME temporarily flat) on the card's dev port and shoots
board / dashboard / card-overview, where every AI-cost surface lives."""
import sys, time
from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "3469"
BASE = f"http://localhost:{PORT}"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1360, "height": 900})
    pg.goto(BASE, wait_until="networkidle", timeout=120_000)
    pg.evaluate("localStorage.setItem('helmdeck.demo','1')")
    pg.goto(BASE, wait_until="networkidle")
    time.sleep(4)
    pg.screenshot(path="../shots/flatcost_board.png", full_page=False)

    pg.goto(BASE + "/dashboard", wait_until="networkidle")
    time.sleep(3)
    pg.screenshot(path="../shots/flatcost_dash.png", full_page=True)

    pg.goto(BASE + "/card/d1", wait_until="load")
    time.sleep(6)
    pg.screenshot(path="../shots/flatcost_card.png", full_page=False, animations="disabled")
    b.close()
print("SHOTS_OK")
