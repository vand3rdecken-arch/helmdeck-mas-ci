# Screenshot the More tab's new Datenschutz (analytics opt-out) panel for UI judging.
import time

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3434"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 420, "height": 900})   # phone-ish
    pg.goto(BASE, wait_until="networkidle", timeout=120_000)
    pg.evaluate("localStorage.setItem('helmdeck.demo','1')")
    pg.goto(BASE + "/more", wait_until="networkidle")
    time.sleep(3)
    pg.screenshot(path="../shots/analytics_more_privacy.png", full_page=True)
    b.close()
print("shot saved")
