# -*- coding: utf-8 -*-
"""A throwaway daemon for LOOKING AT the boards UI (accounts-boards-prd phase 2).

Serves the real request handler (spine.http.server.H) over a SANDBOX store, so
the app under test talks to the actual routes - but nothing else the daemon's
serve() does runs. That exclusion is the point: serve() reaps orphan agent
process trees and sweeps worktrees, which on a developer box would reach into
OTHER cards' live work. A screenshot is not worth that.

  py -3.12 ops/tools/boards_verify_daemon.py [port]

Prints the login and the #cfg fragment to point the Expo web build at it.
Ctrl-C to stop; the sandbox is a temp dir and is not cleaned up on purpose, so
a failed run can still be inspected.
"""
import base64, json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-boardsui-")
import daemon.paths
daemon.paths.DAEMON_ROOT = SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import boards, db, events    # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET),
                    ("users", auth.USERS), ("sessions", auth.SESS)):
    assert path.startswith(SANDBOX), \
        "REFUSING TO RUN: %s points at %s, not the sandbox" % (label, path)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8149
PW = "hunter2hunter2"

db.init()
with open(events.SET, "w", encoding="utf-8") as f:
    json.dump({"policy": {"lang": "de", "lane_labels": {"working": "Bei uns"}},
               "appearance": {"backdrop": "mesh"}}, f)

auth.create_user("owner", PW, "owner")
auth.create_user("ada", PW, "client")
boards.ensure_default()

# Cards in every lane, so the overflow invariant has something to be about.
NOW = "2026-09-01 12:00:00"
CARDS = [
    ("bk-1", "Login-Flow entwerfen", "backlog", "queued", "high"),
    ("bk-2", "Onboarding-Text kürzen", "backlog", "queued", "low"),
    ("wk-1", "Relay-Reconnect härten", "working", "running", "urgent"),
    ("wk-2", "Push-Token erneuern", "working", "needs_you", "medium"),
    ("rv-1", "Board-Spalten umbenennen", "review", "submitted", "high"),
    ("rv-2", "Audit-Zeile für Boards", "review", "submitted", "medium"),
    ("dn-1", "Profil je Konto speichern", "done", "accepted", "medium"),
]
for i, (tid, task, lane, status, prio) in enumerate(CARDS):
    db.track_put({"id": tid, "task": task, "lane": lane, "status": status,
                  "priority": prio, "branch": "feat/" + tid, "repo": ROOT,
                  "created": NOW, "rank": i, "driver": "claude",
                  "actor": "owner", "client": "", "ai_cost": 0.0})

from http.server import ThreadingHTTPServer     # noqa: E402
from spine.http.server import H                 # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

cfg = base64.b64encode(
    json.dumps({"baseUrl": "http://127.0.0.1:%d" % PORT}).encode()).decode()
print("sandbox : %s" % SANDBOX)
print("daemon  : http://127.0.0.1:%d  (owner/%s, ada/%s)" % (PORT, PW, PW))
print("#cfg    : #cfg=%s" % cfg)
sys.stdout.flush()
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    srv.shutdown()
