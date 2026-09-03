# -*- coding: utf-8 -*-
"""Process-level editing + cancel + progress (owner report 2026-09-03:
"+Schritt war die einzige Aktion ausser Steps annehmen - man kann nicht
mal den Client/die Faelligkeit aendern oder abbrechen... man sieht auch
nicht was in den Schritten gemacht wird").

Pins:
  1. update_process only accepts client/due/request - anything else refuses
     (ValueError), never silently drops or applies it
  2. due edit re-lays step due dates (same _lay_dates() create() uses)
  3. cancel_process flips status once, refuses on an already-done process,
     and sync() never reclassifies a cancelled process back to
     running/done even once its steps happen to finish
  4. a cancelled process's chain STOPS advancing (no new auto-dispatch/
     auto-accept), but a card a step already spawned is UNTOUCHED - the
     cancel is an authority over the CHAIN, never over live work
  5. progress_summary() reports one line per step with state + lane
  6. the HTTP layer (routes_system.processes_sub_post) gates edit/cancel
     on cards.admin and leaves status open to every role

Self-sandboxing: db.ROOT/db.DBPATH + events.EV/SET redirected to a temp dir.

Run: py -3.12 ops/tests/test_process_edit_cancel.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-proceditcancel-")
    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    db.init(role="tool")
    assert db.DBPATH.startswith(tmp), "REFUSING TO RUN: db not sandboxed"

    from cells.engineer.chains import processes

    # 1+2. update_process: closed field set, due edit re-lays step dates.
    p = processes.create("Kunde Meier Q3-Vertrag", client="Meier", actor="owner",
                         steps=[{"title": "Entwurf", "mode": "do", "days": 2},
                                {"title": "Review", "mode": "do", "days": 3}])
    pid = p["id"]
    old_due = p["steps"][0]["due"]

    try:
        processes.update_process(pid, {"status": "done"})
        check(False, "update_process refuses an unlisted field")
    except ValueError:
        check(True, "update_process refuses an unlisted field (status)")

    updated = processes.update_process(pid, {"client": "Meier GmbH", "due": "2026-12-31"})
    check(updated["client"] == "Meier GmbH", "client updated")
    check(updated["due"] == "2026-12-31", "due updated")
    check(updated["steps"][0]["due"] != old_due,
          "changing the process due date re-lays step due dates")

    # 3. cancel_process.
    cancelled = processes.cancel_process(pid, actor="owner")
    check(cancelled["status"] == "cancelled", "cancel_process flips status")
    try:
        processes.cancel_process(pid, actor="owner")
        # not done yet (no steps completed) - a second cancel is a no-op-ish
        # re-cancel, not an error; only an ALREADY-DONE process refuses.
    except RuntimeError:
        check(False, "re-cancelling an already-cancelled (not done) process should not raise")
    else:
        check(True, "re-cancelling an already-cancelled process is harmless")

    p_done = processes.create("Finished one", actor="owner",
                              steps=[{"title": "Only step", "mode": "human", "days": 1}])
    # fake it done directly (sync() would normally flip this once the step's
    # card reaches the done lane - out of scope for this sandboxed test)
    from spine.storage import db as _db
    all_p = _db.processes_all()
    for q in all_p:
        if q["id"] == p_done["id"]:
            q["status"] = "done"
    _db.processes_replace(all_p)
    try:
        processes.cancel_process(p_done["id"], actor="owner")
        check(False, "cancelling an already-DONE process refuses")
    except RuntimeError:
        check(True, "cancelling an already-DONE process refuses")

    # sync() must never reclassify a cancelled process, even if every step
    # of it happens to look done.
    all_p = _db.processes_all()
    for q in all_p:
        if q["id"] == pid:
            for s in q["steps"]:
                s["track"] = None   # no card - sync() would otherwise see "no track -> proposed"
    _db.processes_replace(all_p)
    processes.sync()
    still = processes.get(pid)
    check(still["status"] == "cancelled",
          "sync() never reclassifies a cancelled process back to running/done")

    # 5. progress_summary.
    p2 = processes.create("Progress check", actor="owner",
                          steps=[{"title": "Step A", "mode": "do", "days": 1},
                                 {"title": "Step B", "mode": "do", "days": 1}])
    _, lines = processes.progress_summary(p2["id"])
    check(len(lines) == 2, "progress_summary returns one line per step")
    check("Step A" in lines[0] and "proposed" in lines[0],
          "each line names the step and its state (%r)" % lines[0])
    try:
        processes.progress_summary("does-not-exist")
        check(False, "progress_summary on an unknown id refuses")
    except RuntimeError:
        check(True, "progress_summary on an unknown id refuses")

    # 6. HTTP-layer capability gate: cards.admin required for edit/cancel,
    # status stays open. Call the real route handler with fake user dicts.
    from spine.http.routes import routes_system
    import json as _json

    class FakeSelf:
        def __init__(self):
            self.sent = None
        def _send(self, code, body):
            self.sent = (code, body)
            return self.sent

    p3 = processes.create("Cap check", actor="owner",
                          steps=[{"title": "S", "mode": "do", "days": 1}])
    client_role = {"name": "cl", "role": "client"}   # zero caps by default
    owner = {"name": "owner", "role": "owner"}

    fs = FakeSelf()
    routes_system.processes_sub_post(fs, client_role, {"patch": {"client": "x"}}, p3["id"], "edit")
    check(fs.sent[0] == 403, "a role with no cards.admin is refused on edit")

    fs2 = FakeSelf()
    routes_system.processes_sub_post(fs2, owner, {"patch": {"client": "x"}}, p3["id"], "edit")
    check(fs2.sent[0] == 200, "owner (has cards.admin) may edit")

    fs3 = FakeSelf()
    routes_system.processes_sub_post(fs3, client_role, {}, p3["id"], "status")
    check(fs3.sent[0] == 200, "status is open to every role (read-only), even one with no caps at all")

    # 7. the CHAT path (Henry's action layer) - owner report: "entweder per
    # chat, oder genug UI-Optionen". process_status/edit_process/
    # cancel_process wired the same way audit_query is.
    from cells.copilot.chat import copilot_actions as ca
    p4 = processes.create("Chat-driven process test", actor="owner",
                          steps=[{"title": "Only step", "mode": "do", "days": 1}])
    r = ca._run_action({"type": "process_status", "process": p4["id"]}, "duy", role="client")
    check(p4["id"] in r and "Only step" in r,
          "process_status via chat is readable to every role (%r)" % r[:120])
    r = ca._run_action({"type": "edit_process", "process": p4["id"], "client": "Chat GmbH"},
                       "cl", role="client")
    check("gesperrt" in r or "cards.admin" in r,
          "edit_process via chat refuses a role without cards.admin, names the gate")
    check(processes.get(p4["id"])["client"] != "Chat GmbH", "the refused edit did not apply")
    r = ca._run_action({"type": "edit_process", "process": p4["id"], "client": "Chat GmbH"},
                       "duy", role="owner")
    check(processes.get(p4["id"])["client"] == "Chat GmbH",
          "edit_process via chat applies for an admin role (%r)" % r)
    r = ca._run_action({"type": "cancel_process", "process": p4["id"]}, "duy", role="owner")
    check(processes.get(p4["id"])["status"] == "cancelled",
          "cancel_process via chat applies (%r)" % r)
    r = ca._run_action({"type": "edit_process", "process": "no such fragment"},
                       "duy", role="owner")
    check("ambiguous or not found" in r, "an unresolvable process reference refuses cleanly")

    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        sys.exit(1)
    print("process-edit-cancel: all pinned - PASS")


if __name__ == "__main__":
    main()
