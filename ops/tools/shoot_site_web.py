# -*- coding: utf-8 -*-
"""Web captures for helmdeck.de against a SANDBOX daemon (boards_verify_daemon.py
or demo_phone_daemon.py): the desktop board shot, plus a phone-viewport preview
used to judge the seeded content before the emulator shoot.

  py -3.12 ops/tools/shoot_site_web.py <web-port> <daemon-port> <out-dir> desk|phone [tab-text ...]
"""
import json, os, sys
from playwright.sync_api import sync_playwright

WEB, DPORT, OUT, MODE = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
CFG = json.dumps({"baseUrl": "http://127.0.0.1:%d" % DPORT, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})
PW = "hunter2hunter2"

with sync_playwright() as p:
    b = p.chromium.launch()
    vp = {"width": 1029, "height": 489} if MODE == "desk" else {"width": 390, "height": 867}
    page = b.new_page(viewport=vp, device_scale_factor=1.4 if MODE == "desk" else 1.5)
    url = "http://127.0.0.1:%d/" % WEB
    page.goto(url, wait_until="domcontentloaded", timeout=240000)
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto(url, wait_until="domcontentloaded", timeout=240000)
    page.wait_for_timeout(5000)
    for u, pw, cta in (("Benutzername", "Passwort", "Anmelden"), ("Username", "Password", "Sign in")):
        if page.get_by_placeholder(u).count():
            page.get_by_placeholder(u).first.fill("owner")
            page.get_by_placeholder(pw).first.fill(PW)
            page.get_by_text(cta, exact=True).last.click()
            page.keyboard.press("Enter"); page.wait_for_timeout(14000)
            break
    page.wait_for_timeout(4000)
    if page.get_by_text("English", exact=True).count():   # first-run language chooser
        page.get_by_text("English", exact=True).first.click()
        page.wait_for_timeout(4000)
    if os.environ.get("HDRELOAD"):   # queries fired before sign-in stay empty until a fresh load
        page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(15000)
    page.screenshot(path="%s/%s-0.png" % (OUT, MODE))
    for i, tab in enumerate(sys.argv[5:], 1):
        (page.get_by_text(tab, exact=True).first if MODE == "desk" else page.get_by_text(tab, exact=True).last).click()
        page.wait_for_timeout(int(os.environ.get("HDWAIT", "12000")))
        if MODE == "desk":   # the two floating round buttons (chat, +) cover the last card column
            page.evaluate("""() => document.querySelectorAll('*').forEach(e => {
              const r = e.getBoundingClientRect();
              if (r.width > 40 && r.width < 80 && r.height > 40 && r.height < 80
                  && r.right > innerWidth - 40 && r.bottom > innerHeight - 150 && r.left > innerWidth - 100)
                e.style.visibility = 'hidden'; })""")
        page.screenshot(path="%s/%s-%d.png" % (OUT, MODE, i))
    b.close()
