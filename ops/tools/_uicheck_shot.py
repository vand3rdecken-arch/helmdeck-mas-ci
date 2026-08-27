# -*- coding: utf-8 -*-
"""Scratch Playwright driver for the GxP picker screenshot check. Delete
after use, same as _uicheck_daemon.py."""
import base64
import json
import sys
import time

from playwright.sync_api import sync_playwright

cfg = json.dumps({"baseUrl": "http://127.0.0.1:8199", "token": ""})
frag = base64.b64encode(cfg.encode()).decode()
url = "http://localhost:8189/#cfg=" + frag

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 480, "height": 900})
    page.goto(url)
    page.wait_for_timeout(2500)
    page.screenshot(path="/tmp/shot_1_login.png")

    # login form: two TextInputs (name, password) + submit pressable
    inputs = page.locator("input")
    inputs.nth(0).fill("uicheck")
    inputs.nth(1).fill("uicheck-pw-12345")
    page.get_by_text("Anmelden", exact=False).first.click()
    page.wait_for_timeout(2500)
    page.screenshot(path="/tmp/shot_2_after_login.png")

    # navigate to settings
    page.goto("http://localhost:8189/settings#cfg=" + frag)
    page.wait_for_timeout(2500)
    page.screenshot(path="/tmp/shot_3_settings.png", full_page=True)

    # scroll to find the GxP panel and open it
    gxp_btn = page.get_by_text("GxP", exact=False).first
    gxp_btn.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    page.screenshot(path="/tmp/shot_4_gxp_panel.png")
    gxp_btn.click()
    page.wait_for_timeout(1000)
    page.screenshot(path="/tmp/shot_5_gxp_dialog.png", full_page=True)

    browser.close()

print("done")
