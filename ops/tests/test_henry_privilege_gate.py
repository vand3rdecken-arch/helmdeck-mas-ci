# -*- coding: utf-8 -*-
"""Self-sandboxing test: Henry's live-tree HANDS (action "did") must be
unavailable for an escalation on a card a `client`-role account dispatched
(owner decree 2026-08-25 chat: "das soll ok sein, solange user is owner
oder hat genuegend rechte"). Before this, cells/copilot/henry_broker.py had
NO check at all on who dispatched the escalating card - _ask() always used
the same working permission mode regardless of the card's origin.

Covers:
  1. _dispatcher_privileged: owner/operator dispatcher -> True, client
     dispatcher -> False, no card / agent-name dispatcher (pm, henry) ->
     True (nothing to restrict FROM - unchanged from before this fix)
  2. _decide: an unprivileged escalation calls _ask with perm="plan" (no
     edits possible at the tool layer) and the prompt tells Henry he has
     no hands this round
  3. _decide: even if the model answers "did" anyway on an unprivileged
     escalation, it is refused and the escalation stays open - defense in
     depth, not just a prompt instruction
  4. a privileged escalation (owner-dispatched card, or no card at all)
     is completely unaffected - perm=None (henry_pmode() default), "did"
     closes normally

Run: py -3.12 ops/tests/test_henry_privilege_gate.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-henrygate-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    db.init()
    from spine.registry import escalations
    escalations.ESC_PATH = os.path.join(tmp, "escalations.jsonl")

    auth.create_user("duy", "owner-password-1", "owner")
    auth.create_user("opuser", "operator-password-1", "operator")
    auth.create_user("eve", "client-password-1", "client")

    from cells.copilot import henry_broker as hb

    # -- 1: _dispatcher_privileged -------------------------------------------
    print("\n_dispatcher_privileged")
    ok(hb._dispatcher_privileged(None) is True, "no card at all -> privileged (nothing to restrict)")
    ok(hb._dispatcher_privileged({"dispatched_by": "duy"}) is True, "owner dispatcher -> privileged")
    ok(hb._dispatcher_privileged({"dispatched_by": "opuser"}) is True, "operator dispatcher -> privileged")
    ok(hb._dispatcher_privileged({"dispatched_by": "eve"}) is False, "CLIENT dispatcher -> NOT privileged")
    ok(hb._dispatcher_privileged({"dispatched_by": "pm"}) is True, "agent-name dispatcher (not a real account) -> privileged")
    ok(hb._dispatcher_privileged({"dispatched_by": ""}) is True, "empty dispatched_by -> privileged")
    ok(hb._dispatcher_privileged({}) is True, "card dict with no dispatched_by key -> privileged")

    # -- 2 + 3: _decide wiring, via a fake _ask/_execute ----------------------
    # _HENRY_REPO_ROOT patched to a throwaway git repo for the rest of this
    # test - _hands_on_ask (the privileged path) runs REAL git commands
    # (_baseline_commit) against it, and must never touch the actual live
    # HelmDeck checkout this test process happens to be running inside of.
    import subprocess
    henry_repo = os.path.join(tmp, "henry-repo")
    os.makedirs(henry_repo)
    subprocess.run(["git", "-C", henry_repo, "init", "-q"])
    subprocess.run(["git", "-C", henry_repo, "config", "user.email", "t@t.t"])
    subprocess.run(["git", "-C", henry_repo, "config", "user.name", "T"])
    open(os.path.join(henry_repo, "a.txt"), "w").write("base\n")
    subprocess.run(["git", "-C", henry_repo, "add", "-A"])
    subprocess.run(["git", "-C", henry_repo, "commit", "-qm", "base"])
    orig_repo_root = hb._HENRY_REPO_ROOT
    hb._HENRY_REPO_ROOT = henry_repo

    print("\n_decide: perm override + did-refusal for an unprivileged escalation")
    db.track_put({"id": "c-client", "repo": "/x", "branch": "b", "worktree": "/x",
                  "lane": "review", "status": "submitted", "task": "client card",
                  "dispatched_by": "eve"})
    db.track_put({"id": "c-owner", "repo": "/x", "branch": "b2", "worktree": "/x",
                  "lane": "review", "status": "submitted", "task": "owner card",
                  "dispatched_by": "duy"})

    calls = {}
    def fake_ask_did(prompt, model="", perm=None):
        calls["prompt"] = prompt
        calls["perm"] = perm
        return {"action": "did", "card": calls["card"], "text": "fixed it", "why": "x"}

    orig_ask = hb._ask
    orig_execute = hb._execute
    executed = []
    hb._execute = lambda *a: (executed.append(a) or True)

    try:
        hb._ask = fake_ask_did
        calls["card"] = "c-client"
        closed = hb._decide({"id": "e1", "kind": "test", "card": "c-client", "detail": ""})
        ok(calls["perm"] == "plan", "unprivileged escalation calls _ask with perm='plan'")
        ok("KEINE Haende" in calls["prompt"], "prompt tells Henry he has no hands this round")
        ok(closed is False, "a 'did' answer on an unprivileged escalation is REFUSED (stays open)")
        ok(len(executed) == 0, "_execute was never reached - refused before it could close via did")

        executed.clear()
        calls["card"] = "c-owner"
        closed = hb._decide({"id": "e2", "kind": "test", "card": "c-owner", "detail": ""})
        ok(calls["perm"] is None, "privileged escalation calls _ask with perm=None (henry_pmode() default)")
        ok("KEINE Haende" not in calls["prompt"], "prompt carries no hands-restriction note")
        ok(closed is True, "a 'did' answer on a privileged escalation closes normally")
        ok(len(executed) == 1 and executed[0][0] == "did", "_execute WAS reached for the privileged card")

        # a client-dispatched card whose Henry answer is something OTHER than
        # "did" (e.g. steer) must still go through normally - the restriction
        # is scoped to hands, not to Henry acting on the escalation at all.
        def fake_ask_steer(prompt, model="", perm=None):
            calls["perm"] = perm
            return {"action": "steer", "card": "c-client", "text": "please retry", "why": "x"}
        hb._ask = fake_ask_steer
        executed.clear()
        closed = hb._decide({"id": "e3", "kind": "test", "card": "c-client", "detail": ""})
        ok(calls["perm"] == "plan", "still perm='plan' for the unprivileged card")
        ok(closed is True and executed[0][0] == "steer",
           "a non-'did' action on an unprivileged card still executes normally")
    finally:
        hb._ask = orig_ask
        hb._execute = orig_execute

    # -- 5: _baseline_commit -------------------------------------------------
    print("\n_baseline_commit")
    log_before = subprocess.run(["git", "-C", henry_repo, "log", "--oneline"],
                                capture_output=True, text=True).stdout
    hb._baseline_commit()
    log_after = subprocess.run(["git", "-C", henry_repo, "log", "--oneline"],
                               capture_output=True, text=True).stdout
    ok(log_after == log_before, "a CLEAN tree gets no baseline commit (nothing to snapshot)")

    open(os.path.join(henry_repo, "dirty.txt"), "w").write("uncommitted work\n")
    hb._baseline_commit()
    log2 = subprocess.run(["git", "-C", henry_repo, "log", "--oneline"],
                          capture_output=True, text=True).stdout
    ok(log2 != log_after and "Henry baseline" in log2,
       "a DIRTY tree gets a real baseline commit before Henry's hands touch it")
    status = subprocess.run(["git", "-C", henry_repo, "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    ok(status.strip() == "", "the tree is clean again after the baseline commit")

    # -- 6: _hands_on_ask - lock + baseline wrap the privileged path ---------
    print("\n_hands_on_ask")
    open(os.path.join(henry_repo, "dirty2.txt"), "w").write("more uncommitted work\n")
    hb._ask = lambda prompt, model="", perm=None: {"perm_seen": perm}
    try:
        result = hb._hands_on_ask("a judgement prompt")
        ok(result == {"perm_seen": None}, "calls the real _ask with perm=None")
        status = subprocess.run(["git", "-C", henry_repo, "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        ok(status.strip() == "", "the dirty file got baseline-committed before _ask ran")
    finally:
        hb._ask = orig_ask

    # a lock already held by someone else -> _hands_on_ask refuses promptly
    # rather than blocking the whole 90s judgement cycle indefinitely.
    from spine.git import locks as _locks
    busy_lock = _locks._direct_lock_for(henry_repo)
    ok(busy_lock.acquire(blocking=False), "test can grab the lock first")
    try:
        try:
            hb._hands_on_ask("prompt", timeout=0.2)   # short: this is a same-thread hold,
                                                        # nothing will ever release it
            ok(False, "_hands_on_ask must raise when the tree's lock is already held")
        except RuntimeError as e:
            ok("busy" in str(e), "raises a clear 'tree busy' error instead of hanging")
    finally:
        busy_lock.release()

    hb._HENRY_REPO_ROOT = orig_repo_root

    print("\n%d failure(s)" % len(_fails))
    if _fails:
        sys.exit(1)
    print("all green - %s" % tmp)


if __name__ == "__main__":
    main()
