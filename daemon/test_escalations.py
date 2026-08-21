# -*- coding: utf-8 -*-
"""Pins the Henry exception broker (owner decree 2026-08-21, dual
architecture): harness points EMIT, Henry DECIDES, code only executes his
bounded verb; append-only store, state folded not flagged; 2-attempt cap.

Self-sandboxing: escalation log redirected to a temp file, Henry's model
call (pm._ask), steer, deploy hook and notify all stubbed - nothing touches
the live board, a real model or the phone.

Run: py -3.12 daemon/test_escalations.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daemon.spine.registry import escalations as esc
from daemon.cells.pm import pm
from daemon.spine.storage import events


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-esc-")
    saved = (esc.ESC_PATH, pm._ask, events.settings, events.emit)
    try:
        esc.ESC_PATH = os.path.join(tmp, "escalations.jsonl")
        events.settings = lambda: {}
        events.emit = lambda *a, **k: None

        # -- emit + fold: append-only, state derived --------------------------
        eid = esc.emit("aborted-by-restart", card=None, detail="apk build")
        opens = esc.list_open()
        assert len(opens) == 1 and opens[0]["id"] == eid and opens[0]["attempts"] == 0
        print("PASS emit -> open, folded from the log")

        # -- Henry decides notify_owner: executes, closes, audits -------------
        notified = []
        esc._notify_owner = lambda text, t: notified.append(text)
        pm._ask = lambda prompt, model="": {"action": "notify_owner", "card": "",
                                            "text": "build neu anstossen?", "why": "restart"}
        assert esc._decide(opens[0]) is True
        assert not esc.list_open(), "decided escalation must fold closed"
        assert notified and "neu anstossen" in notified[0]
        print("PASS decide(notify_owner) -> executed + closed")

        # -- malformed decision stays open, attempts counted ------------------
        eid2 = esc.emit("conflict-unresolved", card=None, detail="x")
        pm._ask = lambda prompt, model="": {"action": "levitate"}
        e2 = [e for e in esc.list_open() if e["id"] == eid2][0]
        assert esc._decide(e2) is False
        e2 = [e for e in esc.list_open() if e["id"] == eid2][0]
        assert e2["attempts"] == 1, "attempt must be folded: %r" % e2
        print("PASS malformed verb -> stays open, attempt recorded")

        # -- cap: after MAX attempts the loop gives up loudly, closes ---------
        esc._decide(e2)   # attempt 2, still malformed
        e2 = [e for e in esc.list_open() if e["id"] == eid2][0]
        assert e2["attempts"] >= esc._MAX_ATTEMPTS
        notified.clear()
        esc._give_up(e2)
        assert not [e for e in esc.list_open() if e["id"] == eid2], "give-up must close"
        assert notified, "give-up must notify the owner"
        print("PASS 2-attempt cap -> give up, owner notified, closed")

        # -- Henry's ask failing entirely never crashes the broker ------------
        eid3 = esc.emit("deploy-red", card=None, detail="boom")
        def _raise(*a, **k): raise RuntimeError("model down")
        pm._ask = _raise
        e3 = [e for e in esc.list_open() if e["id"] == eid3][0]
        assert esc._decide(e3) is False and [e for e in esc.list_open() if e["id"] == eid3]
        print("PASS model failure -> escalation survives, no crash")

        print("ALL PASS")
    finally:
        (esc.ESC_PATH, pm._ask, events.settings, events.emit) = saved


if __name__ == "__main__":
    main()
