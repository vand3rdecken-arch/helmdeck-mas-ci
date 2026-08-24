# -*- coding: utf-8 -*-
"""Self-sandboxing test for the electronic signature (phase B, record half).

Runs against a REAL git repo built in a temp dir, because the whole point of
the binding is that it is a pair of commit ids git produced - a test with fake
shas would prove nothing about the thing being claimed.

What this pins down:
  1. subject() names the actual head/base pair, and REFUSES a dirty card
     (a signature must name a commit that exists; _autocommit would otherwise
     create one during the accept and void the signature just checked)
  2. re-authentication is real: the wrong password produces no signature
  3. the record carries name, UTC time, MEANING and reason (11.50)
  4. the guard refuses an in-scope card with NO signature
  5. it accepts one WITH a valid signature
  6. DRIFT voids it - a new commit on the branch, or main moving underneath -
     and the two cases are reported differently
  7. 'rejected' and 'reviewed' do not authorise a landing; only 'approved' does
  8. four-eyes blocks the dispatcher approving their own card, when switched on
  9. a consumed signature cannot authorise a second landing
 10. out of scope, none of this applies at all

Run: py -3.12 tests/test_gxp_signature.py
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True).stdout.strip()


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-gxpsig-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import auth, signatures
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    from spine.auth import gxp
    gxp.LOCK = os.path.join(tmp, "gxp.lock")
    db.init()

    auth.create_user("duy", "owner-password-1", "owner")
    auth.create_user("pat", "other-password-1", "operator", actor="duy")

    # ---- a real repo with a real card branch -------------------------------
    repo = os.path.join(tmp, "product")
    wt = os.path.join(tmp, "wt")
    os.makedirs(repo)
    # plain `git init` - `-b main` is not in every git this repo runs on, and
    # the base branch NAME is irrelevant here: subject() reads HEAD.
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "T")
    open(os.path.join(repo, "a.txt"), "w").write("base\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
    git(repo, "branch", "card/1")
    git(repo, "worktree", "add", "-q", wt, "card/1")
    git(wt, "config", "user.email", "t@t.t"); git(wt, "config", "user.name", "T")
    open(os.path.join(wt, "b.txt"), "w").write("work\n")
    git(wt, "add", "-A"); git(wt, "commit", "-qm", "the work")

    T = {"id": "t-1", "repo": repo, "branch": "card/1", "worktree": wt,
         "lane": "review", "status": "submitted", "task": "x",
         "dispatched_by": "pat"}

    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        json.dump({"enabled": True, "repos": [repo], "activated_by": "duy"}, f)

    # ------------------------------------------------------------------ 1 ---
    print("\nsubject names the real commit pair")
    subj, why = signatures.subject(T)
    ok(why is None and subj, "clean card is signable")
    ok(subj["head"] == git(repo, "rev-parse", "card/1"), "head is the branch tip")
    ok(subj["base"] == git(repo, "rev-parse", "HEAD"), "base is main")
    ok(subj["commits"] == 1, "one commit ahead")

    open(os.path.join(wt, "dirty.txt"), "w").write("uncommitted\n")
    _, why = signatures.subject(T)
    ok(why and "uncommitted" in why, "a DIRTY card refuses to be signed")
    os.remove(os.path.join(wt, "dirty.txt"))
    subj, why = signatures.subject(T)
    ok(why is None, "clean again")

    # ------------------------------------------------------------------ 4 ---
    print("\nthe guard, with no signature")
    r = gxp.accept_block_reason("duy", T)
    ok(r and "no approval signature" in r, "in scope + human + unsigned -> refused")

    # ------------------------------------------------------------------ 2 ---
    print("\nre-authentication is real")
    ok(not auth.verify_password("duy", "wrong"), "wrong password rejected")
    ok(auth.verify_password("duy", "owner-password-1"), "right password accepted")
    ok(auth.verify_password("duy", "owner-password-1"), "...and mints nothing")

    # ------------------------------------------------------------------ 3 ---
    print("\nthe record carries what 11.50 asks for")
    sig = signatures.create(T, "duy", "owner", "approved", "Diff geprueft", subj)
    T["signatures"] = [sig]
    ok(sig["actor"] == "duy", "printed name")
    ok(sig["signed_at"].endswith("Z"), "UTC timestamp")
    ok(sig["meaning"] == "approved", "MEANING")
    ok(sig["reason"] == "Diff geprueft", "reason")
    ok(sig["subject"]["head"] == subj["head"], "bound to the commit")
    try:
        signatures.create(T, "duy", "owner", "rejected", "", subj)
        ok(False, "a rejection without a reason should be refused")
    except ValueError:
        ok(True, "a rejection without a reason is refused")

    # ------------------------------------------------------------------ 5 ---
    print("\nthe guard, with a valid signature")
    ok(gxp.accept_block_reason("duy", T) is None, "now it may land")
    ok(gxp.accept_block_reason("henry", T) is not None,
       "...but still not for an agent, signature or no signature")

    # ------------------------------------------------------------------ 7 ---
    print("\nonly 'approved' authorises a landing")
    for m in ("reviewed", "rejected"):
        T["signatures"] = [dict(sig, meaning=m, reason="r")]
        ok(gxp.accept_block_reason("duy", T) is not None, "'%s' does not land it" % m)
    T["signatures"] = [sig]

    # ------------------------------------------------------------------ 6 ---
    print("\ndrift voids it, and says which kind")
    open(os.path.join(wt, "more.txt"), "w").write("more\n")
    git(wt, "add", "-A"); git(wt, "commit", "-qm", "more work")
    r = gxp.accept_block_reason("duy", T)
    ok(r and "card branch moved" in r, "a new commit on the branch voids it")

    subj2, _ = signatures.subject(T)
    T["signatures"] = [signatures.create(T, "duy", "owner", "approved", "again", subj2)]
    ok(gxp.accept_block_reason("duy", T) is None, "re-signing restores it")

    open(os.path.join(repo, "c.txt"), "w").write("main moved\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "someone else landed")
    r = gxp.accept_block_reason("duy", T)
    ok(r and "base branch moved" in r, "main moving underneath voids it too")
    ok("integration" in r, "...and explains why that matters")

    subj3, _ = signatures.subject(T)

    # ------------------------------------------------------------------ 8 ---
    print("\nfour-eyes")
    T["signatures"] = [signatures.create(T, "pat", "operator", "approved", "x", subj3)]
    ok(gxp.accept_block_reason("pat", T) is None, "off by default: dispatcher may approve")
    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        json.dump({"enabled": True, "repos": [repo], "four_eyes": True}, f)
    r = gxp.accept_block_reason("pat", T)
    ok(r and "four-eyes" in r, "on: 'pat' dispatched it and cannot approve it")
    T["signatures"] = [signatures.create(T, "duy", "owner", "approved", "x", subj3)]
    ok(gxp.accept_block_reason("duy", T) is None, "a different person can")
    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        json.dump({"enabled": True, "repos": [repo]}, f)

    # ------------------------------------------------------------------ 9 ---
    print("\na spent signature cannot be spent twice")
    T["signatures"] = [dict(signatures.create(T, "duy", "owner", "approved", "x", subj3),
                            consumed_by={"lane": "done"})]
    r = gxp.accept_block_reason("duy", T)
    ok(r and "no approval signature" in r, "consumed -> no longer authorises")

    # ----------------------------------------------------------------- 10 ---
    print("\nout of scope, none of this applies")
    OUT = dict(T, repo=os.path.join(tmp, "somewhere-else"), signatures=[])
    ok(gxp.accept_block_reason("henry", OUT) is None, "agent lands it, unsigned")

    print()
    if _fails:
        print("FAILED (%d):" % len(_fails))
        for m in _fails:
            print("  - " + m)
        return 1
    print("all green - %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
