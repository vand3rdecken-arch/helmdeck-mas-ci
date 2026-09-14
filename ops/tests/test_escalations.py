# -*- coding: utf-8 -*-
"""Pins the escalation channel + Henry broker (owner decree 2026-08-21, dual
architecture, cell-corrected same day): spine/registry/escalations.py is the
BUS (any cell emits, append-only, state folded); cells/copilot/henry_broker
is the JUDGEMENT (Henry decides via headless seam, bounded verbs, 2-attempt
cap). Engineer never decides; copilot never stores flags.

Self-sandboxing: escalation log redirected to a temp file, Henry's model
call, notify and settings stubbed - nothing touches the live board, a real
model or the phone.

Run: py -3.12 ops/tests/test_escalations.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import db, events
from spine.registry import escalations as esc
from cells.copilot.broker import henry_broker as hb


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-esc-")
    saved = (db.DBPATH, hb._ask, hb._hands_on_ask, hb._notify_owner, events.settings,
             events.emit, hb._HENRY_REPO_ROOT)
    try:
        # escalations live in the db since state-into-db phase C - sandbox
        # the store itself, not a file path
        db.DBPATH = os.path.join(tmp, "test.db")
        db._local.c = None
        db.init()
        events.settings = lambda: {}
        events.emit = lambda *a, **k: None
        # Defense in depth (found live 2026-08-27: stubbing only hb._ask was
        # not enough - card-less escalations are privileged, so _decide
        # calls _hands_on_ask, which calls the REAL _baseline_commit() unless
        # _HENRY_REPO_ROOT also points somewhere throwaway. This is the SAME
        # real-repo-commit risk test_henry_privilege_gate.py already guards
        # against; a future scenario in this file that forgets to stub
        # _hands_on_ask must still be safe, not just correctly-remembered.
        hb._HENRY_REPO_ROOT = tmp
        notified = []
        hb._notify_owner = lambda text, t: notified.append(text)

        # -- emit + fold: append-only, state derived --------------------------
        eid = esc.emit("aborted-by-restart", card=None, detail="apk build")
        opens = esc.list_open()
        assert len(opens) == 1 and opens[0]["id"] == eid and opens[0]["attempts"] == 0
        print("PASS bus: emit -> open, folded from the log")

        # -- Henry decides notify_owner: executes, closes ---------------------
        # Card-less escalations are PRIVILEGED (_dispatcher_privileged(None)
        # is True - no client to be restricted from), so _decide calls
        # _hands_on_ask, not _ask - both must be stubbed or this silently
        # falls through to the real headless-claude seam (found live
        # 2026-08-27: this test asserted True but got False for exactly this
        # reason, unrelated to the rerun_deploy work below - a real gap this
        # fixes alongside it).
        decision = {"action": "notify_owner", "card": "",
                    "text": "build neu anstossen?", "why": "restart"}
        hb._ask = lambda prompt, model="", perm=None: decision
        hb._hands_on_ask = lambda prompt, timeout=60: decision
        assert hb._decide(opens[0]) is True
        assert not esc.list_open(), "decided escalation must fold closed"
        assert notified and "neu anstossen" in notified[0]
        print("PASS broker: decide(notify_owner) -> executed + closed")

        # -- malformed decision stays open, attempts counted ------------------
        eid2 = esc.emit("conflict-unresolved", card=None, detail="x")
        hb._ask = lambda prompt, model="", perm=None: {"action": "levitate"}
        hb._hands_on_ask = lambda prompt, timeout=60: {"action": "levitate"}
        e2 = [e for e in esc.list_open() if e["id"] == eid2][0]
        assert hb._decide(e2) is False
        e2 = [e for e in esc.list_open() if e["id"] == eid2][0]
        assert e2["attempts"] == 1, "attempt must be folded: %r" % e2
        print("PASS broker: malformed verb -> stays open, attempt recorded")

        # -- cap: after MAX attempts the loop gives up loudly, closes ---------
        hb._decide(e2)   # attempt 2, still malformed
        e2 = [e for e in esc.list_open() if e["id"] == eid2][0]
        assert e2["attempts"] >= hb._MAX_ATTEMPTS
        notified.clear()
        hb._give_up(e2)
        assert not [e for e in esc.list_open() if e["id"] == eid2], "give-up must close"
        assert notified, "give-up must notify the owner"
        print("PASS broker: 2-attempt cap -> give up, owner notified, closed")

        # -- Henry's ask failing entirely never crashes the broker ------------
        eid3 = esc.emit("deploy-red", card=None, detail="boom")
        def _raise(*a, **k): raise RuntimeError("model down")
        hb._ask = _raise
        hb._hands_on_ask = _raise
        e3 = [e for e in esc.list_open() if e["id"] == eid3][0]
        assert hb._decide(e3) is False and [e for e in esc.list_open() if e["id"] == eid3]
        print("PASS broker: model failure -> escalation survives, no crash")

        # -- boot check: dead ship.lock pid emits ship-aborted ----------------
        lockdir = os.path.join(tmp, ".loop", "ship.lock")
        os.makedirs(lockdir)
        with open(os.path.join(lockdir, "pid"), "w") as f:
            f.write("999999999")
        real_root = hb.ROOT
        try:
            hb.ROOT = os.path.join(tmp, "daemon")   # lock path derives from ROOT's parent
            os.makedirs(hb.ROOT, exist_ok=True)
            hb.check_stale_ship_lock()
        finally:
            hb.ROOT = real_root
        kinds = [e["kind"] for e in esc.list_open()]
        assert "ship-aborted" in kinds, "dead lock pid must escalate: %r" % kinds
        print("PASS boot: dead ship.lock pid -> ship-aborted escalation")

        # -- rerun_deploy with no matching repo_hooks entry: fails LOUD, not --
        # -- quiet (found live 2026-08-27: a stale lock kept re-escalating on --
        # -- every daemon restart because this silently returned True) -------
        events.settings = lambda: {"default_repo": "C:/some/repo", "repo_hooks": {}}
        eid4 = esc.emit("ship-aborted", card=None, detail="lock dead")
        e4 = [e for e in esc.list_open() if e["id"] == eid4][0]
        ok4 = hb._execute("rerun_deploy", "", "", "", e4)
        assert ok4 is False, "no configured deploy hook -> _execute must return False, not silently succeed"
        assert any(r["id"] == eid4 and r["event"] == "note" and "repo_hooks" in (r.get("detail") or "")
                   for r in esc.records()), \
            "the missing-hook reason must be recorded as a note on the escalation"
        print("PASS broker: rerun_deploy with no matching repo_hooks entry -> False + noted, not a silent no-op success")

        # -- the ship verb (owner decree 2026-09-01: shipping is Henry's ------
        # -- judgement; emit half = lanemachine.request_ship_decision). -------
        # -- Owner decree 2026-09-09, 18:04 correction: EXECUTE spawns a -------
        # -- SHIP CARD (dispatch.new_ship_task), not a hook subprocess - -------
        # -- stubbed here so this stays a unit test (no real card, no real -----
        # -- spawned turn). ------------------------------------------------
        eid5 = esc.emit("ship-decision", card=None, detail="entscheide")
        e5 = [e for e in esc.list_open() if e["id"] == eid5][0]
        # kind none = a deliberate non-ship, closes with nothing spawned
        assert hb._execute("ship", "", "", "", e5, kind="none") is True
        # an invalid kind is a malformed verb: stays open, reason noted
        assert hb._execute("ship", "", "", "", e5, kind="banana") is False

        import cells.engineer.cards.dispatch as _dispatch
        calls = []
        def _fake_new_ship_task(repo, kind, actor="owner", origin_card=None):
            calls.append({"repo": repo, "kind": kind, "actor": actor, "origin_card": origin_card})
            return {"id": "ship-fake-1"}
        real_new_ship_task = _dispatch.new_ship_task
        _dispatch.new_ship_task = _fake_new_ship_task
        try:
            events.settings = lambda: {"default_repo": tmp}
            assert hb._execute("ship", "", "", "", e5, kind="ota") is True
            assert calls and calls[-1]["kind"] == "ota" and calls[-1]["repo"] == tmp, \
                "ship verb must spawn a Ship card carrying the decided kind"
            # no repo resolvable at all -> refuses loudly, nothing spawned
            calls.clear()
            events.settings = lambda: {}
            assert hb._execute("ship", "", "", "", e5, kind="native") is False
            assert not calls, "no repo known -> must not spawn a card"
        finally:
            _dispatch.new_ship_task = real_new_ship_task
        print("PASS broker: ship verb -> none closes, bad kind stays open, "
              "ota/native spawn a Ship card with the decided kind, no repo refuses loudly")

        # -- emit half: one open decision per card, deduped; no hook = no-op --
        # (unrelated to the ship VERB stubbed above - request_ship_decision
        # only checks a deploy hook is CONFIGURED as evidence something can
        # ship at all; it still needs one here regardless of what runs it)
        import cells.engineer.cards.lanemachine as lm
        events.settings = lambda: {"repo_hooks": {tmp: {"deploy": "bash ops/deploy/ship.sh"}}}
        t9 = {"id": "c9", "repo": tmp, "run_dir": os.path.join(tmp, "run9"), "worktree": tmp}
        os.makedirs(t9["run_dir"], exist_ok=True)
        # 2026-09-12 (owner: "ship als Karte"): a landing files a DECIDE ship
        # card (synchronously, dedup-visible) and dispatches it on a thread;
        # the escalation is only the fallback when filing the card fails.
        # 2026-09-14 (third iteration): that card is now filed board_hidden -
        # same mechanism, no board row (threads.py/routes_tracks.py skip it).
        filed, open_cards = [], []
        def fake_ship(repo, kind, actor="henry", origin_card=None, dispatch=True,
                     board_hidden=False):
            assert kind == "decide" and dispatch is False and origin_card == "c9"
            assert board_hidden is True, "the decide card must be filed board_hidden"
            c = {"id": "ship-%d" % len(filed), "ship_kind": kind, "ship_origin": origin_card,
                 "repo": repo, "lane": "backlog", "run_dir": t9["run_dir"],
                 "board_hidden": board_hidden}
            filed.append(c); open_cards.append(c); return c
        _dispatch.new_ship_task = fake_ship
        moved = []
        real_move = lm.move_lane
        lm.move_lane = lambda tid, lane, actor="owner", **k: moved.append((tid, lane))
        real_open = lm._open_ship_card_for
        lm._open_ship_card_for = lambda t: next((c for c in open_cards if c["ship_origin"] == t["id"]), None)
        try:
            r = lm.request_ship_decision(t9, "test")
            assert r == "ship-0" and len(filed) == 1, "a landing files exactly one decide ship card"
            import threading
            for th in threading.enumerate():
                if th.name.startswith("_ship-decide-"):
                    th.join(5)
            assert moved == [("ship-0", "working")], "the card is dispatched on its own thread (%r)" % moved
            assert lm.request_ship_decision(t9, "test") is None,                 "an open ship card for the card must dedup the second landing"
            assert len(filed) == 1
            # filing fails -> the old escalation is the fallback, never silence
            def boom(*a, **k): raise RuntimeError("no disk")
            _dispatch.new_ship_task = boom
            open_cards.clear()
            eid = lm.request_ship_decision(t9, "test")
            assert eid and any(e.get("kind") == "ship-decision" and e.get("card") == "c9"
                               for e in esc.list_open()), "card failure falls back to a ship-decision escalation"
            events.settings = lambda: {"repo_hooks": {}}
            t10 = dict(t9, id="c10")
            assert lm.request_ship_decision(t10, "test") is None,                 "no deploy hook configured -> nothing to decide, no card"
        finally:
            _dispatch.new_ship_task = real_new_ship_task
            lm.move_lane = real_move
            lm._open_ship_card_for = real_open
        print("PASS emit: request_ship_decision -> decide ship card, deduped per card, "
              "escalation fallback, no-op without a hook")

        print("ALL PASS")
    finally:
        (db.DBPATH, hb._ask, hb._hands_on_ask, hb._notify_owner, events.settings,
         events.emit, hb._HENRY_REPO_ROOT) = saved
        db._local.c = None


if __name__ == "__main__":
    main()
