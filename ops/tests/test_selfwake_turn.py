# -*- coding: utf-8 -*-
"""A turn the CLI starts BY ITSELF must be adopted, not ignored.

Measured live 2026-10-11 (card 20261011-183135-machine-2): a background task
reported just after the turn ended, the CLI woke itself and worked five more
minutes with no turn open. Nothing folded its reply or cost, the card kept the
stale "not done yet" text as needs_you, and the idle sweeper tree-killed the
process mid-turn. Runs the REAL driver against the fake CLI (__SELFWAKE__):
result -> (no user message) assistant frame -> result.

Self-sandboxing: temp db + settings + run dirs, no daemon, no network."""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp()
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.agent import drivers
from cells.engineer.cards import sessions

_WRAP = os.path.join(tempfile.mkdtemp(), "fake_claude.cmd")
with open(_WRAP, "w", encoding="utf-8") as _f:
    _f.write('@echo off\r\n"%s" "%s" %%*\r\n'
             % (sys.executable, os.path.join(HERE, "fake_claude.py")))
drivers.CLAUDE = _WRAP
# the real brief (13k+) overflows the 8191-char cmd.exe line the fake-CLI wrapper
# goes through (test_driver_session.py fails the same way on a clean tree) - the
# brief is irrelevant to what this pins, so stub it.
drivers.harness.brief = lambda *a, **k: "brief"
drivers._PIDFILE = os.path.join(tempfile.mkdtemp(), "driver_pids.json")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _card(tid, status="needs_you", lane="working"):
    run_dir = os.path.join(SANDBOX, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "status": status, "lane": lane, "task": "t",
         "branch": "b-" + tid, "worktree": tempfile.mkdtemp(), "run_dir": run_dir,
         "session_id": None, "turns": 1, "updated": "2026-10-11 18:41:05"}
    db.track_put(t)
    return t


def _wait(pred, secs=15.0):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    return False


def _first_turn(tid, lane="working", status="needs_you"):
    t = _card(tid, "running", lane)
    s = drivers._get_session({"type": "claude", "timeout": 30}, t)
    _, res, _ = s.run_turn("__SELFWAKE__", t["run_dir"])
    # what sessions._finish_turn does at the end of the sent turn
    def _park(tt):
        tt["status"] = status
        tt["last_reply"] = res
    sessions._mutate(tid, _park)
    return s, res


def test_adopts_and_settles():
    tid = "t-selfwake"
    s, res = _first_turn(tid)
    check(res == "first", "the sent turn returned its own result (got %r)" % res)
    check(_wait(lambda: db.track_get(tid)["status"] == "running"),
          "the CLI's own turn flips the card back to running")
    check(drivers.turn_active(tid), "turn_active sees the adopted turn")
    gone = drivers.sweep_idle(ttl=0)
    check(tid not in gone and s.alive(),
          "idle sweep does NOT kill the adopted turn mid-flight")
    check(_wait(lambda: db.track_get(tid)["status"] == "needs_you"
                and db.track_get(tid).get("turns") == 2),
          "adopted turn settles through the one finisher (turns 1 -> 2)")
    t = db.track_get(tid)
    check(t.get("last_reply") == "second",
          "reply of the self-started turn is the card's reply (got %r)" % t.get("last_reply"))
    check((t.get("ai_cost") or 0) >= 0.005, "its cost is booked (got %r)" % t.get("ai_cost"))
    check(not drivers.turn_active(tid), "no turn left open afterwards")
    drivers.cancel(tid)


def test_not_adopted_when_card_is_closed():
    tid = "t-selfwake-done"
    s, _ = _first_turn(tid, lane="done", status="accepted")
    time.sleep(3.2)                               # let the fake CLI run its whole self-turn
    t = db.track_get(tid)
    check(t["status"] == "accepted" and t.get("turns") == 1,
          "a closed card is left alone (status %r, turns %r)" % (t["status"], t.get("turns")))
    check(not drivers.turn_active(tid), "no turn opened on a closed card")
    drivers.cancel(tid)


def test_not_adopted_while_a_question_waits():
    tid = "t-selfwake-q"
    s, _ = _first_turn(tid)
    sessions._mutate(tid, lambda tt: tt.__setitem__("question", {"kind": "x"}))
    time.sleep(3.2)
    t = db.track_get(tid)
    check(t["status"] == "needs_you" and t.get("turns") == 1,
          "a card with an open question is not auto-resumed (turns %r)" % t.get("turns"))
    drivers.cancel(tid)


if __name__ == "__main__":
    test_adopts_and_settles()
    test_not_adopted_when_card_is_closed()
    test_not_adopted_while_a_question_waits()
    print("\nFAILED: %d" % len(_fails) if _fails else "\nall ok")
    sys.exit(1 if _fails else 0)
