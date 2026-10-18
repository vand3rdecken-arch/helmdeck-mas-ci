# -*- coding: utf-8 -*-
"""Pins owner decree 2026-10-18: a worker's question reaches the owner DIRECTLY
and, in parallel, Henry hears it as a `worker-question` escalation and may
answer the trivial ones himself (broker verb `answer`).

  1. A finished turn that ASKS emits worker-question once (dedup on the open
     one) carrying the request_id; a turn that does not ask emits nothing.
  2. `answer` relays Henry's text through sessions.answer_question with the
     escalation's request_id and actor=henry.
  3. A question the owner already settled/replaced is a quiet no-op - never a
     second steer (the owner may have been faster than Henry's judgement).
  4. A multi-question ask is not settled by one sentence - owner decides.

Self-sandboxing like test_direct_cards_land. Run: py -3.12 ops/tests/test_worker_question_henry.py
"""
import os, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-wq-")
from spine.storage import db as _db
_db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
_db.init()
from spine.registry import escalations
from spine.storage import trackstore
from cells.engineer.cards import sessions, turnrunner
from cells.copilot.broker import henry_broker as hb


class FakeDB:
    def __init__(self):
        self.tracks = {}
    def tracks_all(self):
        return [dict(t) for t in self.tracks.values()]
    def tracks_replace(self, ts):
        self.tracks = {t["id"]: dict(t) for t in ts}
    def track_put(self, t):
        self.tracks[t["id"]] = dict(t)
    def track_get(self, tid):
        t = self.tracks.get(tid)
        return dict(t) if t else None


def check(desc, ok):
    assert ok, desc
    print("  ok: " + desc)


events.emit = lambda *a, **k: None
trackstore._db = FakeDB()
BUS = []
escalations._append = lambda rec: (BUS.append(dict(rec, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))), BUS[-1])[1]
escalations.records = lambda: list(BUS)


def opens(kind, card):
    return [r for r in BUS if r.get("event") == "open" and r.get("kind") == kind and r.get("card") == card]


def ask_q(qid, n=1):
    return {"id": qid, "kind": "choice", "questions": [
        {"question": "Welche Datei?%d" % i, "header": "F%d" % i,
         "options": [{"label": "a.py"}, {"label": "b.py"}]} for i in range(n)]}


T = {"id": "c1", "branch": "c1", "run_dir": tempfile.mkdtemp(prefix="hd-wq-run-"),
     "lane": "working", "status": "needs_you", "question": ask_q("q-1")}
trackstore._db.track_put(T)

# -- 1) emit ------------------------------------------------------------------
turnrunner._emit_worker_question(dict(T, question=None), "needs_you")
check("1. no question -> nothing", not opens("worker-question", "c1"))
turnrunner._emit_worker_question(T, "needs_you")
check("1. reason != question -> nothing", not opens("worker-question", "c1"))
turnrunner._emit_worker_question(T, "question")
o = opens("worker-question", "c1")
check("1. a question emits once, with the request_id", len(o) == 1 and "request_id: q-1" in o[0]["detail"])
turnrunner._emit_worker_question(T, "question")
check("1. dedup while Henry has not judged", len(opens("worker-question", "c1")) == 1)

# -- 2..4) the verb ---------------------------------------------------------
CALLS = []
sessions.answer_question = lambda tid, answers, request_id="", actor="owner", echo_chat=True: CALLS.append(
    (tid, answers, request_id, actor))
ESC = {"id": "worker-question-1", "kind": "worker-question", "card": "c1",
       "detail": "request_id: q-1\nDer Worker fragt"}

ok = hb._execute("answer", "c1", "", "a.py", ESC)
check("2. answer relays through answer_question as henry",
      ok and CALLS == [("c1", {"F0": "a.py"}, "q-1", "henry")])

CALLS.clear()
ok = hb._execute("answer", "c1", "", "a.py", dict(ESC, detail="request_id: q-OLD\n"))
check("3. a replaced question is a quiet no-op", ok and not CALLS)

gone = dict(T); gone.pop("question")
trackstore._db.track_put(gone)
ok = hb._execute("answer", "c1", "", "a.py", ESC)
check("3. an already answered question is a quiet no-op", ok and not CALLS)

trackstore._db.track_put(dict(T, question=ask_q("q-1", n=2)))
ok = hb._execute("answer", "c1", "", "a.py", ESC)
check("4. several questions: Henry sends nothing, the owner decides", ok and not CALLS)

ok = hb._execute("answer", "c1", "", "  ", ESC)
check("2. empty answer text stays open", ok is False and not CALLS)

print("test_worker_question_henry: PASS")
