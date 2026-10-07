# -*- coding: utf-8 -*-
"""A compaction is ONE typed feed item (Paseo CompactionTimelineItem), not note lines.

Owner 2026-10-07, screenshot of card chat 20261007-124850-direct: the
compaction showed as plain note lines ("Verdichtung laeuft" TWICE at 13:28:49,
"AUTO-COMPACT: Kontext bei 98%"), and Henry's steer decision stood twice
(13:28:49 "HENRY entschieden", 13:28:50 "Henry (...): steer"). Pinned here, on
behaviour the old code fails:

  1. card path: frames `status: compacting` -> `compact_boundary` leave exactly
     ONE compaction step in the card's timeline store - loading folded into
     completed in place, carrying pre/post tokens + duration_ms
  2. a compaction the runtime never closed is settled (never a spinner left)
  3. Henry's chat: the same two states as rows sharing one cid, and NO `act`
     note line for the compaction
  4. one waiter or many: no note line per waiter
  5. a broker decision leaves ONE line on the card, not an audit + a report

Sandboxed: the db is a temp file (db.py refuses the live one), no real process.
"""
import json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

tmp = tempfile.mkdtemp(prefix="compaction_item_")
from spine.storage import db
db.DBPATH = os.path.join(tmp, "test.db")
db.init()

from spine.agent import drivers, timeline_store
from cells.copilot.chat import copilot as c
from cells.engineer.cards import sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# --- 1/2. the driver folds the frames into one feed item ----------------------
RUN = os.path.join(tmp, "card-1")


def make_session():
    real_spawn = drivers._ClaudeSession._spawn
    drivers._ClaudeSession._spawn = lambda self: None
    drivers._record_pid = lambda pid, spawn_time=None: None
    drivers._forget_pid = lambda pid: None
    try:
        s = drivers._ClaudeSession({}, {"id": "card-1", "worktree": ".", "session_id": "s1",
                                         "run_dir": RUN})
    finally:
        drivers._ClaudeSession._spawn = real_spawn
    s.brief = ""
    s._alive = True
    return s


def new_cur():
    return {"parts": [], "result": None, "session_id": "s1", "done": threading.Event(),
            "live_key": "k", "last_flush": 0.0, "last_event": time.time()}


def items(run_dir):
    return [s for s in timeline_store.read(run_dir) if s.get("kind") == "compaction"]


s = make_session()
s._cur = new_cur()
s._on_event({"type": "system", "subtype": "status", "status": "compacting"})
check([i.get("event") for i in items(RUN)] == ["loading"], "status:compacting opens ONE loading item")
s._on_event({"type": "system", "subtype": "status", "status": "compacting"})
check(len(items(RUN)) == 1, "a repeated status frame does not open a second item")
s._on_event({"type": "system", "subtype": "compact_boundary", "session_id": "s1",
             "compact_metadata": {"trigger": "auto", "pre_tokens": 954000,
                                  "post_tokens": 4500, "duration_ms": 17785}})
it = items(RUN)
check(len(it) == 1 and it[0].get("event") == "completed",
      "compact_boundary completes the SAME item in place (one row, not two)")
check((it[0].get("pre_tokens"), it[0].get("post_tokens"), it[0].get("duration_ms"),
       it[0].get("trigger")) == (954000, 4500, 17785, "auto"),
      "the item carries pre_tokens, post_tokens, duration_ms and trigger")

RUN2 = os.path.join(tmp, "card-2")
s2 = make_session()
s2.run_dir = RUN2
s2._cur = new_cur()
s2._on_event({"type": "system", "subtype": "status", "status": "compacting"})
drivers.settle_compaction(RUN2, "interrupted")
check([i.get("event") for i in items(RUN2)] == ["interrupted"],
      "an item the runtime never closed is settled - no spinner left behind")
drivers.settle_compaction(RUN2, "completed")
check([i.get("event") for i in items(RUN2)] == ["interrupted"],
      "settling twice is a no-op (the boundary/first verdict stands)")

# --- 3. Henry's chat: rows sharing one cid, no note line -----------------------
class _Out:
    def __init__(self, lines):
        self._l = lines

    def __iter__(self):
        return iter(self._l)


class _Popen:
    def __init__(self, lines):
        self.stdin = self
        self.stdout = _Out(lines)

    def write(self, _):
        pass

    def close(self):
        pass

    def wait(self, timeout=None):
        pass


def frames(boundary=True):
    f = [{"type": "system", "subtype": "status", "status": "compacting", "session_id": "sess-a"},
         {"type": "system", "subtype": "status", "status": None, "session_id": "sess-a"}]
    if boundary:
        f.append({"type": "system", "subtype": "compact_boundary", "session_id": "sess-a",
                  "compact_metadata": {"trigger": "auto", "pre_tokens": 180000,
                                       "post_tokens": 62000, "duration_ms": 41000}})
    f.append({"type": "result", "session_id": "sess-a", "result": "",
              "usage": {"input_tokens": 0, "output_tokens": 0}, "modelUsage": {}, "total_cost_usd": 0.0})
    return [json.dumps(x) for x in f]


import subprocess as _sp
_orig = _sp.Popen
sessions._compact_marks = lambda sid: 0


def rows(user="owner"):
    return [e for e in c._entries(user) if e.get("cls") == "compaction"]


c._save_sessions({"owner": "sess-a"})
c._save_stats({"owner": {"ctx_tokens": 180000, "ctx_window": 200000, "turns": 5, "cost": 0.0}})
_sp.Popen = lambda *a, **k: _Popen(frames())
c._maybe_compact("owner")
_sp.Popen = _orig
r = rows()
check([e.get("event") for e in r] == ["loading", "completed"], "chat gets loading then completed rows")
check(len({e.get("cid") for e in r}) == 1, "both rows share one cid (the client folds them to one)")
check((r[-1].get("pre_tokens"), r[-1].get("post_tokens"), r[-1].get("duration_ms")) == (180000, 62000, 41000),
      "the completed row carries pre/post tokens and duration")
check(not [e for e in c._entries("owner") if e.get("cls") == "act" and "AUTO-COMPACT" in (e.get("text") or "")],
      "no 'AUTO-COMPACT' act note in the chat")

# --- 4. waiters write no note line --------------------------------------------
class _Log:
    def __init__(self):
        self.notes = []

    def log(self, kind, detail, **kw):
        self.notes.append(detail)


ev = threading.Event()
sessions._compacting["tw"] = ev
a, b = _Log(), _Log()
ts = [threading.Thread(target=lambda lg=lg: sessions.await_compaction("tw", lg, timeout=5)) for lg in (a, b)]
for t_ in ts:
    t_.start()
time.sleep(0.2)
ev.set()
for t_ in ts:
    t_.join(5)
sessions._compacting.pop("tw", None)
check(not a.notes and not b.notes, "two steers waiting on one compaction write ZERO note lines (was one each)")

# --- 5. one card line per broker decision -------------------------------------
# REAL _decide -> REAL _audit + _notify_owner -> REAL ActionLog rows of the card.
from spine.ops import runs
from spine.ops.actionlog import read_timeline
from spine.comms import notify
from cells.copilot.broker import henry_broker as hb
runs.REC = os.path.join(tmp, "runs")
os.makedirs(runs.REC, exist_ok=True)
notify.push_fcm = lambda *a, **k: False
CARD = "c-steer"
rd = os.path.join(runs.REC, CARD)
os.makedirs(rd, exist_ok=True)
db.track_put({"id": CARD, "task": "x", "status": "running", "lane": "working",
              "run_dir": rd, "worktree": tmp, "repo": tmp})
class _Esc:
    def record_attempt(self, i): pass
    def record_note(self, i, n): pass
    def record_decision(self, i, a, card=None, why="", kind=""): pass
hb.escalations = _Esc()
dec = {"action": "steer", "card": CARD, "lane": "", "text": "mach weiter", "why": "darum"}
hb._ask = lambda *a, **k: dict(dec)
hb._hands_on_ask = lambda *a, **k: dict(dec)
hb._dispatcher_privileged = lambda t: True
hb._card_log_tail = lambda *a, **k: ""
hb._audit_context = lambda t: ""
hb._snapshot = lambda: ""
hb._judgement_policy = lambda t: "policy"
hb._execute = lambda *a, **k: True          # the steer itself is not under test
check(hb._decide({"id": "e1", "kind": "stuck", "card": CARD, "attempts": 0, "detail": "x"}) is True,
      "the decision closes")
lines = [r.get("detail") or "" for r in read_timeline(rd) if r.get("kind") == "note"]
check(len(lines) == 1, "ONE note on the card for a steer decision, not an audit line AND a report (got %d)" % len(lines))
check(lines and "mach weiter" in lines[0], "...and it is the full 'Henry (kind): steer - text' line")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("compaction-item: all pinned - PASS")
