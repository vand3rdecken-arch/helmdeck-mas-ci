# -*- coding: utf-8 -*-
"""Headless test for AUTO-CONTINUE on background completion (Phase 2.5).

The trap being closed: a turn that ends while a worker-launched background task
is still running was labelled needs_you. The owner had nothing to do, and
nothing would ever wake the card again - a finished build just sat there.

What this pins:
 1. background_wait() reads the runtime's OWN completion signal: a
    run_in_background tool_use counts as outstanding until the
    <task-notification> carrying its tool-use-id arrives.
 2. It is scoped to the LAST turn, so a task completed in an earlier turn can
    never strand a card.
 3. A parked card waiting on a background task is labelled waiting_on=background
    (not "waiting for you") and is NEVER pushed.
 4. drivers._running_cards() protects such a session from idle eviction -
    without that the sweeper would tree-kill the very task being waited on.
 5. _sweep_background() continues the card exactly when the task has reported,
    and gives up (handing the card back to the owner) after the max wait.

Self-sandboxing: temp sqlite DB, temp events/settings, and a hand-written
session transcript - no claude process, no network.
Run: py -3.12 tests/test_background_continue.py
"""
import json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-bg-")

from daemon.spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from daemon.spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from daemon.spine.agent import claude_sessions, drivers
from daemon.cells.engineer import sessions
from daemon.spine.ops.actionlog import ActionLog

PROJECTS = os.path.join(SANDBOX, "projects", "proj")
os.makedirs(PROJECTS, exist_ok=True)
claude_sessions.PROJECTS = os.path.dirname(PROJECTS)

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _rec(**kw):
    return kw


def _steer(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _bg_call(tool_id, desc):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": "Bash",
         "input": {"command": "./gradlew build", "description": desc,
                   "run_in_background": True}}]}}


def _notification(tool_id):
    return {"type": "user", "message": {"role": "user", "content":
        "<task-notification>\n<task-id>x</task-id>\n<tool-use-id>%s</tool-use-id>\n"
        "<status>completed</status>\n</task-notification>" % tool_id}}


def _write_session(sid, records):
    with open(os.path.join(PROJECTS, sid + ".jsonl"), "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _track(tid, sid, **extra):
    run_dir = os.path.join(SANDBOX, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "status": "needs_you", "lane": "working", "task": "t",
         "branch": tid, "run_dir": run_dir, "worktree": "", "turns": 1,
         "session_id": sid, "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0,
         "models": [], "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    t.update(extra)
    db.track_put(t)
    return t


def test_detection():
    print("background_wait:")
    _write_session("s-open", [_steer("bau das"), _bg_call("t1", "gradle build")])
    t = _track("c-open", "s-open")
    bg = claude_sessions.background_wait(t)
    check(bg and bg["n"] == 1, "outstanding background task detected")
    check(bg and "gradle build" in bg["names"][0], "task described by its description")

    _write_session("s-done", [_steer("bau das"), _bg_call("t1", "gradle build"),
                              _notification("t1")])
    check(claude_sessions.background_wait(_track("c-done", "s-done")) is None,
          "a reported task is not outstanding")

    # a task finished in an EARLIER turn must not strand the next turn
    _write_session("s-prev", [_steer("bau das"), _bg_call("t1", "gradle"),
                              _notification("t1"), _steer("und jetzt das")])
    check(claude_sessions.background_wait(_track("c-prev", "s-prev")) is None,
          "scan is scoped to the last turn")

    _write_session("s-none", [_steer("hallo")])
    check(claude_sessions.background_wait(_track("c-none", "s-none")) is None,
          "a turn with no background task reports nothing")


def test_cue_and_no_push():
    print("_settle_reply cue:")
    _write_session("s-cue", [_steer("bau das"), _bg_call("t1", "gradle build")])
    t = _track("c-cue", "s-cue")
    log = ActionLog(t["run_dir"])
    reason = sessions._settle_reply(t, "Build laeuft im Hintergrund.", log)
    check(reason == "background", "reason is 'background', not 'needs_you'")
    check(t["waiting_on"] == "background", "card labelled waiting_on=background")
    check(t["background"]["n"] == 1 and t["background"].get("since"),
          "background payload carries count + start time")

    from daemon.spine.comms import notify
    pushed = []
    orig = notify.push_fcm
    notify.push_fcm = lambda title, body, track_id="": pushed.append(title)
    try:
        notify.card_event(t, "background")
        check(not pushed, "a background wait NEVER pushes (not the owner's move)")
        notify.card_event(t, "needs_you")
        check(len(pushed) == 1, "an ordinary needs_you still pushes")
    finally:
        notify.push_fcm = orig

    # a later turn with nothing outstanding clears the cue
    _write_session("s-cue", [_steer("bau das"), _bg_call("t1", "g"), _notification("t1")])
    reason = sessions._settle_reply(t, "Fertig. DELIVERED", log)
    check(reason == "needs_you" and t["waiting_on"] == "you" and "background" not in t,
          "cue cleared once the task reported")


def test_idle_eviction_guard():
    print("idle-eviction guard:")
    _track("c-bgwait", "s-x", waiting_on="background", status="needs_you")
    _track("c-plain", "s-y", status="needs_you")
    protected = drivers._running_cards()
    check("c-bgwait" in protected,
          "a card waiting on a background task is protected from idle eviction")
    check("c-plain" not in protected, "an ordinary parked card is still evictable")


def _settle(steers, want, timeout=5.0):
    """The continuation runs OFF the watcher thread (a turn can take 30 min and
    must not stall the loop), so wait for it instead of assuming it already
    happened - and give a negative case time to prove itself wrong too."""
    deadline = time.time() + timeout
    while len(steers) < want and time.time() < deadline:
        time.sleep(0.02)
    if want == 0:
        time.sleep(0.35)          # let a wrong steer show up rather than pass by luck
    return steers


def test_auto_continue():
    print("_sweep_background:")
    steers = []
    orig = sessions.steer
    sessions.steer = lambda tid, text, **kw: steers.append((tid, text, kw))
    try:
        # still running -> left alone
        _write_session("s-run", [_steer("bau"), _bg_call("t1", "gradle")])
        _track("c-run", "s-run", waiting_on="background",
               background={"n": 1, "names": ["gradle"], "since": time.time()})
        sessions._sweep_background()
        check(not _settle(steers, 0), "a card whose task is still running is not steered")

        # reported -> continued automatically
        _write_session("s-fin", [_steer("bau"), _bg_call("t1", "gradle"), _notification("t1")])
        _track("c-fin", "s-fin", waiting_on="background",
               background={"n": 1, "names": ["gradle"], "since": time.time()})
        sessions._sweep_background()
        _settle(steers, 1)
        check(len(steers) == 1 and steers[0][0] == "c-fin",
              "a finished task continues the card automatically")
        check(steers[0][2].get("source") == "background-task",
              "the follow-up is attributed to the background task, not the owner")
        after = db.track_get("c-fin")
        check(after.get("waiting_on") == "you" and "background" not in after,
              "cue cleared when the card is continued")

        # REGRESSION: a missing/rotated transcript reads as "unknown", never as
        # "finished". Treating it as finished auto-steered cards - real money
        # spent on a guess (caught by this test during development).
        steers.clear()
        _track("c-gone", "s-does-not-exist", waiting_on="background",
               background={"n": 1, "names": ["gradle"], "since": time.time()})
        sessions._sweep_background()
        check(not _settle(steers, 0), "an unreadable transcript is NOT mistaken for completion")

        # give-up window: never auto-steer a task that never reports
        steers.clear()
        _write_session("s-old", [_steer("bau"), _bg_call("t1", "gradle")])
        _track("c-old", "s-old", waiting_on="background",
               background={"n": 1, "names": ["gradle"],
                           "since": time.time() - sessions._BG_MAX_WAIT_S - 10})
        sessions._sweep_background()
        check(not _settle(steers, 0), "a task past the max wait is not auto-steered")
        check(db.track_get("c-old").get("waiting_on") == "you",
              "it is handed back to the owner instead")

        # kill-switch
        steers.clear()
        events.save_settings({"policy": {"auto_continue": False}})
        _write_session("s-off", [_steer("bau"), _bg_call("t1", "g"), _notification("t1")])
        _track("c-off", "s-off", waiting_on="background",
               background={"n": 1, "names": ["g"], "since": time.time()})
        sessions._sweep_background()
        check(not _settle(steers, 0), "policy.auto_continue=false disables auto-continue")
        # ...but the kill-switch gates only the STEER. The cue must still fall
        # back to 'you' when nothing is outstanding - stuck at 'background' the
        # card looked blocked forever AND kept idle-eviction protection.
        check(db.track_get("c-off").get("waiting_on") == "you",
              "cue still clears with auto-continue off (done task never blocks)")
        events.save_settings({"policy": {"auto_continue": True}})

        # off the active lanes: same split - no steer, but the cue clears
        steers.clear()
        _write_session("s-lane", [_steer("bau"), _bg_call("t1", "g"), _notification("t1")])
        _track("c-lane", "s-lane", lane="done", waiting_on="background",
               background={"n": 1, "names": ["g"], "since": time.time()})
        sessions._sweep_background()
        check(not _settle(steers, 0), "a card off working/review is not steered")
        check(db.track_get("c-lane").get("waiting_on") == "you",
              "its cue clears anyway (no eternal eviction protection)")
    finally:
        sessions.steer = orig


test_detection()
test_cue_and_no_push()
test_idle_eviction_guard()
test_auto_continue()

print()
if _fails:
    print("FAILED: %d check(s): %s" % (len(_fails), "; ".join(_fails)))
    sys.exit(1)
print("ALL BACKGROUND AUTO-CONTINUE CHECKS PASSED")
