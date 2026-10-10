# -*- coding: utf-8 -*-
"""Headless test for HENRY'S LIVE TURN IN A ROOM (/rooms/live).

The CLI is stood in by a tiny python child that prints REAL stream-json frames
(message_start, a thinking block, a text block, a result); everything around it
is the real code: run_claude's stream fold, the livebuf fields, the room's
running signal, the route's membership gate, the hands feed for an owner run.

 1. run_claude streams: thinking tail + prose reach the live buffer WHILE the
    child is still running, and the result event is the return value.
 2. A half-typed <memory-save> never shows in the live prose.
 3. `running` is the observed turn count: true from accept to the end, false
    after, and the buffer is cleared with it.
 4. The route answers a member and 404s a stranger.
 5. An owner run's tool steps are mirrored in the chat's live-step shape, and
    hands._land_room ends the live spell AFTER the answer is posted.

Self-sandboxing: temp DB, no network, no real CLI. Run: py -3.12 ops/tests/test_room_live.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-roomlive-")

from spine.storage import db
db.ROOT = SANDBOX
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth
from cells.copilot.chat import rooms, room_henry, hands
from cells.copilot.routes import routes_rooms

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


for n, r in (("tien", "owner"), ("***", "client"), ("fremd", "client")):
    auth.create_user(n, "Correct-Horse-Battery-9", r, actor="test")
room = rooms.create("Team Alpha", "tien", ["***"])
RID = room["id"]

GATE = os.path.join(SANDBOX, "go")
CHILD = os.path.join(SANDBOX, "fake_cli.py")


def _ev(**kw):
    return json.dumps(kw)


frames = [
    _ev(type="stream_event", event={"type": "message_start", "message": {"usage": {}}}),
    _ev(type="stream_event", event={"type": "content_block_start", "content_block": {"type": "thinking"}}),
    _ev(type="stream_event", event={"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "ich ueberlege"}}),
    _ev(type="stream_event", event={"type": "content_block_start", "content_block": {"type": "text"}}),
    _ev(type="stream_event", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hallo ***. "}}),
    _ev(type="stream_event", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "<memory-save name=\"x\">halb"}}),
]
final = _ev(type="result", result="Hallo ***.", is_error=False, usage={}, modelUsage={})
with open(CHILD, "w", encoding="utf-8") as f:
    f.write("import sys, time, os\nsys.stdin.read()\n")
    for fr in frames:
        f.write("print(%r, flush=True)\n" % fr)
    f.write("while not os.path.exists(%r): time.sleep(0.05)\n" % GATE)
    f.write("print(%r, flush=True)\n" % final)

real_popen = subprocess.Popen
room_henry._argv = lambda: ["--output-format", "json", "x"]            # shape only; the child ignores it
import spine.agent.drivers as drivers
drivers._cmd_line = lambda argv: [sys.executable, CHILD]
room_henry._empty_cwd = lambda: SANDBOX

box = {}


def turn():
    room_henry.live_begin(RID)
    try:
        box["out"] = room_henry.run_claude("brief", "frage", timeout=60, live=RID)
    finally:
        room_henry.live_end(RID)


th = threading.Thread(target=turn, daemon=True)
th.start()
t0 = time.time()
while time.time() - t0 < 20 and not room_henry.live(RID)["text"]:
    time.sleep(0.05)
L = room_henry.live(RID)
check(th.is_alive() and L["running"], "1. running while the child is still alive")
check(L["thinking"] == "ich ueberlege", "1. the reasoning tail is live")
check(L["text"] == "Hallo ***.", "1/2. prose is live and the half-typed <memory-save> is cut: %r" % L["text"])
check(isinstance(L["since"], float), "3. since = the daemon's clock for the counter")

st, body = None, None


class _H:
    def __init__(self, who, path):
        self.path, self.sent = path, []
        self.user = who

    def _send(self, code, payload, *a, **k):
        self.sent.append((code, payload))


def call(who, rid):
    h = _H(who, "/rooms/live?room=" + rid)
    routes_rooms.rooms_live_get(h, {"name": who})
    return h.sent[0][0], json.loads(h.sent[0][1])


st, b = call("***", RID)
check(st == 200 and b["text"] == "Hallo ***.", "4. a member reads the live turn")
st, b = call("fremd", RID)
check(st == 404, "4. a stranger gets 404, same as an unknown room")

open(GATE, "w").close()
th.join(30)
check(not th.is_alive() and box["out"][0] == "Hallo ***." and box["out"][1].get("type") == "result",
      "1. the result event is the return value")
L = room_henry.live(RID)
check(not L["running"] and L["text"] == "" and L["since"] is None, "3. ended: not running, buffer cleared")

# 5. owner run: steps mirrored, live spell ends after the post
room_henry.live_begin(RID)
room_henry.live_steps(RID, [{"id": "a", "label": "Read x", "text": "x.py", "status": "completed", "ta": 1.0}])
L = room_henry.live(RID)
check(L["steps"] and L["steps"][0]["tool"] == "Read x" and L["steps"][0]["status"] == "completed",
      "5. owner-run steps arrive in the chat's live-step shape")
hands._land_room({"room": {"id": RID, "to": "tien"}, "user": "tien"}, "h1", "completed", "Antwort.", 1)
check(rooms.history(RID, "tien")[-1]["text"] == "Antwort.", "5. the answer is posted")
check(not room_henry.live(RID)["running"], "5. and only then the live spell is over")

print()
print("ROOM LIVE: all pinned - PASS" if not _fails else "ROOM LIVE: FAIL - %d" % len(_fails))
sys.exit(1 if _fails else 0)
