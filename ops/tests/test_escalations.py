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
from spine.registry import escalations as esc
from cells.copilot.broker import henry_broker as hb
from spine.storage import events


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-esc-")
    saved = (esc.ESC_PATH, hb._ask, hb._hands_on_ask, hb._notify_owner, events.settings,
             events.emit, hb._HENRY_REPO_ROOT)
    try:
        esc.ESC_PATH = os.path.join(tmp, "escalations.jsonl")
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
        with open(esc.ESC_PATH, encoding="utf-8") as f:
            raw_lines = f.readlines()
        assert any(eid4 in ln and "repo_hooks" in ln and '"event": "note"' in ln for ln in raw_lines), \
            "the missing-hook reason must be recorded as a note on the escalation"
        print("PASS broker: rerun_deploy with no matching repo_hooks entry -> False + noted, not a silent no-op success")

        # -- the ship verb (owner decree 2026-09-01: shipping is Henry's ------
        # -- judgement; emit half = lanemachine.request_ship_decision, --------
        # -- execute half = this verb; pays debt ship-decision-not-wired) -----
        eid5 = esc.emit("ship-decision", card=None, detail="entscheide")
        e5 = [e for e in esc.list_open() if e["id"] == eid5][0]
        # kind none = a deliberate non-ship, closes with no hook involved
        assert hb._execute("ship", "", "", "", e5, kind="none") is True
        # an invalid kind is a malformed verb: stays open, reason noted
        assert hb._execute("ship", "", "", "", e5, kind="banana") is False
        # ota with no configured hook fails LOUD (same law as rerun_deploy)
        assert hb._execute("ship", "", "", "", e5, kind="ota") is False
        print("PASS broker: ship verb -> none closes, bad kind + missing hook stay open loud")

        # -- SHIP_KIND must actually REACH the hook subprocess (the whole -----
        # -- point: ship.sh runs the DECISION, not the legacy hash fallback) --
        import cells.engineer.cards.lanemachine as lm
        marker = os.path.join(tmp, "shipkind.txt")
        events.settings = lambda: {"default_repo": tmp, "repo_hooks": {
            tmp: {"deploy": 'sh -c "echo $SHIP_KIND > \\"%s\\""' % marker.replace("\\", "/")}}}
        eid6 = esc.emit("ship-decision", card=None, detail="entscheide")
        e6 = [e for e in esc.list_open() if e["id"] == eid6][0]
        assert hb._execute("ship", "", "", "", e6, kind="ota") is True
        with open(marker, encoding="utf-8") as f:
            assert f.read().strip() == "ota", "SHIP_KIND must reach the hook's env"
        print("PASS broker: ship ota -> hook ran with SHIP_KIND=ota in its env")

        # -- emit half: one open decision per card, deduped; no hook = no-op --
        t9 = {"id": "c9", "repo": tmp, "run_dir": os.path.join(tmp, "run9"), "worktree": tmp}
        os.makedirs(t9["run_dir"], exist_ok=True)
        assert lm.request_ship_decision(t9, "test") is not None
        assert lm.request_ship_decision(t9, "test") is None, \
            "an open ship-decision for the card must dedup the second emit"
        events.settings = lambda: {"repo_hooks": {}}
        t10 = dict(t9, id="c10")
        assert lm.request_ship_decision(t10, "test") is None, \
            "no deploy hook configured -> nothing to decide, no escalation"
        print("PASS emit: request_ship_decision -> deduped per card, no-op without a hook")

        print("ALL PASS")
    finally:
        (esc.ESC_PATH, hb._ask, hb._hands_on_ask, hb._notify_owner, events.settings,
         events.emit, hb._HENRY_REPO_ROOT) = saved


if __name__ == "__main__":
    main()
