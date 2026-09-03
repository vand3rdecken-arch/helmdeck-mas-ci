# -*- coding: utf-8 -*-
"""Headless test for the PM coordinator's resilience ladder (pm._resolve_card
and friends).

The requirement: on ANY blocker/bounce the coordinator actively finds a path
forward - classify the blocker, delegate the matching fix, RE-SUBMIT itself,
retry once with a DIFFERENT approach - and escalates to the owner only when
truly stuck, always with a concrete unblock proposal attached. Stalling
silently (the old behavior for worktree-less bounces) is the bug class under
test.

Self-sandboxing: pm's loopstate/activity files go to a temp dir, sessions'
board functions are monkeypatched onto an in-memory store, _say/push are
captured - no daemon, no git, no network, no LLM."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()

from cells.copilot.planning import pm
from cells.copilot.planning import pm_comm
from cells.copilot.planning import pm_state
from cells.copilot.planning import pm_resolve
from cells.engineer.cards import sessions
from spine.comms import notify

# pm.py, pm_comm.py and pm_state.py each independently compute their own
# PLANS/LOOPSTATE/_ACTIVITY (extracted from pm.py, no shared reference) - the
# functions _resolve_card/_notify_deliveries actually call live in pm_resolve
# and pm_comm, so those are the modules that need redirecting, not pm.py.
PLANS = os.path.join(SANDBOX, "pm")
pm.PLANS = PLANS
pm_comm.PLANS = PLANS
pm_comm._ACTIVITY = os.path.join(PLANS, "activity.jsonl")
pm_state.PLANS = PLANS
pm_state.LOOPSTATE = os.path.join(PLANS, "loop.json")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- in-memory board + captured channels --------------------------------------
store = {}          # tid -> track dict (THE board)
said = []           # pm._say messages
pushed = []         # notify.push_fcm calls
calls = []          # delegation calls: (verb, detail)

pm_resolve._say = lambda text: said.append(text)   # used by _resolve_card's own bare `_say`
pm._say = lambda text: said.append(text)           # used by _notify_deliveries's own bare `_say`
notify.push_fcm = lambda title, body, tid=None: pushed.append((title, body))
sessions._load = lambda: list(store.values())
sessions.list_tracks = lambda: list(store.values())

WT = os.path.join(SANDBOX, "wt")
os.makedirs(WT, exist_ok=True)


def card(tid, **kw):
    t = {"id": tid, "task": "Task " + tid, "branch": "b-" + tid, "status": "bounced",
         "lane": "review", "repo": SANDBOX, "worktree": WT, "mode": "auto"}
    t.update(kw)
    store[tid] = t
    return t


PM = {"repos": [], "autonomy": "act"}


def fresh_day():
    return {"dispatched": [], "paused_at": 0}


# -- 1. classification: the right tool for each blocker ------------------------
def test_bounce_kind():
    check(pm._bounce_kind(card("k1", worktree="")) == "dispatch",
          "no worktree -> dispatch retry (was silently skipped before)")
    check(pm._bounce_kind(card("k2", merge_kind="conflict",
                               merge_report="Your local changes to the following files "
                                            "would be overwritten by merge")) == "dirty",
          "dirty shared checkout recognized behind a 'conflict' label")
    check(pm._bounce_kind(card("k3", merge_kind="conflict",
                               merge_report="Konfliktmarkierungen <<<<<<< offen")) == "conflict",
          "real marker conflict -> worker delegation")
    check(pm._bounce_kind(card("k4", gate_report=["tests red"])) == "gate",
          "gate bounce -> steer the worker")


# -- 2. every escalation carries a CONCRETE proposal ---------------------------
def test_proposals():
    p = pm._unblock_proposal(card("p1", worktree="", last_reply="DISPATCH FAILED: no repo"))
    check("In Arbeit" in p and "DISPATCH FAILED" in p, "dispatch proposal names error + move")
    p = pm._unblock_proposal(card("p2", merge_kind="conflict",
                                  merge_report="would be overwritten by merge"))
    check("resolve_blocker b-p2" in p, "dirty proposal names the resolve_blocker command")
    p = pm._unblock_proposal(card("p3", merge_kind="conflict", merge_report="<<<<<<< daemon/x.py"))
    check("resolve_conflict b-p3" in p, "conflict proposal names the resolve_conflict command")
    p = pm._unblock_proposal(card("p4", gate_report=["gate command failed (tsc):\nTS2345 boom"]))
    check("gate command failed" in p, "gate proposal carries the concrete reason")


# -- 3. the ladder: delegate -> re-submit -> DIFFERENT approach -> escalate ----
def test_gate_ladder():
    store.clear()
    said.clear(); pushed.clear(); calls.clear()
    t = card("g1", gate_report=["tests red"])
    steers = []
    gate_outcomes = ["bounced", "submitted"]      # red on 1st re-submit, green on 2nd

    def fake_steer(tid, instr, **kw):
        steers.append(instr)
        store[tid]["status"] = "needs_you"
        return store[tid]

    def fake_move(tid, lane, actor="owner", **kw):
        calls.append(("move", lane))
        if lane == "review":
            store[tid]["status"] = gate_outcomes.pop(0)
        return store[tid]

    sessions.steer = fake_steer
    sessions.move_lane = fake_move

    day = fresh_day()
    todo = pm._bounced_to_resolve(sessions.list_tracks(), PM, day)
    check([x["id"] for x in todo] == ["g1"], "bounced card is a resolve candidate")

    a1 = pm._bump_attempt("g1")
    pm._resolve_card("g1", a1)
    check("beim Review gebounct" in steers[0] and "tests red" in steers[0],
          "attempt 1 steers the worker with the concrete reason")
    check(("move", "review") in calls, "coordinator RE-SUBMITS itself after the fix")
    check(store["g1"]["status"] == "bounced", "gate stayed red -> still bounced")
    day = pm._loopstate().get(pm._today(), {})
    check("g1" not in day.get("resolved", []), "NOT escalated after one failed attempt")
    check(pm._bounced_to_resolve(sessions.list_tracks(), PM, day),
          "a retry (different approach) is still planned")

    a2 = pm._bump_attempt("g1")
    pm._resolve_card("g1", a2)
    check("ANDEREN Ansatz" in steers[1], "attempt 2 explicitly demands a different approach")
    check(store["g1"]["status"] == "submitted", "second attempt unblocked the card")
    check(any("wieder frei" in s for s in said), "owner told the card is unstuck")


def test_gate_exhausted_escalates_with_proposal():
    store.clear()
    said.clear(); pushed.clear()
    t = card("g2", gate_report=["gate command failed (tsc): TS2345"])

    sessions.steer = lambda tid, instr, **kw: store[tid].__setitem__("status", "needs_you")
    def fake_move(tid, lane, actor="owner", **kw):
        store[tid]["status"] = "bounced"           # gate stays red forever
        return store[tid]
    sessions.move_lane = fake_move

    for _ in range(pm._RESOLVE_MAX):
        pm._resolve_card("g2", pm._bump_attempt("g2"))
    st = pm._loopstate(); day = st.get(pm._today(), {})
    check("g2" in day.get("resolved", []), "attempts exhausted -> escalation-ready")
    check(not pm._bounced_to_resolve(sessions.list_tracks(), PM, day),
          "given-up card no longer retried")

    notify.fcm_ready = lambda: True
    pm._notify_deliveries(day, sessions.list_tracks(), st, PM)
    check(any("Vorschlag" in s for s in said),
          "escalation reaches the chat WITH a concrete proposal")
    check(any("Vorschlag" in b for _ti, b in pushed),
          "push notification carries the proposal too")
    said.clear(); pushed.clear()
    pm._notify_deliveries(day, sessions.list_tracks(), st, PM)
    check(not said and not pushed, "escalation pings ONCE, not every tick")


# -- 4. conflict path auto-switches tools (resolve_conflict -> resolve_blocker) -
def test_conflict_switches_to_blocker():
    store.clear(); said.clear()
    card("c1", merge_kind="conflict", merge_report="Konflikt <<<<<<< daemon/x.py")

    def fake_dcr(tid, actor="x", background=True):
        calls.append(("dcr", background))
        return ("b-c1: no conflict markers in the worktree - if it still won't merge "
                "it is likely a dirty shared checkout (use resolve_blocker).")

    def fake_park(tid, actor="x"):
        calls.append(("park", tid))
        store[tid]["status"] = "submitted"
        return "parked + review check now passes"

    sessions.dispatch_conflict_resolution = fake_dcr
    sessions.park_and_retry_merge = fake_park
    sessions.move_lane = lambda tid, lane, **kw: store[tid]

    calls.clear()
    pm._resolve_card("c1", pm._bump_attempt("c1"))
    check(("dcr", False) in calls, "conflict fix delegated SYNCHRONOUSLY (chained)")
    check(("park", "c1") in calls,
          "'use resolve_blocker' answer auto-triggers park_and_retry_merge")
    check(store["c1"]["status"] == "submitted", "card unblocked by the switched tool")


# -- 5. a failed dispatch is retried, not abandoned ----------------------------
def test_dispatch_retry():
    store.clear(); said.clear()
    card("d1", worktree="", lane="backlog", last_reply="DISPATCH FAILED: boom")

    def fake_move(tid, lane, actor="owner", **kw):
        calls.append(("move", lane))
        if lane == "working":
            store[tid].update(status="needs_you", lane="working", worktree=WT)
        return store[tid]
    sessions.move_lane = fake_move

    calls.clear()
    pm._resolve_card("d1", pm._bump_attempt("d1"))
    check(("move", "working") in calls, "no-worktree bounce -> re-dispatch attempted")
    check(store["d1"]["status"] == "needs_you", "card is moving again")


# -- 6. a delegation crash is contained, counted, and escalates in the end -----
def test_delegation_crash_contained():
    store.clear(); said.clear(); pushed.clear()
    card("x1", gate_report=["boom"])
    def raising_steer(tid, instr, **kw):
        raise RuntimeError("driver exploded")
    sessions.steer = raising_steer
    for _ in range(pm._RESOLVE_MAX):
        pm._resolve_card("x1", pm._bump_attempt("x1"))   # must not raise
    day = pm._loopstate().get(pm._today(), {})
    check("x1" in day.get("resolved", []),
          "crashing delegation still walks the ladder to escalation")
    check("x1" not in pm._resolving, "in-flight marker cleaned up after a crash")


# -- 7. escalation works even without FCM (chat is the floor, push the extra) --
def test_escalation_without_fcm():
    store.clear(); said.clear(); pushed.clear()
    card("f1", gate_report=["boom"])
    st = pm._loopstate()
    day = st.setdefault(pm._today(), fresh_day())
    day.setdefault("resolved", []).append("f1")
    day["notified"] = []
    notify.fcm_ready = lambda: False
    pm._notify_deliveries(day, sessions.list_tracks(), st, PM)
    check(any("Vorschlag" in s for s in said) and not pushed,
          "no FCM -> chat escalation still goes out (with proposal)")


if __name__ == "__main__":
    test_bounce_kind()
    test_proposals()
    test_gate_ladder()
    test_gate_exhausted_escalates_with_proposal()
    test_conflict_switches_to_blocker()
    test_dispatch_retry()
    test_delegation_crash_contained()
    test_escalation_without_fcm()
    if _fails:
        print("\nFAILED (%d): %s" % (len(_fails), "; ".join(_fails)))
        sys.exit(1)
    print("\nall pm-resilience checks passed")
