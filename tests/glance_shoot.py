# -*- coding: utf-8 -*-
"""Screenshot + JUDGE the glasses Glance webapp at its real 600x600 viewport.

Serves glasses/ AND a fake /glance built by the REAL daemon code path
(server.glance_payload over a fixture board), so what the shots show is what the
daemon would actually send - not a hand-written JSON that could flatter the UI.

  py -3.12 tests/glance_shoot.py            # port from HELMDECK_DEV_PORT
"""
import json, os, sys, threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "daemon"))

PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3404)
SHOTS = os.path.join(ROOT, "shots")
TOKEN = "shoot-token"


class FakeDrivers:
    live = {"m-running"}
    turn_active = staticmethod(lambda tid: tid in FakeDrivers.live)
    has_session = staticmethod(lambda tid: tid in FakeDrivers.live)


sys.modules["drivers"] = FakeDrivers
import server                                                   # noqa: E402

BOARD = [
    {"id": "c-gate", "task": "Zahlungs-Webhook auf Idempotenz umstellen",
     "client": "Acme", "status": "bounced", "lane": "review",
     "gate_report": ["tests/test_webhook.py:\nassert charged_once == True"]},
    {"id": "c-conflict", "task": "Rechnungs-PDF neu layouten", "client": "Nordwind",
     "status": "bounced", "lane": "review", "merge_kind": "conflict",
     "merge_report": "Konfliktmarkierungen sind noch im Worktree offen."},
    {"id": "c-dispatch", "task": "Nightly-Import reparieren", "client": "",
     "status": "bounced", "lane": "working",
     "last_reply": "DISPATCH FAILED: worktree fehlt"},
    {"id": "c-phantom", "task": "Suche auf Postgres FTS umstellen", "client": "Acme",
     "status": "running", "lane": "working"},
    {"id": "c-question", "task": "Kundenportal: Login-Flow", "client": "Nordwind",
     "status": "needs_you", "lane": "working", "waiting_on": "you",
     "question": {"id": "q-1", "kind": "choice", "questions": [
         {"question": "Magic-Link oder Passwort?", "header": "Login", "options": []}]}},
    {"id": "c-submitted", "task": "Onboarding-Mails eindeutschen", "client": "Acme",
     "status": "submitted", "lane": "review", "review_report": "sauber mergebar"},
    {"id": "c-delivered", "task": "Dashboard-Ladezeit halbieren", "client": "",
     "status": "needs_you", "lane": "working", "waiting_on": "you",
     "last_reply": "Fertig - 1.9s -> 0.7s."},
    {"id": "m-running", "task": "Laeuft gerade", "client": "", "status": "running",
     "lane": "working"},
    {"id": "m-background", "task": "Wartet auf eigenen Task", "client": "",
     "status": "needs_you", "lane": "working", "waiting_on": "background"},
]
METRICS = {"capacity": {"wip": 3, "wip_limit": 4, "headroom": 1},
           "totals": {"margin": 8420.0}, "settings": {"currency": "EUR"},
           "sows": [{"name": "Acme Retainer", "margin": 5200.0},
                    {"name": "Nordwind Portal", "margin": -340.0}]}


class H(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/glance"):
            body = json.dumps(server.glance_payload(
                [dict(t) for t in BOARD], METRICS)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return SimpleHTTPRequestHandler.do_GET(self)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    payload = server.glance_payload([dict(t) for t in BOARD], METRICS)
    print("payload the UI will render:")
    for c in payload["needs_you"]:
        print("  %-9s %-12s %s" % (c["reason"], c["id"], c["detail"][:60]))
    print("  econ.needs_you = %d" % payload["econ"]["needs_you"])

    httpd = ThreadingHTTPServer(
        ("127.0.0.1", PORT), partial(H, directory=os.path.join(ROOT, "glasses")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % PORT
    print("serving %s" % base)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 600, "height": 600})
        pg.goto(base, wait_until="domcontentloaded")
        pg.evaluate("""(cfg) => localStorage.setItem('helmdeck_glance_cfg',
                       JSON.stringify(cfg))""", {"base": base, "token": TOKEN})
        pg.goto(base, wait_until="networkidle")
        pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(SHOTS, "glance_1_home.png"))

        pg.click("[data-action=open-needs]")
        pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(SHOTS, "glance_2_needs.png"))

        pg.click("[data-id=c-gate]")
        pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(SHOTS, "glance_3_detail_gate.png"))

        # what the list actually reads, as text - the shot is judged, this is pinned
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(250)
        rows = pg.eval_on_selector_all(
            "#needs-list .list-item",
            "els => els.map(e => e.innerText.replace(/\\n/g, ' | '))")
        print("\nrendered rows:")
        for r in rows:
            print("  " + r)
        overflow = pg.evaluate(
            "document.documentElement.scrollWidth > 600")
        print("\nhorizontal overflow at 600px: %s" % overflow)
        b.close()
    httpd.shutdown()
    print("shots -> shots/glance_*.png")


main()
