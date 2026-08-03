# -*- coding: utf-8 -*-
"""Per-card autopilot (mode='auto') - the launch-card fix: a card opted into
autopilot dispatches itself, delegates its own bounce fixes (2 tries, then one
alert), and accepts itself on a green gate - so launch cards never sit for
weeks. Covers: mode editing/validation, one-shot board directives, and the
_autopilot tick.

Self-sandboxing: fake in-memory DB, patched events.emit, patched thread
spawner (records instead of running), temp directives file - nothing touches
the real board, event log, or any git worktree.

Run: py -3.12 tests/test_autopilot.py
"""
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "daemon"))
import sessions, events, processes


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
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
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
    real_db, real_emit = sessions._db, events.emit
    real_threading, real_gate = processes.threading, sessions._gate
    real_directives = sessions.DIRECTIVES
    try:
        fake = FakeDB()
        sessions._db = fake
        emitted = []
        events.emit = lambda kind, track, **f: emitted.append(
            {"kind": kind, "track": track, **f})
        processes.threading = FakeThreading

        # -- mode is editable, validated, clearable ------------------------
        card(fake, "t-edit", run_dir)
        t = sessions.update_track("t-edit", {"mode": "auto"})
        assert t["mode"] == "auto", "mode not set: %r" % t.get("mode")
        raised = False
        try:
            sessions.update_track("t-edit", {"mode": "yolo"})
        except ValueError:
            raised = True
        assert raised, "bad mode accepted"
        t = sessions.update_track("t-edit", {"mode": ""})
        assert t["mode"] is None, "mode not clearable: %r" % t.get("mode")
        print("PASS mode edit: settable, bad value rejected, clearable")

        # -- board directives: applied once, done cards untouched ----------
        sessions.DIRECTIVES = os.path.join(tmp, "board_directives.json")
        card(fake, "t-dir", run_dir)
        card(fake, "t-done", run_dir, lane="done", status="accepted", mode="assisted")
        with open(sessions.DIRECTIVES, "w", encoding="utf-8") as f:
            json.dump([{"id": "d1", "card": "t-dir", "set": {"mode": "auto"}},
                       {"id": "d2", "card": "t-done", "set": {"mode": "auto"}},
                       {"id": "d3", "card": "t-gone", "set": {"mode": "auto"}}], f)
        n = sessions.apply_board_directives()
        assert n == 1, "expected 1 applied, got %r" % n
        assert fake.track_get("t-dir")["mode"] == "auto"
        assert "d1" in fake.track_get("t-dir")["directives_applied"]
        assert fake.track_get("t-done")["mode"] == "assisted", "done card touched"
        # owner overrides later; a restart must NOT re-apply
        sessions.update_track("t-dir", {"mode": ""})
        assert sessions.apply_board_directives() == 0, "directive re-applied"
        assert fake.track_get("t-dir")["mode"] is None, "owner edit overwritten"
        print("PASS directives: applied once, done card skipped, owner edit kept")

        # -- autopilot: backlog card dispatches itself once ----------------
        FakeThread.spawned = []
        card(fake, "t-auto", run_dir, mode="auto")
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
        card(fake, "t-full", run_dir, mode="auto")
        processes._autopilot()
        assert not FakeThread.spawned, "dispatched past the WIP limit"
        for i in range(wip_limit):
            del fake.tracks["t-wip%d" % i]
        print("PASS autopilot dispatch: respects WIP headroom")

        # -- autopilot: bounce -> steer with the reason, 2 tries, 1 alert --
        FakeThread.spawned = []
        card(fake, "t-bounce", run_dir, mode="auto", lane="working",
             status="bounced", worktree=os.path.join(tmp, "wt"),
             gate_report=["tsc: 3 errors"])
        processes._autopilot()
        steers = [s for s in FakeThread.spawned if s.target is sessions.steer]
        assert len(steers) == 1, "no steer delegated"
        assert "tsc: 3 errors" in steers[0].args[1], "bounce reason not in steer"
        assert fake.track_get("t-bounce")["autopilot_resolves"] == 1
        processes._autopilot()   # within the retry window -> no double-steer
        assert len([s for s in FakeThread.spawned if s.target is sessions.steer]) == 1, \
            "steered again inside the retry window"
        t = fake.track_get("t-bounce"); t["autopilot_ts"] = 0; fake.track_put(t)
        processes._autopilot()   # try 2 of 2
        assert fake.track_get("t-bounce")["autopilot_resolves"] == 2
        t = fake.track_get("t-bounce"); t["autopilot_ts"] = 0; fake.track_put(t)
        processes._autopilot()   # exhausted -> escalate ONCE
        assert fake.track_get("t-bounce")["autopilot_resolves"] == 2, "third try fired"
        esc = [e for e in emitted if e.get("action") == "autopilot_escalate"]
        assert len(esc) == 1 and esc[0]["card"] == "t-bounce", "no single escalation"
        processes._autopilot()
        assert len([e for e in emitted if e.get("action") == "autopilot_escalate"]) == 1, \
            "escalated twice"
        print("PASS autopilot resolve: 2 delegated tries, then exactly one alert")

        # -- autopilot: conflict bounce goes to conflict resolution --------
        FakeThread.spawned = []
        card(fake, "t-conf", run_dir, mode="auto", lane="working", status="bounced",
             worktree=os.path.join(tmp, "wt"), merge_kind="conflict")
        processes._autopilot()
        assert [s for s in FakeThread.spawned
                if s.target is sessions.dispatch_conflict_resolution], \
            "conflict not delegated to conflict resolution"
        print("PASS autopilot resolve: merge conflict routed to the card's worker")

        # -- autopilot: delivered + green gate -> accepted once ------------
        FakeThread.spawned = []
        sessions._gate = lambda t: (True, [])
        card(fake, "t-green", run_dir, mode="auto", lane="review", status="needs_you")
        processes._autopilot()
        assert [s for s in FakeThread.spawned if s.target is processes._auto_accept
                and s.args == ("t-green",)], "green delivery not accepted"
        assert fake.track_get("t-green")["autopilot_accepted"] is True
        processes._autopilot()
        assert len(FakeThread.spawned) == 1, "accepted twice"
        # red gate: nothing fires, no accept flag
        FakeThread.spawned = []
        sessions._gate = lambda t: (False, ["red"])
        card(fake, "t-red", run_dir, mode="auto", lane="review", status="needs_you")
        processes._autopilot()
        assert not FakeThread.spawned, "accepted despite red gate"
        assert not fake.track_get("t-red").get("autopilot_accepted")
        print("PASS autopilot accept: green gate accepts once, red gate never")

        print("ALL PASS")
    finally:
        sessions._db = real_db
        events.emit = real_emit
        processes.threading = real_threading
        sessions._gate = real_gate
        sessions.DIRECTIVES = real_directives
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
