# -*- coding: utf-8 -*-
"""A throwaway daemon for RECORDING the question-channel demo clip (owner
card "15-Sekunden-Demo-Clip produzieren"): a card asks a question, the owner
answers from the phone/chat UI, the card continues.

Same shape as ops/tools/boards_verify_daemon.py - a sandbox store behind the
REAL request handler, so the recording drives the actual routes and the actual
QuestionPanel/chat components. The one deliberate fake is `sessions.steer`
(the same seam ops/tests/test_question_channel.py::test_answer fakes): a real
steer resumes an actual claude session, which a 15s marketing clip has no
business spawning. Everything up to and including validating the answer and
echoing it into the chat runs for real.

  py -3.12 ops/tools/demo_ask_daemon.py [port]

Ctrl-C to stop; the sandbox is a temp dir and is not cleaned up on purpose.
"""
import os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-askdemo-")
import daemon.paths
daemon.paths.DAEMON_ROOT = SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import db, events            # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET),
                    ("users", auth.USERS)):
    assert path.startswith(SANDBOX), \
        "REFUSING TO RUN: %s points at %s, not the sandbox" % (label, path)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8199
PW = "hunter2hunter2"
TID = "demo-ask-1"

db.init()
db.workspace_config_replace({"policy": {"lang": "de"}, "appearance": {"backdrop": "mesh"}})
auth.create_user("owner", PW, "owner")

from spine.ops import ask                        # noqa: E402
from cells.copilot.chat import card_mirror        # noqa: E402
from cells.engineer.cards import sessions         # noqa: E402

BLOCK = (
    '<helmdeck-ask>\n'
    '{"questions": [{"question": '
    '"Bevor ich weitermache: Erinnerung per Web-Push oder E-Mail schicken?", '
    '"header": "Kanal", "options": ['
    '{"label": "Web-Push", "description": "Kommt sofort aufs Handy"}, '
    '{"label": "E-Mail", "description": "Sammelt sich im Digest"}]}]}\n'
    '</helmdeck-ask>'
)
QUESTION, _ = ask.parse(BLOCK)

RUN_DIR = os.path.join(SANDBOX, TID)
os.makedirs(RUN_DIR, exist_ok=True)
TRACK = {"id": TID, "status": "needs_you", "lane": "working",
         "task": "Deploy-Erinnerung einrichten", "branch": "feat/" + TID,
         "repo": ROOT, "run_dir": RUN_DIR, "worktree": "", "turns": 1,
         "session_id": "sess-" + TID, "ai_cost": 0.0, "tokens_in": 0,
         "tokens_out": 0, "models": [], "created": "2026-09-13 12:00:00",
         "updated": "2026-09-13 12:00:00", "rank": 0, "driver": "claude",
         "actor": "owner", "client": "", "priority": "medium",
         "question": QUESTION}
db.track_put(TRACK)
card_mirror.say_card(TRACK, "question", ask.summary(QUESTION), question=QUESTION)

# The one fake: sessions.answer_question ends by resuming the session via a
# real steer() - here it instead simulates the worker picking the decision
# back up, on a short delay so the clip shows a beat of "thinking" before the
# card continues. Everything BEFORE this (validating the pick, rejecting a
# stale/empty answer, echoing the owner's tap into the chat) is untouched.
_orig_steer = sessions.steer


def _fake_steer(tid, text, **kw):
    def _later():
        time.sleep(1.6)
        t = db.track_get(tid) or dict(TRACK)
        t["status"] = "done"
        t["last_reply"] = "Web-Push eingerichtet und aktiv. Fertig."
        db.track_put(t)
        card_mirror.say_card(t, "result", t["last_reply"])
    threading.Thread(target=_later, daemon=True).start()
    return {"id": tid}


sessions.steer = _fake_steer

from http.server import ThreadingHTTPServer      # noqa: E402
from spine.http.server import H                  # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

print("sandbox : %s" % SANDBOX)
print("daemon  : http://127.0.0.1:%d  (owner/%s)" % (PORT, PW))
print("card    : %s (open /chat, answer the question, watch it continue)" % TID)
sys.stdout.flush()
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    srv.shutdown()
