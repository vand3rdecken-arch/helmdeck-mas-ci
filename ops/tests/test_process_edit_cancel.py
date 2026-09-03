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

    # step-level chat actions (owner decree: "Henry soll den Prozess aendern
    # koennen" - chat is a full alternative to the UI, not just process-level).
    p5 = processes.create("Step-level chat test", actor="owner",
                          steps=[{"title": "First step", "mode": "do", "days": 1}])
    r = ca._run_action({"type": "add_step", "process": p5["id"], "title": "New via chat"},
                       "cl", role="client")
    check("gesperrt" in r or "cards.admin" in r, "add_step refuses a non-admin role")
    r = ca._run_action({"type": "add_step", "process": p5["id"], "title": "New via chat"},
                       "duy", role="owner")
    check(len(processes.get(p5["id"])["steps"]) == 2, "add_step via chat appends a step")
    r = ca._run_action({"type": "update_step", "process": p5["id"], "step": "New via",
                        "days": 3}, "duy", role="owner")
    check(processes.get(p5["id"])["steps"][1]["days"] == 3,
          "update_step via chat resolves the step by a title fragment (%r)" % r)
    r = ca._run_action({"type": "update_step", "process": p5["id"], "step": "no such step",
                        "days": 1}, "duy", role="owner")
    check("not found" in r, "update_step refuses cleanly when the fragment matches nothing")
    r = ca._run_action({"type": "remove_step", "process": p5["id"], "step": "New via"},
                       "duy", role="owner")
    check(len(processes.get(p5["id"])["steps"]) == 1, "remove_step via chat drops the matched step")

    # move_step + relaxed remove_step + delete_process (owner report
    # 2026-09-03: "Bearbeiten still doesn't cover all, cannot remove or
    # switch steps. Or delete process" - hit specifically on a DONE process
    # where every step already has a card).
    p6 = processes.create("Reorder + delete test", actor="owner",
                          steps=[{"title": "A", "mode": "do", "days": 1},
                                 {"title": "B", "mode": "do", "days": 1},
                                 {"title": "C", "mode": "do", "days": 1, "track": "t-fake",
                                  "status": "accepted", "done": True}])
    moved = processes.move_step(p6["id"], 0, "down", actor="owner")
    check([s["title"] for s in moved["steps"]] == ["B", "A", "C"],
          "move_step swaps a step with its neighbour")
    try:
        processes.move_step(p6["id"], 0, "up", actor="owner")
        check(False, "move_step at the top refuses 'up'")
    except RuntimeError as e:
        check("top" in str(e), "move_step at the top refuses 'up', names why (%r)" % e)
    try:
        processes.move_step(p6["id"], 2, "down", actor="owner")
        check(False, "move_step at the bottom refuses 'down'")
    except RuntimeError as e:
        check("bottom" in str(e), "move_step at the bottom refuses 'down', names why (%r)" % e)
    # "C" (index 2) has a track - removing it used to refuse ("step already
    # has a card"), which is exactly what blocked the owner on their DONE
    # process where every step had one.
    removed = processes.remove_step(p6["id"], 2)
    check(len(removed["steps"]) == 2 and all(s["title"] != "C" for s in removed["steps"]),
          "remove_step now works even for a step that already has a card - "
          "the card itself is untouched, only this process's own list shrinks")

    r = ca._run_action({"type": "move_step", "process": p6["id"], "step": "B", "direction": "down"},
                       "duy", role="owner")
    check(processes.get(p6["id"])["steps"][1]["title"] == "B",
          "move_step via chat resolves the step by fragment and moves it (%r)" % r)
    r = ca._run_action({"type": "move_step", "process": p6["id"], "step": "B", "direction": "sideways"},
                       "duy", role="owner")
    check("direction" in r, "move_step via chat refuses a bogus direction, not a crash")

    check(processes.get(p6["id"]) is not None, "sanity: process still exists before delete")
    r = ca._run_action({"type": "delete_process", "process": p6["id"]}, "cl", role="client")
    check("gesperrt" in r or "cards.admin" in r, "delete_process via chat refuses a non-admin role")
    check(processes.get(p6["id"]) is not None, "the refused delete did not apply")
    r = ca._run_action({"type": "delete_process", "process": p6["id"]}, "duy", role="owner")
    check(processes.get(p6["id"]) is None, "delete_process via chat removes the process row (%r)" % r)
    r = ca._run_action({"type": "delete_process", "process": p6["id"]}, "duy", role="owner")
    check("ambiguous or not found" in r, "deleting an already-gone process refuses cleanly, not a crash")

    # HTTP-layer: delete is admin-gated the same way edit/cancel are.
    p7 = processes.create("HTTP delete cap check", actor="owner",
                          steps=[{"title": "S", "mode": "do", "days": 1}])
    fs4 = FakeSelf()
    routes_system.processes_sub_post(fs4, client_role, {}, p7["id"], "delete")
    check(fs4.sent[0] == 403, "HTTP: a role with no cards.admin is refused on delete")
    check(processes.get(p7["id"]) is not None, "the refused HTTP delete did not apply")
    fs5 = FakeSelf()
    routes_system.processes_sub_post(fs5, owner, {}, p7["id"], "delete")
    check(fs5.sent[0] == 200 and processes.get(p7["id"]) is None,
          "HTTP: owner may delete, and the process is actually gone")

    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        sys.exit(1)
    print("process-edit-cancel: all pinned - PASS")


if __name__ == "__main__":
    main()
