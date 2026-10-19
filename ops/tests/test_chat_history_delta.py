# -*- coding: utf-8 -*-
"""GET /chat/history?after=SEQ sends only what changed (owner 2026-10-19: "warum sendet so viel und nicht
nur diff wie bei paseo"), and the escalation fold behind its followups reads only the bus tail.

  1. after = newest seq -> delta, no rows; after = newest-3 -> delta, exactly those 3 rows;
  2. a gap wider than the window, or a cursor past the store's end -> full window, delta=False;
  3. no cursor -> the full window as before (delta=False);
  4. escalations.fold() equals a full re-fold after appends, and handing out copies keeps the cache clean;
  5. a db swapped underneath (sandbox repoint) re-folds from zero instead of serving the old state.

Sandboxed db, no daemon.  Run: py -3.12 ops/tests/test_chat_history_delta.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.storage import db                                  # noqa: E402

db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-chat-delta-"), "test.db")
db.init()
from cells.copilot.chat import copilot                        # noqa: E402
from spine.registry import escalations                        # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def full_fold():
    out = {}
    for r in db.escalations_rows():
        escalations._fold_into(out, r)
    return out


def main():
    for i in range(200):
        db.chat_append("owner", [{"role": "user", "kind": "text", "text": "m%d" % i, "ts": "10:00"}])
    top = copilot.history("owner")["messages"][-1]["seq"]

    d = copilot.history("owner", after=top)
    check(d["delta"] and d["messages"] == [], "cursor at the end -> empty delta")
    d = copilot.history("owner", after=top - 3)
    check(d["delta"] and [m["seq"] for m in d["messages"]] == [top - 2, top - 1, top],
          "cursor 3 behind -> exactly the 3 new rows")
    d = copilot.history("owner", after=top - 150)
    check(not d["delta"] and len(d["messages"]) == 80, "gap wider than the window -> full window")
    d = copilot.history("owner", after=top + 10)
    check(not d["delta"] and len(d["messages"]) == 80, "cursor past the end -> full window")
    d = copilot.history("owner")
    check(not d["delta"] and len(d["messages"]) == 80, "no cursor -> full window")

    a = escalations.emit("henry-followup", "", "first")
    check(escalations.fold() == full_fold(), "fold == full re-fold after open")
    escalations.record_note(a, "n1")
    escalations.record_attempt(a)
    escalations.record_decision(a, "done", why="ok")
    got = escalations.fold()
    check(got == full_fold() and got[a]["closed"] and got[a]["attempts"] == 1,
          "incremental fold folds note/attempt/decision")
    got[a]["closed"] = "mutated"
    check(escalations.fold()[a]["closed"] is True, "callers get copies, the cache stays clean")

    db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-chat-delta2-"), "test.db")
    db._local.c = None
    db.init()
    check(escalations.fold() == {}, "swapped db re-folds from zero")

    print("chat history delta: %s" % ("PASS" if not _fails else "FAIL (%d)" % len(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
