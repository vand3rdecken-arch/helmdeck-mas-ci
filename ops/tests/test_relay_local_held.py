# -*- coding: utf-8 -*-
"""relay_client._local: the HELD leg giving up is not a daemon failure.

Owner report 2026-09-17 09:16: Alert "Error / timed out" over the Henry chat.
Two card-scoped Henry sends waited 132s / 116s on the turn lock; the bridge's
115s loopback leg gave up and sealed back 502 {"error": "timed out"}, which
the app read as "the daemon answered" although both turns succeeded.

Runs the REAL path: a real HTTP server on loopback that holds the request
longer than LOCAL_TIMEOUT (shortened here), and a dead port for the contrast
case. No db, no settings - _local touches neither.

Run: py -3.12 ops/tests/test_relay_local_held.py
"""
import http.server, json, os, socket, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spine.comms import relay_client as rc  # noqa: E402

FAILS = []


def check(name, cond, note=""):
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" - " + note) if note else ""))
    if not cond:
        FAILS.append(name)


class _H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/slow":
            time.sleep(1.5)
        body = json.dumps({"reply": "ok"}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass            # the bridge hung up first - exactly the case under test


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

rc.LOCAL_TIMEOUT = 0.5

# 1. the daemon is still working when the held leg gives up
r = rc._local(port, {"method": "POST", "path": "/slow", "body": "{}"})
b = json.loads(r["body"])
check("held leg give-up is 504, not 502", r["status"] == 504, str(r["status"]))
check("held leg give-up carries held=true", b.get("held") is True, r["body"])
check("the raw socket text never reaches the phone", "timed out" not in b.get("error", ""), b.get("error", ""))

# 2. an answer inside the bound passes through untouched
r = rc._local(port, {"method": "POST", "path": "/fast", "body": "{}"})
check("fast answer passes through", r["status"] == 200 and json.loads(r["body"]).get("reply") == "ok")

# 3. a daemon that is DOWN is not "held": nothing accepted the request
s = socket.socket()
s.bind(("127.0.0.1", 0))
dead = s.getsockname()[1]
s.close()
r = rc._local(dead, {"method": "POST", "path": "/chat", "body": "{}"})
check("dead daemon stays a plain 502", r["status"] == 502 and not json.loads(r["body"]).get("held"), r["body"])

srv.shutdown()
print("\n%d failed" % len(FAILS))
sys.exit(1 if FAILS else 0)
