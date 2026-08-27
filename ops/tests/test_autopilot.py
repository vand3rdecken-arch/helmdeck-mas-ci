# -*- coding: utf-8 -*-
"""Per-card autopilot (card flag autopilot=true) - the launch-card fix: an
opted-in card dispatches itself and runs the PM's resilience ladder on its own
bounces immediately, so launch cards never sit unmoved for weeks. Covers: the
flag (own field, no collision with the `mode` completion statistic), one-shot
board directives, and the _autopilot tick - including the two limits that keep
it lawful: it shares the PM's attempt budget, and it never merges without
policy.auto_accept_green.

Self-sandboxing: fake in-memory DB, patched events.emit, patched thread
spawners (record instead of running), temp directives + temp PM loopstate -
nothing touches the real board, event log, chat, or any git worktree.

Run: py -3.12 ops/tests/test_autopilot.py
"""
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from cells.engineer import sessions
from cells.engineer import cardadmin
from spine.storage import events
from spine.storage import trackstore
from cells.process import processes
from cells.pm import pm
from cells.pm import pm_state
from cells.pm import pm_resolve


class FakeDB:
    def __init__(self):
        self.tracks = {}
    def tracks_all(self):
        return [dict(t) for t in self.tracks.values()]
    def track_put(self, t):
        self.tracks[t["id"]] = dict(t)
    def track_get(self, tid):
        t = self.tracks.get(tid)
        return dict(t) if t else None


class FakeThread:
    """Records the would-be worker instead of running it."""
    spawned = []
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}
    def start(self):
        FakeThread.spawned.append(self)


class FakeThreading:
    Thread = FakeThread


def card(fake, tid, run_dir, **over):
    t = {"id": tid, "repo": "r", "branch": "b-" + tid, "worktree": "",
         "task": "task " + tid, "client": "", "session_id": None,
         "perm": "acceptEdits", "lane": "backlog", "status": "queued",
         "turns": 0, "run_dir": run_dir, "last_reply": "", "value": 50.0,
         "driver": "claude", "priority": "medium", "due": "", "rank": None,
         "model": "", "attachments": [], "ai_cost": 0.0, "tokens_in": 0,
         "tokens_out": 0, "models": [], "created": "", "updated": ""}
    t.update(over)
    fake.track_put(t)
    return t


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-test-")
    run_dir = os.path.join(tmp, "run")
    os.makedirs(run_dir)
    real_db, real_emit = trackstore._db, events.emit
    real_threading, real_gate = processes.threading, sessions._gate
    real_directives = cardadmin.DIRECTIVES
    real_settings = events.settings
    real_pm_threading, real_loopstate, real_say = (
        pm_resolve.threading, pm_state.LOOPSTATE, pm_resolve._say)
    try:
        fake = FakeDB()
        trackstore._db = fake
        emitted = []
        events.emit = lambda kind, track, **f: emitted.append(
            {"kind": kind, "track": track, **f})
        processes.threading = FakeThreading
        # the PM ladder is driven, not run: its threads are recorded, its
        # loopstate lives in the temp dir, and it never speaks into the chat
        pm_resolve.threading = FakeThreading
        pm_state.LOOPSTATE = os.path.join(tmp, "loop.json")
        pm_resolve._say = lambda *a, **k: None

        # -- the flag is its own field, editable both ways ------------------
        card(fake, "t-edit", run_dir)
        t = sessions.update_track("t-edit", {"autopilot": True})
        assert t["autopilot"] is True, "autopilot not set: %r" % t.get("autopilot")
        t = sessions.update_track("t-edit", {"autopilot": False})
        assert t["autopilot"] is False, "autopilot not switchable off"
        # and it must NOT collide with `mode` - a touch-free acceptance writes
        # mode="auto" (events._completion_mode); that must never mean autopilot
        accepted = card(fake, "t-acc", run_dir, lane="done", status="accepted",
                        mode="auto")
        assert not accepted.get("autopilot"), "completion stat leaked into autopilot"
        print("PASS autopilot flag: own field, on/off, no collision with mode")

        # -- board directives: applied once, done cards untouched ----------
        cardadmin.DIRECTIVES = os.path.join(tmp, "board_directives.json")
        card(fake, "t-dir", run_dir)
        card(fake, "t-done", run_dir, lane="done", status="accepted", mode="assisted")
        with open(cardadmin.DIRECTIVES, "w", encoding="utf-8") as f:
            json.dump([{"id": "d1", "card": "t-dir", "set": {"autopilot": True}},
                       {"id": "d2", "card": "t-done", "set": {"autopilot": True}},
                       {"id": "d3", "card": "t-gone", "set": {"autopilot": True}}], f)
        n = sessions.apply_board_directives()
        assert n == 1, "expected 1 applied, got %r" % n
        assert fake.track_get("t-dir")["autopilot"] is True
        assert "d1" in fake.track_get("t-dir")["directives_applied"]
        assert not fake.track_get("t-done").get("autopilot"), "done card touched"
        # owner overrides later; a restart must NOT re-apply
        sessions.update_track("t-dir", {"autopilot": False})
        assert sessions.apply_board_directives() == 0, "directive re-applied"
        assert fake.track_get("t-dir")["autopilot"] is False, "owner edit overwritten"
        print("PASS directives: applied once, done card skipped, owner edit kept")

        # -- autopilot: backlog card dispatches itself once ----------------
        FakeThread.spawned = []
        card(fake, "t-auto", run_dir, autopilot=True)
        processes._autopilot()
        assert [s for s in FakeThread.spawned if s.target is processes._auto_dispatch
                and s.args == ("t-auto",)], "no dispatch spawned"
        assert fake.track_get("t-auto")["autopilot_dispatched"] is True
        processes._autopilot()
        assert len(FakeThread.spawned) == 1, "re-dispatched on second tick"
        print("PASS autopilot dispatch: fires once, flag persisted")

        # -- autopilot: no dispatch without WIP headroom -------------------
        FakeThread.spawned = []
        wip_limit = events.settings()["capacity"]["wip_limit"]
        for i in range(wip_limit):
            card(fake, "t-wip%d" % i, run_dir, lane="working", status="running")
        card(fake, "t-full", run_dir, autopilot=True)
        processes._autopilot()
        assert not FakeThread.spawned, "dispatched past the WIP limit"
        for i in range(wip_limit):
            del fake.tracks["t-wip%d" % i]
        del fake.tracks["t-full"]
        print("PASS autopilot dispatch: respects WIP headroom")

        # -- autopilot bounce: runs the PM's ONE ladder, then escalates ----
        # (the ladder itself is covered by ops/tests/test_pm_resilience.py; here we
        # prove autopilot drives it, shares its attempt budget, and alerts once)
        FakeThread.spawned = []
        card(fake, "t-bounce", run_dir, autopilot=True, lane="working",
             status="bounced", worktree=os.path.join(tmp, "wt"),
             gate_report=["tsc: 3 errors"])
        processes._autopilot()
        rung = [s for s in FakeThread.spawned if s.target is pm._resolve_card]
        assert len(rung) == 1 and rung[0].args[0] == "t-bounce", \
            "bounce did not enter the PM ladder: %r" % FakeThread.spawned
        assert rung[0].args[1] == 1, "not counted as attempt 1"
        assert "t-bounce" in pm._resolving, "card not marked in-flight"
        processes._autopilot()   # fix still in flight -> no second rung
        assert len([s for s in FakeThread.spawned if s.target is pm._resolve_card]) == 1, \
            "second rung started while a fix was in flight"
        pm._resolving.discard("t-bounce")            # ladder thread finished, still bounced
        processes._autopilot()                       # rung 2 of _RESOLVE_MAX
        assert len([s for s in FakeThread.spawned if s.target is pm._resolve_card]) == 2, \
            "second attempt never ran"
        pm._resolving.discard("t-bounce")
        processes._autopilot()                       # budget spent -> escalate ONCE
        assert len([s for s in FakeThread.spawned if s.target is pm._resolve_card]) == 2, \
            "third attempt fired past _RESOLVE_MAX"
        esc = [e for e in emitted if e.get("action") == "autopilot_escalate"]
        assert len(esc) == 1 and esc[0]["card"] == "t-bounce", "no single escalation"
        processes._autopilot()
        assert len([e for e in emitted if e.get("action") == "autopilot_escalate"]) == 1, \
            "escalated twice"
        print("PASS autopilot resolve: drives the PM ladder, shares its budget, "
              "one escalation")

        # the escalation carries a concrete proposal, never a bare 'it is stuck'
        prop = pm._unblock_proposal(fake.track_get("t-bounce"))
        assert "Vorschlag" in prop and len(prop) > 30, "no unblock proposal: %r" % prop
        # ...and the PM must not push the SAME card a second time: a card the
        # autopilot escalated is already in the PM's notified set for today
        day = pm._loopstate().get(pm._today(), {})
        assert "t-bounce" in day.get("notified", []), \
            "PM would push a second time for the same stuck card"
        print("PASS autopilot escalate: proposal attached, exactly one ping")

        # -- accept stays the OWNER's: only policy.auto_accept_green opts in -
        FakeThread.spawned = []
        sessions._gate = lambda t: (True, [])
        card(fake, "t-green", run_dir, autopilot=True, lane="review", status="needs_you")
        processes._autopilot()          # policy default: auto_accept_green = False
        assert not FakeThread.spawned, "merged itself without policy.auto_accept_green"
        assert not fake.track_get("t-green").get("autopilot_accepted")
        print("PASS autopilot accept: nothing merges itself with the default policy")

        events.settings = lambda: {**real_settings(),
                                   "policy": {"auto_accept_green": True}}
        processes._autopilot()
        assert [s for s in FakeThread.spawned if s.target is processes._auto_accept
                and s.args == ("t-green",)], "green delivery not accepted under policy"
        assert fake.track_get("t-green")["autopilot_accepted"] is True
        processes._autopilot()
        assert len(FakeThread.spawned) == 1, "accepted twice"
        # red gate: nothing fires even with the policy on
        FakeThread.spawned = []
        sessions._gate = lambda t: (False, ["red"])
        card(fake, "t-red", run_dir, autopilot=True, lane="review", status="needs_you")
        processes._autopilot()
        assert not FakeThread.spawned, "accepted despite red gate"
        assert not fake.track_get("t-red").get("autopilot_accepted")
        print("PASS autopilot accept: policy+green accepts once, red gate never")

        print("ALL PASS")
    finally:
        trackstore._db = real_db
        events.emit = real_emit
        events.settings = real_settings
        processes.threading = real_threading
        sessions._gate = real_gate
        cardadmin.DIRECTIVES = real_directives
        pm_resolve.threading, pm_state.LOOPSTATE, pm_resolve._say = (
            real_pm_threading, real_loopstate, real_say)
        pm._resolving.clear()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
