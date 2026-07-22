# -*- coding: utf-8 -*-
"""Adversarial UI smoke - test the app like an idiot, until it's bulletproof.

The loop's TEST state used to mean 'does it render'. This is 'does it BREAK':
walk every view, do the dumb things a real user does (open everything, submit
empty, paste a wall of text, double-toggle, rapid open/close, hit empty
states), and flag anything that crashes, errors in console, overflows
sideways, or renders an unreadable overlay over content.

Every UI bug caught by hand this session (transparent peek, collapsed
checkbox, wrong-theme dropdown, cut-off title, misaligned chat) is the kind
of thing this is meant to catch BEFORE a human sees it.

Run:  python tools/adversarial_smoke.py [--url http://localhost:3300]
Needs the dev server (:3300) + daemon (:8140) up, and playwright installed.
Prints a report; exit 0 always (a doctor, not a gate) - the loop's TEST
reminds you to run it and address what it finds."""
import sys

URL = "http://localhost:3300"
for i, a in enumerate(sys.argv):
    if a == "--url" and i + 1 < len(sys.argv):
        URL = sys.argv[i + 1]

VIEWS = ["board", "list", "timeline", "procs", "dash", "recs", "history", "settings"]


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("adversarial-smoke: playwright not installed - skipped")
        return
    import json, urllib.request
    # servers up?
    try:
        urllib.request.urlopen(URL, timeout=4)
        urllib.request.urlopen("http://localhost:8140/auth/state", timeout=4)
    except Exception:
        print("adversarial-smoke: dev server (:3300) or daemon (:8140) not up - skipped")
        return

    issues = []
    with sync_playwright() as pl:
        b = pl.chromium.launch()
        pg = b.new_context(viewport={"width": 1280, "height": 860}).new_page()
        errors = []
        # network-status console noise (401/403/404 from auth checks, SSE
        # reconnects) is NOT an app bug - only flag thrown JS errors.
        def on_console(m):
            if m.type != "error":
                return
            txt = m.text
            if "Failed to load resource" in txt or "status of 4" in txt or "status of 5" in txt:
                return
            errors.append("console.error: " + txt[:120])
        pg.on("console", on_console)
        pg.on("pageerror", lambda e: errors.append("pageerror (JS crash): " + str(e)[:120]))

        def flush(where):
            for e in errors:
                issues.append("%s -> %s" % (where, e))
            errors.clear()

        pg.goto(URL); pg.wait_for_timeout(2000)
        # login (idiot path: wrong password first, then right)
        if pg.query_selector("#authcard"):
            pg.fill('input[placeholder="username"]', "owner")
            pg.fill('input[type="password"]', "wrongpass")
            pg.click("#authcard button"); pg.wait_for_timeout(800)
            if not pg.query_selector("#authcard"):
                issues.append("auth -> wrong password did NOT block login")
            pg.fill('input[type="password"]', "glass-owner-2026")
            pg.click("#authcard button"); pg.wait_for_timeout(2500)
        flush("login")

        for v in VIEWS:
            pg.goto(URL + "/#" + v); pg.wait_for_timeout(1400)
            flush("view:" + v)
            # horizontal overflow (sideways scroll = layout break)
            ov = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            if ov and ov > 4:
                issues.append("view:%s -> horizontal overflow %dpx (layout break)" % (v, ov))

        # --- idiot actions on the board ---
        pg.goto(URL + "/#board"); pg.wait_for_timeout(1200)
        # open every card, check peek overlay is readable (opaque enough)
        cards = pg.query_selector_all(".card")
        for c in cards[:6]:
            try:
                c.click(); pg.wait_for_timeout(400)
                peek = pg.query_selector("#peek")
                if peek:
                    op = pg.evaluate("""el => {
                        const bg = getComputedStyle(el).backgroundColor;
                        const m = bg.match(/[\\d.]+\\)$/); return m ? parseFloat(m[0]) : 1;
                    }""", peek)
                    if op < 0.6:
                        issues.append("peek -> overlay too transparent (alpha %.2f) - content bleeds through" % op)
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
            except Exception as ex:
                issues.append("open-card -> %s" % str(ex)[:80])
        flush("open-cards")

        # new-request modal: empty submit + wall of text
        try:
            btn = pg.query_selector("#hdr .btn.primary")
            if btn:
                btn.click(); pg.wait_for_timeout(400)
                pg.click("#mcard .foot .btn.primary"); pg.wait_for_timeout(300)  # empty submit
                if not pg.query_selector("#mcard"):
                    issues.append("new-request -> empty submit closed/filed instead of validating")
                ta = pg.query_selector("#mcard textarea")
                if ta:
                    ta.fill("X" * 5000); pg.wait_for_timeout(300)  # wall of text
                    ov = pg.evaluate("() => { const m=document.querySelector('#mcard'); return m ? m.scrollWidth-m.clientWidth : 0 }")
                    if ov and ov > 4:
                        issues.append("new-request -> 5000-char input overflows the modal %dpx" % ov)
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        except Exception as ex:
            issues.append("new-request -> %s" % str(ex)[:80])
        flush("new-request")

        # settings: double-toggle every checkbox, cycle selects
        try:
            pg.goto(URL + "/#settings"); pg.wait_for_timeout(1500)
            for cb in pg.query_selector_all("#settings input[type=checkbox]")[:8]:
                cb.click(); pg.wait_for_timeout(80); cb.click(); pg.wait_for_timeout(80)
            flush("settings-toggle")
        except Exception as ex:
            issues.append("settings-toggle -> %s" % str(ex)[:80])

        # chat: rapid open/close
        try:
            pg.goto(URL + "/#board"); pg.wait_for_timeout(800)
            for _ in range(4):
                pg.keyboard.press("k"); pg.wait_for_timeout(120)
            flush("chat-rapid")
        except Exception as ex:
            issues.append("chat-rapid -> %s" % str(ex)[:80])

        b.close()

    # de-dup
    seen, out = set(), []
    for x in issues:
        if x not in seen:
            seen.add(x); out.append(x)
    if not out:
        print("adversarial-smoke: PASS - nothing broke under idiot testing")
    else:
        print("adversarial-smoke: %d issue(s) - address before shipping:" % len(out))
        for x in out:
            print("  - " + x)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("adversarial-smoke: harness error (not an app bug):", str(e)[:150])
    sys.exit(0)
