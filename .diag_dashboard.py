import json
from playwright.sync_api import sync_playwright

WEB = 8199
DAEMON = "http://127.0.0.1:8149"
PW = "hunter2hunter2"
CFG = json.dumps({"baseUrl": DAEMON, "token": "", "relayUrl": "",
                  "room": "", "daemonPub": "", "mySec": "", "myPub": ""})

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("PAGEERROR:", e))
    page.on("requestfailed", lambda r: print("REQFAIL:", r.url, r.failure))
    page.on("response", lambda r: print("RESP:", r.status, r.url))

    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded", timeout=180000)
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", ["helmdeck.config", CFG])
    page.goto("http://127.0.0.1:%d/" % WEB, wait_until="domcontentloaded", timeout=180000)
    page.wait_for_timeout(4000)
    for user_ph, pw_ph, cta in (("Benutzername", "Passwort", "Anmelden"),
                                ("Username", "Password", "Sign in")):
        if page.get_by_placeholder(user_ph).count():
            page.get_by_placeholder(user_ph).first.fill("owner")
            page.get_by_placeholder(pw_ph).first.fill(PW)
            page.get_by_text(cta, exact=True).last.click()
            page.wait_for_timeout(5000)
            break
    for _ in range(20):
        if "Sprache" not in page.inner_text("body") and "language" not in page.inner_text("body"):
            break
        try:
            page.get_by_text("Deutsch", exact=True).first.click(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
    page.wait_for_timeout(2500)

    print("=== after sign-in, marker ===")
    page.wait_for_timeout(6000)
    txt = page.inner_text("body")[:500].encode("ascii", "replace").decode()
    print("BODY TEXT:", txt)
    b.close()
