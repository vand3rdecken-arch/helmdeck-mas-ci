# -*- coding: utf-8 -*-
"""Pins the 2026-09-10 broker-queue fix (owner complaint, escalations.jsonl
id henry-followup-1789036727413): a henry-followup escalation must not queue
behind a slow non-followup _decide() call, and Henry's closing-JSON parser
must not be fooled by an earlier brace-shaped fragment in the model's reply.

Covers:
  1. _extract_json: the real trailing JSON survives an earlier, unrelated
     '{...}'-shaped fragment in the reply text - the bug behind the observed
     "ask failed: Expecting property name enclosed in double quotes".
  2. _dispatch_pass: a henry-followup escalation is dispatched on its own
     thread and is NOT blocked behind a slow non-followup escalation's
     synchronous _decide() call in the same pass.
  3. _dispatch_pass: a follow-up already in flight from a prior pass is not
     re-dispatched (no double-attempt / double-execute).

Run: py -3.12 ops/tests/test_henry_followup_priority.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    from cells.copilot.broker import henry_broker as hb

    # -- 1: _extract_json survives a stray earlier brace ---------------------
    print("\n_extract_json")
    real = {"action": "did", "card": "c1", "text": "fixed it", "why": "y"}
    txt = ("Sure, here's roughly what a config like {not: 'json', just: prose}"
           " would look like.\n\n" + __import__("json").dumps(real))
    got = hb._extract_json(txt)
    ok(got == real, "trailing JSON extracted even with an earlier brace-shaped fragment: %r" % (got,))

    ok(hb._extract_json('{"action": "ignore"}') == {"action": "ignore"},
       "plain single JSON reply still parses")
    ok(hb._extract_json("no json here at all") is None,
       "no braces at all -> None, not a crash")
    ok(hb._extract_json("prose only { still not json") is None,
       "an unterminated brace never parses -> None")

    # -- 2 + 3: _dispatch_pass concurrency ------------------------------------
    print("\n_dispatch_pass")
    orig_decide = hb._decide
    orig_give_up = hb._give_up
    events = []

    def fake_decide(esc):
        if esc["kind"] == hb._FOLLOWUP_KIND:
            events.append(("followup-done", esc["id"]))
        else:
            events.append(("other-start", esc["id"]))
            time.sleep(0.4)          # simulates a slow ship-decision/conflict judgement
            events.append(("other-done", esc["id"]))
        return True

    hb._decide = fake_decide
    hb._give_up = lambda esc: events.append(("gave-up", esc["id"]))

    try:
        esc_other = {"id": "e-other-1", "kind": "ship-decision", "attempts": 0, "card": None}
        esc_fu = {"id": "e-fu-1", "kind": hb._FOLLOWUP_KIND, "attempts": 0, "card": None}

        threads = hb._dispatch_pass([esc_other, esc_fu])
        ok(len(threads) == 1, "exactly one thread started, for the follow-up only")
        for th in threads:
            th.join(timeout=2)
        ok(not any(th.is_alive() for th in threads), "follow-up thread finished")

        fu_idx = events.index(("followup-done", "e-fu-1"))
        other_done_idx = events.index(("other-done", "e-other-1"))
        ok(fu_idx < other_done_idx,
           "follow-up finished WHILE the slow non-followup escalation was still running: %r" % (events,))

        # -- dedup: a follow-up still in flight is not re-dispatched --------
        print("\n_dispatch_pass: in-flight dedup")
        events.clear()
        slow_fu = {"id": "e-fu-2", "kind": hb._FOLLOWUP_KIND, "attempts": 0, "card": None}
        release = []
        def fake_decide_slow_fu(esc):
            time.sleep(0.4)
            events.append(("slow-followup-done", esc["id"]))
            release.append(1)
            return True
        hb._decide = fake_decide_slow_fu

        t1 = hb._dispatch_pass([slow_fu])
        ok(len(t1) == 1, "first pass dispatches the follow-up")
        t2 = hb._dispatch_pass([slow_fu])
        ok(len(t2) == 0, "second pass, while the first is still running, dispatches nothing new")

        t1[0].join(timeout=2)
        ok(release == [1], "the in-flight follow-up ran exactly once")
        ok(slow_fu["id"] not in hb._followups_inflight, "in-flight marker cleared after completion")

        t3 = hb._dispatch_pass([slow_fu])
        ok(len(t3) == 1, "a THIRD pass, after the follow-up finished, dispatches it again (still open)")
        t3[0].join(timeout=2)
    finally:
        hb._decide = orig_decide
        hb._give_up = orig_give_up

    print("\n%d failure(s)" % len(_fails))
    if _fails:
        sys.exit(1)
    print("all green")


if __name__ == "__main__":
    main()
