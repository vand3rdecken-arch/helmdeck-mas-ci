# -*- coding: utf-8 -*-
"""Render the glasses lens (surfaces/glasses) at 600x600 against a FAKE daemon and
write screenshots: the Henry home while listening, a spoken exchange with options,
the Board tab, the More tab, a decision.

The lens is plain HTML/JS served over http; the daemon is faked with Playwright
routes, so nothing here touches a real daemon, db or phone. Judge the PNGs by
eye - the reference says "the simulator lies" about the waveguide, so this proves
layout and structure, not brightness.

Run: py -3.12 ops/tests/shot_glasses_lens.py [outdir]
Asserts the structure (tabs, one mic pill, no text label while listening, the
composer field = Meta's own text input, phone mic opt-in) and prints the PNG paths.
"""
import http.server
import json
import os
import socketserver
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LENS = os.path.join(ROOT, "surfaces", "glasses")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".shots", "lens")
os.makedirs(OUT, exist_ok=True)

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ((" - " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=LENS, **k)

    def log_message(self, *a):
        pass


srv = socketserver.TCPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

GLANCE = {
    "needs_you": [
        {"id": "c1", "task": "Login: Passwort-Reset per E-Mail", "client": "Acme", "reason": "question",
         "question": {"id": "q1", "questions": [{"header": "Link-Dauer", "question": "Wie lange soll der Reset-Link gültig sein?",
                      "options": [{"label": "1 Stunde", "description": "sicher, knapp"}, {"label": "24 Stunden", "description": "bequem"}]}]}},
        {"id": "c2", "task": "Export-Button im Dashboard", "client": "", "reason": "delivered"},
        {"id": "c3", "task": "Gate für ***-Radar", "client": "intern", "reason": "gate"},
    ],
    "yours": [{"id": "y1", "task": "Domain verlängern", "mode": "manuell", "client": ""}],
    "econ": {"needs_you": 3, "yours": 1},
}
MSGS = [
    {"mine": True, "text": "Wie ist der Stand bei ***?"},
    {"mine": False, "text": "*** wächst 20 %, ist aber 9 % gefallen. Warum, wissen wir nicht. Das klären wir, bevor du nachkaufst."},
]
STATE = {"turn": {"state": "listening", "text": "", "mic": "glasses", "seq": 1, "age": 0}}
LISTEN_CALLS = []
TALK_CALLS = []


def chat_body():
    return {"c": 1, "g": 1, "messages": MSGS, "turn": STATE["turn"]}


from playwright.sync_api import sync_playwright   # noqa: E402

with sync_playwright() as pw:
    br = pw.chromium.launch()
    ctx = br.new_context(viewport={"width": 600, "height": 600})
    pg = ctx.new_page()

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def on_api(route):
        u = route.request.url
        if "/glance/chat" in u:
            return fulfill(route, chat_body())
        if "/glance/talk" in u:
            TALK_CALLS.append(route.request.post_data)
            return fulfill(route, {"voice": "", "question": None})
        if "/glance/listen" in u:
            LISTEN_CALLS.append(route.request.post_data)
            return fulfill(route, {"ok": True})
        if u.endswith("/glance"):
            return fulfill(route, GLANCE)
        return fulfill(route, {"ok": True})

    pg.route("**/glance**", on_api)
    pg.goto("http://127.0.0.1:%d/#t=testtoken" % PORT)
    pg.wait_for_timeout(900)

    def shot(name):
        p = os.path.join(OUT, name + ".png")
        pg.screenshot(path=p)
        print("shot", p)

    # 1: Henry home while listening
    check("Henry is the first screen", pg.locator("#talk:not(.hidden)").count() == 1)
    check("the rail: Board / orb / Mehr", pg.locator("#talk .rail-btn").all_inner_texts() == ["Board", "Mehr"] and pg.locator("#talk .orb").count() == 1, pg.locator("#talk .rail-btn").all_inner_texts())
    check("Henry's newest message is the hero card", pg.locator(".msg.latest").count() == 1 and pg.inner_text(".msg.latest").count("***") >= 1)
    check("the phone mic is opt-in: nothing asked on open by default", len(LISTEN_CALLS) == 0, LISTEN_CALLS)
    check("the orb is a real text field (Meta composer)", pg.evaluate("document.getElementById('speak').tagName") == "INPUT")
    check("rail buttons carry icons", pg.locator("#talk .rail-btn svg").count() == 2)
    check("the speak button shows the listening state", "listening" in (pg.get_attribute("#speak", "class") or ""))
    check("no 'listening' sentence on the lens", pg.locator("#turnbar.hidden").count() == 1 and "höre" not in pg.inner_text("#talk").lower())
    check("exactly one primary speak button, focused first", pg.locator("#speak").count() == 1 and pg.evaluate("document.activeElement && document.activeElement.id") == "speak")
    check("the label names both ways in", "Sprechen" in pg.inner_text("#speak-label") or "Handy" in pg.inner_text("#speak-label"), pg.inner_text("#speak-label"))
    shot("1-henry-listening")

    # 2: after an answer: options + no pill ring
    STATE["turn"] = {"state": "answered", "text": "", "mic": "glasses", "seq": 2, "age": 0,
                     "question": {"questions": [{"options": [{"label": "Radar zeigen"}, {"label": "Warum gefallen?"}]}]}}
    pg.evaluate("1")
    pg.reload()
    pg.wait_for_timeout(900)
    check("after an answer the label is Sprechen · Schreiben again", pg.inner_text("#speak-label") == "Sprechen · Schreiben", pg.inner_text("#speak-label"))
    # what Meta's composer does: the text lands in the field and a change event fires
    pg.fill("#speak", "Zeig mir das ***-Radar")
    pg.dispatch_event("#speak", "change")
    pg.wait_for_timeout(400)
    check("composer text goes to Henry (POST /glance/talk)", len(TALK_CALLS) == 1 and "***-Radar" in (TALK_CALLS[0] or ""), TALK_CALLS)
    check("the field is empty again afterwards", pg.input_value("#speak") == "")
    shot("2-henry-answer")

    # 3: board
    pg.click(".screen:not(.hidden) [data-tab=board]")
    pg.wait_for_timeout(300)
    check("board shows the big number", pg.inner_text("#needs-num").strip() == "3", pg.inner_text("#needs-num"))
    check("board label is German", "warten auf dich" in pg.inner_text("#needs-label").lower())
    check("no money or capacity stats", "€" not in pg.inner_text("#board") and "WIP" not in pg.inner_text("#board"))
    shot("3-board")

    # 4: more + mute
    pg.click("#board [data-tab=more]")
    pg.wait_for_timeout(200)
    shot("4-more")
    pg.click("[data-action=toggle-autolisten]")
    check("the phone mic can be switched on in Mehr", pg.evaluate("JSON.parse(localStorage.getItem('helmdeck_glance_cfg')).autoListen") is True)
    pg.click("#more [data-tab=talk]")
    pg.wait_for_timeout(200)
    check("the composer field is still there", pg.locator("#speak").count() == 1)
    shot("5-henry-phone-mic-on")
    n = len(LISTEN_CALLS)
    pg.reload()
    pg.wait_for_timeout(900)
    check("opted in: reopening asks the phone to listen", len(LISTEN_CALLS) == n + 1, (n, LISTEN_CALLS))

    # 5: decide
    pg.click(".screen:not(.hidden) [data-tab=board]")
    pg.wait_for_timeout(200)
    pg.click("#needs-list .list-item >> nth=0")
    pg.wait_for_timeout(300)
    check("a question card opens the decision directly", pg.locator("#decide:not(.hidden)").count() == 1)
    shot("6-decide")
    br.close()

srv.shutdown()
print("\n%d failure(s)" % len(FAILS) if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
