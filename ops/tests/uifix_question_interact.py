# -*- coding: utf-8 -*-
"""Prove the question panel actually WORKS in a browser, not just renders:
select an option, confirm the button comes alive, press it, and assert the
daemon received a well-formed POST /tracks/<id>/answer.

Prereqs: ops/tests/uifix_question_harness.py on :8199 + surfaces/app/dist exported.
    py -3.12 ops/tests/uifix_question_interact.py <device-token>
"""
import functools, http.server, json, os, socket, socketserver, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIST = os.path.join(ROOT, "surfaces", "app", "dist")
SHOTS = os.path.join(HERE, "_shots")
TOKEN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HELMDECK_TOKEN", "")
DAEMON = "http://localhost:8199"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = _free_port()
os.makedirs(SHOTS, exist_ok=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def translate_path(self, path):
        p = super().translate_path(path)
        if os.path.isfile(p) or os.path.isdir(p):
            return p
        if os.path.isfile(p + ".html"):
            return p + ".html"
        dyn = os.path.join(os.path.dirname(p), "[id].html")
        if os.path.isfile(dyn):
            return dyn
        return os.path.join(DIST, "index.html")


socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(Quiet, directory=DIST))
threading.Thread(target=srv.serve_forever, daemon=True).start()

from playwright.sync_api import sync_playwright

CONFIG = ('{"baseUrl":"%s","token":"%s","relayUrl":"","room":"","daemonPub":"",'
          '"mySec":"","myPub":""}' % (DAEMON, TOKEN))

_fails = []
answers_seen = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 420, "height": 1100}, device_scale_factor=2)

    def on_req(r):
        if r.url.endswith("/answer"):
            try:
                answers_seen.append(json.loads(r.post_data or "{}"))
            except ValueError:
                answers_seen.append({"unparsable": r.post_data})

    page.on("request", on_req)
    page.goto("http://127.0.0.1:%d/" % PORT, wait_until="domcontentloaded")
    page.evaluate("localStorage.setItem('helmdeck.config', %r)" % CONFIG)
    page.goto("http://127.0.0.1:%d/card/c-question" % PORT, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    page.get_by_text("Chat", exact=False).first.click()
    page.wait_for_timeout(1500)

    check(page.get_by_text("ENTSCHEIDUNG").count() > 0, "the question panel is on screen")

    # Target the option by ROLE, not by text: "Magic-Link" also occurs in the
    # question headline, and get_by_text(...).first hits that instead of the
    # row (which is how this harness first "proved" a bug that wasn't there).
    # Going through the a11y role also checks the radio/checkbox wiring.
    radios = page.get_by_role("radio")
    check(radios.count() == 4, "4 option rows exposed as radios (got %d)" % radios.count())
    row = page.get_by_role("radio", name="Magic-Link")
    check(row.count() == 1, "the option is reachable by its accessible name")
    row.click()
    page.wait_for_timeout(800)
    check(row.get_attribute("aria-checked") == "true", "the tapped option is checked")
    page.screenshot(path=os.path.join(SHOTS, "q-selected.png"), full_page=True)

    send = page.get_by_text("Antworten", exact=False).first
    check(send.count() > 0, "the confirm button is present")
    send.click()
    page.wait_for_timeout(2500)
    page.screenshot(path=os.path.join(SHOTS, "q-after-send.png"), full_page=True)

    check(len(answers_seen) == 1, "exactly one POST /answer was sent (got %d)" % len(answers_seen))
    if answers_seen:
        body = answers_seen[0]
        print("   payload:", json.dumps(body, ensure_ascii=False))
        check(body.get("answers", {}).get("Auth-Verfahren") == "Magic-Link",
              "the chosen label is sent under the question's header")
        check(body.get("request_id") == "q-1",
              "the question id is echoed back (stale-panel guard)")
    b.close()

srv.shutdown()
print()
if _fails:
    print("FAILED: %d check(s): %s" % (len(_fails), "; ".join(_fails)))
    sys.exit(1)
print("QUESTION PANEL INTERACTION OK")
