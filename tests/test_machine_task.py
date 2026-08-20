# -*- coding: utf-8 -*-
"""Headless test for MACHINE tasks + the chat's never-dead-end rule.

The complaint this answers: the board chat blocked the owner from using
HelmDeck to run his own Windows PC - it had no action that reached the machine,
its charter paragraph made it refuse, and every failure path ("unknown action
type", "no card matches", "denied") was a full stop with no way forward.

Checked here: a machine card runs in a REAL folder (no git worktree, no
branch), skips the gate/merge path it has no branch for, is owner-gated and
audited - and every chat refusal now carries the route that IS open.

Self-sandboxing: temp sqlite DB, temp events/settings, temp folders, the driver
turn faked - no daemon, no git, no network, no LLM, nothing touched on the
real machine."""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="helmdeck-machine-")

from daemon.spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from daemon.spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from daemon.cells.engineer import sessions
from daemon.cells.engineer import dispatch
from daemon.cells.copilot import copilot
from daemon.spine.agent import drivers
from daemon.spine.comms import notify

WORKPLACE = os.path.join(SANDBOX, "Desktop")     # stands in for a real PC folder
os.makedirs(WORKPLACE, exist_ok=True)

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# the driver turn, faked: record where it would have run + with which brief
turns = []
dispatch._turn = lambda t, prompt, model=None, perm=None: (
    turns.append({"cwd": t.get("worktree"), "perm": t.get("perm"),
                  "machine": t.get("machine"), "prompt": prompt})
    or ("sess-1", "DELIVERED: habe es auf dem Rechner erledigt.", {"usage": {}, "models": []}))
notify.card_event = lambda t, kind: None
notify.push_fcm = lambda *a, **k: None


def _events(kind):
    with open(events.EV, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip() and json.loads(l).get("kind") == kind]


# -- 1. a machine card runs in a real folder, not a git worktree --------------
def test_machine_card_runs_in_place():
    t = sessions.new_machine_task(WORKPLACE, "Sortiere den Desktop", actor="owner")
    check(t.get("machine") is True, "card is marked as a machine task")
    check(os.path.normcase(t["worktree"]) == os.path.normcase(WORKPLACE),
          "workplace is the real folder (got %r)" % t.get("worktree"))
    check(t["branch"] == sessions.MACHINE_BRANCH, "no code branch (%s)" % t["branch"])
    check(not os.path.exists(os.path.join(WORKPLACE, ".git")),
          "NO git worktree was created in the owner's folder")
    check(turns and os.path.normcase(turns[-1]["cwd"]) == os.path.normcase(WORKPLACE),
          "the agent turn ran in that folder")
    check(turns[-1]["perm"] == "bypassPermissions",
          "headless machine work gets a perm mode that can actually run commands "
          "(got %r)" % turns[-1]["perm"])
    check(t["status"] == "needs_you" and t["lane"] == "working", "card is live on the board")
    check(any(e.get("action") == "filed" for e in _events("machine")), "dispatch is audited")
    return t


# -- 2. review/done skip the gate+merge a machine card has no branch for ------
def test_machine_accept_path(t):
    r = sessions.move_lane(t["id"], "review", actor="owner")
    check(r["status"] == "submitted", "review rests the card for the owner (%s)" % r["status"])
    check(r.get("merge_kind") == "machine", "marked as a machine review, not a merge verdict")
    check(not r.get("gate_failed") and not r.get("merge_failed"),
          "no git gate/merge bounce on a card that has no branch")
    d = sessions.move_lane(t["id"], "done", actor="owner")
    check(d["status"] == "accepted" and d["lane"] == "done", "owner's accept closes it")
    check(any(e["track"] == t["id"] for e in _events("done")), "acceptance economics recorded")
    check(not any(e["track"] == t["id"] for e in _events("merge")),
          "nothing was ever merged to main (gate-before-review untouched)")


# -- 3. the dispatched agent gets a brief that doesn't make IT refuse ---------
def test_machine_brief():
    # the briefs are data now (harness/agents/*.md via daemon/harness.py), so ask
    # for them the way drivers.py does - by the surface a track resolves to.
    from daemon.spine.registry import harness
    b = harness.brief(drivers._agent_for({"machine": True}))
    check("run commands" in b and "owner's own" in b, "machine brief grants the machine")
    check("NEVER end with just 'I cannot do X'" in b, "machine brief forbids dead-ending")
    check("settings.json" in b and "users.json" in b, "machine brief still fences the secrets")
    check("worktree" in harness.brief(drivers._agent_for({})),
          "repo cards keep the worktree brief")
    check(drivers._agent_for({"machine": True}) != drivers._agent_for({}),
          "a machine card and a repo card resolve to different briefs")


# -- 4. owner-gated + policy can RESTRICT (never the other way round) ---------
def test_policy_gates():
    out = copilot._run_action({"type": "machine_task", "task": "mach was"}, "bob", role="client")
    check("policy.machine.roles" in out, "non-owner is refused - with the exact key (%s)" % out[:60])
    check(len(turns) == 1, "and nothing ran")

    events.save_settings({"policy": {"machine": {"roots": [WORKPLACE]}}})
    ok, why = sessions.machine_root_ok(os.path.join(WORKPLACE, "sub"))
    check(ok, "a folder inside an allowed root passes")
    ok, why = sessions.machine_root_ok(SANDBOX)
    check(not ok and "policy.machine.roots" in why,
          "a folder outside the allowed roots is refused, naming the key")
    events.save_settings({"policy": {"machine": {"enabled": False}}})
    out = copilot._run_action({"type": "machine_task", "task": "x"}, "owner", role="owner")
    check("policy.machine.enabled" in out, "switched-off capability names its own switch")
    events.save_settings({"policy": {"machine": {"enabled": True, "roots": []}}})


# -- 5. THE regression: no chat refusal may be a full stop -------------------
def test_chat_never_dead_ends():
    # an action type the board has no verb for must be ROUTED, not dropped
    before = len(turns)
    out = copilot._run_action({"type": "open_app", "task": "oeffne Chrome"}, "owner", role="owner")
    check(len(turns) == before + 1, "unknown action was routed to the machine, not dropped")
    check("Maschinen-Aufgabe" in out, "and the owner is told which route was taken")

    # an action with nothing to act on: still answers with what IS possible
    out = copilot._run_action({"type": "wat"}, "owner", role="owner")
    check("machine_task" in out and "Sag mir" in out, "empty unknown action offers the menu")

    # a card reference that misses must come back with candidates
    out = copilot._run_action({"type": "move", "card": "voellig-unbekannt", "lane": "done"},
                              "owner", role="owner")
    check("keine Karte passt" in out and sessions.MACHINE_BRANCH in out,
          "a missed card reference lists the open cards (%s)" % out[:80])

    # a fixed harness key: refused, but with the route (a card), not a wall
    out = copilot._run_action({"type": "configure", "patch": {"auth": {"x": 1}}},
                              "owner", role="owner")
    check("Karte" in out and "Harness" in out,
          "a harness key points at the code-change route (%s)" % out[:80])

    # role refusals name the key that opens them (on a card that DOES resolve -
    # a reference that misses is answered by _card_hint first, which is right:
    # you cannot refuse what you could not identify). The reference has to pick
    # exactly ONE card: "machine" matches the BRANCH that every machine card
    # shares, so it is ambiguous the moment two of them exist - the normal case.
    out = copilot._run_action({"type": "move", "card": "chrome", "lane": "done"},
                              "bob", role="client")
    check("policy.chat_admin_roles" in out, "role refusal names the policy key (%s)" % out[:70])
    check("steer" in out, "and points at what the role CAN still do")

    # branch surgery must never be aimed at a folder on the owner's PC
    t2 = sessions.new_machine_task(WORKPLACE, "noch was", actor="owner")
    out = sessions.park_and_retry_merge(t2["id"], actor="owner")
    check("Maschinen-Aufgabe" in out and "parken" in out,
          "resolve_blocker refuses a machine card instead of running git in the folder")
    out = sessions.dispatch_conflict_resolution(t2["id"], actor="owner")
    check("Maschinen-Aufgabe" in out, "resolve_conflict likewise refuses a machine card")

    # and the system prompt no longer tells the model to refuse machine work
    check("NEVER DEAD-END" in copilot.SYSTEM, "chat is briefed as the coordinator")
    check("machine_task" in copilot.SYSTEM, "chat knows the machine route")
    check("is NOT a connector build" in copilot.SYSTEM,
          "the charter is scoped to BUILT CODE, so PC work is no longer refused")


# -- 6. two cards filed in the SAME SECOND must stay TWO cards ---------------
# Found live 2026-08-04: the card id is <timestamp>-<branch slug> and is also
# the primary key + run_dir name, so two cards filed in one second collided and
# track_put (INSERT OR REPLACE) silently destroyed the first - audit, economics
# and flight recorder with it. Machine cards hit this every time because they
# all share the branch '(machine)'.
def test_same_second_cards_survive():
    a = sessions.new_machine_task(WORKPLACE, "eins", actor="owner", dispatch=False)
    b = sessions.new_machine_task(WORKPLACE, "zwei", actor="owner", dispatch=False)
    check(a["id"] != b["id"], "same-second cards get distinct ids (%s / %s)"
          % (a["id"], b["id"]))
    ids = [t["id"] for t in sessions.list_tracks()]
    check(ids.count(a["id"]) == 1 and ids.count(b["id"]) == 1,
          "both cards are still on the board (neither overwrote the other)")
    check(a["run_dir"] != b["run_dir"], "and they don't share a flight recorder")


if __name__ == "__main__":
    t = test_machine_card_runs_in_place()
    test_machine_accept_path(t)
    test_machine_brief()
    test_policy_gates()
    test_chat_never_dead_ends()
    test_same_second_cards_survive()
    if _fails:
        print("\nFAILED (%d): %s" % (len(_fails), "; ".join(_fails)))
        sys.exit(1)
    print("\nall machine-task + no-dead-end checks passed")
