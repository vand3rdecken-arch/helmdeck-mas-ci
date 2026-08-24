# -*- coding: utf-8 -*-
"""Self-sandboxing test for the signing ROUTES (phase C backend).

Covers what the UI actually calls, against a real git repo - fake shas would
prove nothing about a binding:

  GET  /sign/subject/<id>   what the dialog renders
  POST /sign                one card
  POST /sign/batch          several cards, ONE password

What this pins down:
  1. the subject route reports scope, signer, four-eyes and the commit pair,
     and reports `blocked` (rather than a subject) for an unsignable card
  2. a wrong password produces no signature and answers 401
  3. the signer is the AUTHENTICATED user - a body field cannot override it
  4. batch: one password, N independent records, each with its own commit pair
  5. batch is NOT all-or-nothing: a bad card fails alone
  6. the lockout applies to signing too, so it cannot be a brute-force oracle
     once login is rate-limited

Run: py -3.12 daemon/test_sign_routes.py
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


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True).stdout.strip()


class FakeH:
    """Stands in for the HTTP handler - the routes only ever call _send."""
    def __init__(self):
        self.code = None
        self.body = None

    def _send(self, code, body):
        self.code = code
        self.body = json.loads(body)
        return code


def call(fn, *a):
    h = FakeH()
    fn(h, *a)
    return h


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-signroutes-test-")

    from daemon.spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from daemon.spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from daemon.spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    from daemon import gxp
    gxp.LOCK = os.path.join(tmp, "gxp.lock")
    db.init()

    from daemon.spine.http.routes import routes_sign

    PW = "owner-password-1"
    auth.create_user("duy", PW, "owner")
    USER = {"name": "duy", "role": "owner"}

    # two cards in one real repo
    repo = os.path.join(tmp, "product")
    os.makedirs(repo)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t.t"); git(repo, "config", "user.name", "T")
    open(os.path.join(repo, "a.txt"), "w").write("base\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")

    cards = []
    for n in (1, 2):
        br = "card/%d" % n
        wt = os.path.join(tmp, "wt%d" % n)
        git(repo, "branch", br)
        git(repo, "worktree", "add", "-q", wt, br)
        git(wt, "config", "user.email", "t@t.t"); git(wt, "config", "user.name", "T")
        open(os.path.join(wt, "f%d.txt" % n), "w").write("work %d\n" % n)
        git(wt, "add", "-A"); git(wt, "commit", "-qm", "work %d" % n)
        tid = "t-%d" % n
        db.track_put({"id": tid, "repo": repo, "branch": br, "worktree": wt,
                      "lane": "review", "status": "submitted", "task": "card %d" % n,
                      "dispatched_by": "pm"})
        cards.append(tid)

    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        json.dump({"enabled": True, "repos": [repo], "activated_by": "duy"}, f)

    # ------------------------------------------------------------------ 1 ---
    print("\nGET /sign/subject")
    h = call(routes_sign.sign_subject_get, USER, "t-1")
    ok(h.code == 200, "200 for a real card")
    ok(h.body["in_scope"] is True, "reports it is in scope")
    ok(h.body["signer"] == {"name": "duy", "role": "owner"}, "names the signer")
    ok(h.body["dispatched_by"] == "pm", "reports who filed it (four-eyes input)")
    ok(h.body["blocked"] is None and h.body["subject"], "signable -> a subject")
    ok(h.body["subject"]["head"] == git(repo, "rev-parse", "card/1"),
       "subject head is the real branch tip")

    open(os.path.join(tmp, "wt1", "dirty.txt"), "w").write("x\n")
    h = call(routes_sign.sign_subject_get, USER, "t-1")
    ok(h.body["subject"] is None and "uncommitted" in (h.body["blocked"] or ""),
       "dirty card -> blocked, with a reason a person can act on")
    os.remove(os.path.join(tmp, "wt1", "dirty.txt"))

    h = call(routes_sign.sign_subject_get, USER, "t-nope")
    ok(h.code == 404, "404 for a card that is not there")

    # ------------------------------------------------------------------ 2 ---
    print("\nPOST /sign - wrong password")
    h = call(routes_sign.sign_post, USER,
             {"card": "t-1", "meaning": "approved", "reason": "x", "password": "WRONG"})
    ok(h.code == 401, "401")
    ok(not (db.track_get("t-1").get("signatures") or []), "no signature was written")

    # ------------------------------------------------------------------ 3 ---
    print("\nPOST /sign - the signer is the authenticated user")
    h = call(routes_sign.sign_post, USER,
             {"card": "t-1", "meaning": "approved", "reason": "geprueft",
              "password": PW, "actor": "somebody-else", "user": "somebody-else"})
    ok(h.code == 200, "200")
    sig = db.track_get("t-1")["signatures"][0]
    ok(sig["actor"] == "duy", "body fields could NOT override the signer")
    ok(sig["meaning"] == "approved" and sig["reason"] == "geprueft", "meaning + reason stored")
    ok(sig["signed_at"].endswith("Z"), "UTC timestamp")
    ok(gxp.accept_block_reason("duy", db.track_get("t-1")) is None,
       "the card may now be landed")

    # ------------------------------------------------------------------ 4 ---
    print("\nPOST /sign/batch - one password, N records")
    git(repo, "branch", "card/3")
    wt3 = os.path.join(tmp, "wt3")
    git(repo, "worktree", "add", "-q", wt3, "card/3")
    git(wt3, "config", "user.email", "t@t.t"); git(wt3, "config", "user.name", "T")
    open(os.path.join(wt3, "f3.txt"), "w").write("work 3\n")
    git(wt3, "add", "-A"); git(wt3, "commit", "-qm", "work 3")
    db.track_put({"id": "t-3", "repo": repo, "branch": "card/3", "worktree": wt3,
                  "lane": "review", "status": "submitted", "task": "card 3"})

    h = call(routes_sign.sign_batch_post, USER, {
        "cards": [{"card": "t-2", "meaning": "approved", "reason": "a"},
                  {"card": "t-3", "meaning": "approved", "reason": "b"}],
        "password": PW})
    ok(h.code == 200, "200")
    res = {r["card"]: r for r in h.body["results"]}
    ok(all(r["ok"] for r in res.values()), "both signed")
    s2 = db.track_get("t-2")["signatures"][0]
    s3 = db.track_get("t-3")["signatures"][0]
    ok(s2["subject"]["head"] != s3["subject"]["head"],
       "each record is bound to its OWN commit, not a shared one")
    ok(s2["actor"] == s3["actor"] == "duy", "both name the signer")

    h = call(routes_sign.sign_batch_post, USER, {
        "cards": [{"card": "t-2", "meaning": "approved", "reason": "x"}],
        "password": "WRONG"})
    ok(h.code == 401, "batch also refuses a wrong password")

    # ------------------------------------------------------------------ 5 ---
    print("\nbatch is not all-or-nothing")
    git(repo, "branch", "card/4")
    wt4 = os.path.join(tmp, "wt4")
    git(repo, "worktree", "add", "-q", wt4, "card/4")
    git(wt4, "config", "user.email", "t@t.t"); git(wt4, "config", "user.name", "T")
    open(os.path.join(wt4, "f4.txt"), "w").write("work 4\n")
    git(wt4, "add", "-A"); git(wt4, "commit", "-qm", "work 4")
    db.track_put({"id": "t-4", "repo": repo, "branch": "card/4", "worktree": wt4,
                  "lane": "review", "status": "submitted", "task": "card 4"})
    open(os.path.join(wt4, "dirty.txt"), "w").write("x\n")   # this one cannot sign

    h = call(routes_sign.sign_batch_post, USER, {
        "cards": [{"card": "t-4", "meaning": "approved", "reason": "x"},
                  {"card": "t-1", "meaning": "reviewed", "reason": "y"}],
        "password": PW})
    res = {r["card"]: r for r in h.body["results"]}
    ok(res["t-4"]["ok"] is False and "uncommitted" in res["t-4"]["error"],
       "the unsignable card failed with its own reason")
    ok(res["t-1"]["ok"] is True, "...and the other one still went through")

    # ------------------------------------------------------------------ 6 ---
    print("\nthe lockout covers signing too")
    for _ in range(auth.LOCK_AFTER):
        call(routes_sign.sign_post, USER,
             {"card": "t-1", "meaning": "reviewed", "reason": "x", "password": "WRONG"})
    h = call(routes_sign.sign_post, USER,
             {"card": "t-1", "meaning": "reviewed", "reason": "x", "password": PW})
    ok(h.code == 401, "the CORRECT password is refused while locked out")
    auth._clear_failures("duy")

    print("\nno secret in the audit")
    blob = open(events.EV, encoding="utf-8").read()
    ok(PW not in blob, "the password never reached the audit")

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
