# -*- coding: utf-8 -*-
"""A throwaway daemon for LOOKING AT the "what is actually stored" view.

Same shape and the same refusal as ops/tools/boards_verify_daemon.py: it serves
the real request handler over a SANDBOX store, and it does NOT call serve(),
because serve() reaps orphan agent process trees and sweeps worktrees - on this
box that would reach into other cards' live work, and no screenshot is worth
that.

  py -3.12 ops/tools/storedconfig_verify_daemon.py [port]

WHAT IT SEEDS, AND WHY EACH ONE. The panel's whole claim is that it shows rows
the resolved view cannot, so a sandbox where everything is tidy would prove
nothing. Each seed below is one state that has to be legible at a glance:

  - rows for TWO projects, only one of them selected. The "row for a repo you
    are not looking at" case, which is the panel's main reason to exist.
  - an UNDECLARED row (`rule.report.retired_knob.all`), written straight through
    db so no validator can refuse it. That is what a retired knob leaves behind:
    a value on disk the daemon has stopped honouring, invisible everywhere else.
  - a legacy key holding an ILLEGAL value, so the refusal path renders. `yolo`
    is not one of hands.permission_mode's options, so adopt() keeps it and says
    why rather than dropping it.
  - a board with one column deliberately UNLABELLED, so "empty means show the
    station's own name" is visible next to three real labels.

Prints the login and the #cfg fragment. Ctrl-C to stop; the sandbox is a temp
dir and is deliberately not cleaned up, so a failed run can still be inspected.
"""
import base64, json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-storedui-")
# policy.py binds SEED = DAEMON_ROOT/policy_seed.json at IMPORT TIME (spine/
# auth/policy.py:25-26, `from daemon.paths import DAEMON_ROOT as HERE`) - the
# sandbox swap above redirects every OTHER store, but a POST /policy/swap
# still reads the real seed from the real daemon/, which does not exist under
# SANDBOX. Copy it in before policy.py is ever imported, or any policy.swap()
# call (this script's own seed() helper, or an e2e toggling a cell flag) 500s
# with a bare "No such file or directory" - found the hard way verifying the
# process/connectors->engineer merge (2026-09-03).
import shutil
shutil.copy2(os.path.join(ROOT, "daemon", "policy_seed.json"),
             os.path.join(SANDBOX, "policy_seed.json"))
import daemon.paths
daemon.paths.DAEMON_ROOT = SANDBOX

from spine.auth import auth                                   # noqa: E402
from spine.storage import boards, db, events, legacypolicy     # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET),
                    ("users", auth.USERS), ("sessions", auth.SESS)):
    assert path.startswith(SANDBOX), \
        "REFUSING TO RUN: %s points at %s, not the sandbox" % (label, path)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8151
PW = "hunter2hunter2"

db.init()
with open(events.SET, "w", encoding="utf-8") as f:
    json.dump({
        "policy": {"lang": "de",
                   "lane_labels": {"backlog": "Inbox", "working": "In Arbeit",
                                   "review": "Abnahme", "done": "Fertig"}},
        "appearance": {"backdrop": "mesh"},
        # The refusal case: not one of the rule's options, so it is KEPT and
        # reported rather than adopted or dropped.
        "henry_permission_mode": "yolo",
    }, f)

auth.create_user("owner", PW, "owner")
boards.ensure_default()

from spine.ops import projects                                # noqa: E402
projects.sight_repo(ROOT, actor="owner", name="HelmDeck")
OTHER = os.path.join(os.path.dirname(ROOT), "netdance")
projects.sight_repo(OTHER, actor="owner", name="netdance")

from spine.storage import projectconfig                       # noqa: E402
here = projectconfig.project_key(ROOT)
there = projectconfig.project_key(OTHER)


def seed(project, patch):
    """Write, and REFUSE TO CONTINUE if the daemon declined.

    projectconfig.validate fails the WHOLE patch on one bad key by design, so a
    seed with a typo'd surface silently produces an empty panel and a
    screenshot that proves nothing - which is exactly what happened on the first
    run of this script (`rule.hands.own_hands.all`; that rule's only surface is
    `pm`). Asserting here turns that into a startup error instead of a quiet
    hole in the picture being judged."""
    _, err = projectconfig.write(project, patch, actor="owner", note="sandbox seed")
    assert not err, "SEED REFUSED for %s: %s" % (project, err)


seed(here, {"rule.hands.own_hands.pm": False,
            "rule.report.followup_attempts.all": 4})
seed(there, {"rule.initiative.estimate.pm": True})
# The ORPHAN. Straight through db, because every writer above it correctly
# refuses a key no table declares - which is exactly how a row like this comes
# to exist in the first place: it was declared once, and then it was not.
db.project_config_put(here, {"rule.report.retired_knob.all": "still on disk"})

# A board whose "review" column is deliberately unlabelled.
b = db.board_get(boards.DEFAULT_ID)
for c in b["columns"]:
    if c["station"] == "review":
        c["label"] = ""
db.board_put(b)

print("legacy  : %s" % legacypolicy.pending())

from http.server import ThreadingHTTPServer                   # noqa: E402
from spine.http.server import H                               # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

cfg = base64.b64encode(
    json.dumps({"baseUrl": "http://127.0.0.1:%d" % PORT}).encode()).decode()
print("sandbox : %s" % SANDBOX)
print("daemon  : http://127.0.0.1:%d  (owner/%s)" % (PORT, PW))
print("repos   : %s | %s" % (here, there))
print("#cfg    : #cfg=%s" % cfg)
sys.stdout.flush()
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    srv.shutdown()
