# -*- coding: utf-8 -*-
"""Self-sandboxing test for GPG-signed approval tags (the last GxP gap).

Closes debt gxp-signature-not-independently-verifiable. The whole value of the
tag is that an AUDITOR can verify it with stock tools and zero trust in
HelmDeck - so the central assertion here IS that story, end to end:

  a fresh GNUPGHOME that has never seen this installation
  + nothing but the exported public key
  + stock `git verify-tag`
  = PASS. And without the key: FAIL.

Runs against the real gpg (ships with Git for Windows) and a real git repo -
a mocked gpg would prove the mock.

What this pins down:
  1. approving a card creates refs/tags/gxp/approve/<card>-<seq> as a REAL
     signed tag object pointing at the signed head commit
  2. the auditor loop: verify-tag fails with no key, passes after importing
     the exported .asc - proving the public-key file alone is sufficient
  3. the tag message carries the full manifestation (11.50: actor, UTC time,
     meaning, reason, head/base) as greppable JSON
  4. record and event both carry tag + tag_sha + fingerprint (the
     cross-witness: the sink names the tag, the tag names the card)
  5. reviewed/rejected produce NO tag - they authorise nothing
  6. an approval whose tag cannot be created FAILS outright (strict) - no
     silently unanchored approvals
  7. password change rotates the key: the next approval gets a new
     fingerprint, and the OLD tag still verifies with the OLD exported key

Run: py -3.12 ops/tests/test_gxp_tag.py
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def git(repo, *a, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["git", "-C", repo, *a],
                          capture_output=True, text=True, env=e)


class FakeH:
    def __init__(self):
        self.code, self.body = None, None

    def _send(self, code, body):
        self.code, self.body = code, json.loads(body)
        return code


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-gxptag-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import auth, signkeys
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    signkeys.KEYS_DIR = os.path.join(tmp, "signkeys")
    from spine.auth import gxp
    gxp.LOCK = os.path.join(tmp, "gxp.lock")
    db.init()

    from spine.http.routes import routes_sign

    PW = "owner-password-1"
    auth.create_user("duy", PW, "owner")
    USER = {"name": "duy", "role": "owner"}
    gpg = signkeys._gpg_exe()
    print("gpg:", gpg)

    # real repo, real card branch
    repo = os.path.join(tmp, "product")
    os.makedirs(repo)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "T")
    open(os.path.join(repo, "a.txt"), "w").write("base\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
    git(repo, "branch", "card/1")
    wt = os.path.join(tmp, "wt1")
    git(repo, "worktree", "add", "-q", wt, "card/1")
    git(wt, "config", "user.email", "t@t.t"); git(wt, "config", "user.name", "T")
    open(os.path.join(wt, "f1.txt"), "w").write("work\n")
    git(wt, "add", "-A"); git(wt, "commit", "-qm", "work")
    head = git(repo, "rev-parse", "card/1").stdout.strip()

    db.track_put({"id": "t-1", "repo": repo, "branch": "card/1", "worktree": wt,
                  "lane": "review", "status": "submitted", "task": "x"})
    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        json.dump({"enabled": True, "repos": [repo]}, f)

    # ------------------------------------------------------------------ 1 ---
    print("\napproval creates a real signed tag")
    h = FakeH()
    routes_sign.sign_post(h, USER, {"card": "t-1", "meaning": "approved",
                                    "reason": "geprueft", "password": PW})
    ok(h.code == 200, "sign succeeded (got %s: %s)" % (h.code, h.body))
    sig = (h.body or {}).get("signature") or {}
    tag = sig.get("git", {}).get("tag")
    fpr = sig.get("git", {}).get("fingerprint")
    ok(tag == "gxp/approve/t-1-1", "tag name is gxp/approve/<card>-<seq> (got %r)" % tag)
    r = git(repo, "rev-parse", "refs/tags/" + (tag or "missing"))
    ok(r.returncode == 0, "the ref actually exists in the repo")
    ok(r.stdout.strip() == sig["git"]["tag_sha"], "record's tag_sha matches the ref")
    target = git(repo, "rev-parse", (tag or "") + "^{commit}").stdout.strip()
    ok(target == head, "the tag points at the SIGNED head commit")

    # ------------------------------------------------------------------ 3 ---
    print("\nthe tag message is the manifestation")
    body = git(repo, "cat-file", "tag", tag).stdout
    ok("BEGIN PGP SIGNATURE" in body, "the tag object embeds a PGP signature")
    payload = body.split("-----BEGIN PGP SIGNATURE-----")[0]
    mani = json.loads(payload.split("\n\n", 1)[1].strip())
    ok(mani["actor"] == "duy" and mani["meaning"] == "approved"
       and mani["reason"] == "geprueft" and mani["head"] == head
       and mani["signed_at"].endswith("Z"),
       "manifestation carries actor/meaning/reason/head/UTC time")

    # ------------------------------------------------------------------ 2 ---
    print("\nTHE auditor loop: stock git verify-tag, zero HelmDeck code")
    auditor = os.path.join(tmp, "auditor-gnupg")
    os.makedirs(auditor)
    ver_env = {"GNUPGHOME": auditor}
    r = git(repo, "-c", "gpg.program=" + gpg, "verify-tag", tag, env=ver_env)
    ok(r.returncode != 0, "WITHOUT the public key: verification fails")
    pub = signkeys.public_key_path("duy", fpr)
    ok(os.path.exists(pub), "the public key was exported at generation time")
    subprocess.run([gpg, "--batch", "--import", pub],
                   capture_output=True, env=dict(os.environ, GNUPGHOME=auditor))
    # judge the import by its OUTCOME (is the key in the ring), not the exit
    # code - gpg's first run against an empty home returns non-zero for
    # keybox-creation noise while importing perfectly well
    lst = subprocess.run([gpg, "--batch", "--list-keys", fpr],
                         capture_output=True, env=dict(os.environ, GNUPGHOME=auditor))
    ok(lst.returncode == 0, "auditor now holds the public key")
    r = git(repo, "-c", "gpg.program=" + gpg, "verify-tag", tag, env=ver_env)
    ok(r.returncode == 0, "WITH it: stock `git verify-tag` PASSES (%s)"
       % (r.stderr.strip().splitlines()[-1][:60] if r.stderr else ""))

    # ------------------------------------------------------------------ 4 ---
    print("\ncross-witness: record and event name the tag")
    rows = [json.loads(l) for l in open(events.EV, encoding="utf-8") if l.strip()]
    ev = [r2 for r2 in rows if r2.get("kind") == "signature" and r2.get("op") == "signed"][-1]
    ok(ev.get("tag") == tag and ev.get("tag_sha") == sig["git"]["tag_sha"],
       "the event carries tag + tag_sha")
    stored = db.track_get("t-1")["signatures"][0]
    ok(stored["git"]["tag"] == tag and stored["git"]["fingerprint"] == fpr,
       "the stored record carries tag + fingerprint")

    # ------------------------------------------------------------------ 5 ---
    print("\nreviewed/rejected produce no tag")
    h = FakeH()
    routes_sign.sign_post(h, USER, {"card": "t-1", "meaning": "reviewed",
                                    "reason": "angesehen", "password": PW})
    ok(h.code == 200, "reviewed signs fine")
    ok(h.body["signature"]["git"]["tag"] is None, "...with no tag")
    tags = git(repo, "tag", "-l", "gxp/approve/*").stdout.split()
    ok(tags == [tag], "still exactly one approval tag in the repo")

    # ------------------------------------------------------------------ 6 ---
    print("\nan approval that cannot be anchored FAILS, not warns")
    # break BOTH paths: signing normally goes through bash (needs_agent), so
    # breaking only _gpg_exe left signing fully functional - the first version
    # of this test proved nothing and PASSED an approval it meant to fail.
    real_exe, real_bash = signkeys._gpg_exe, signkeys._bash_exe
    signkeys._gpg_exe = lambda: (_ for _ in ()).throw(RuntimeError("gpg gone"))
    signkeys._bash_exe = lambda: None
    h = FakeH()
    routes_sign.sign_post(h, USER, {"card": "t-1", "meaning": "approved",
                                    "reason": "x", "password": PW})
    signkeys._gpg_exe, signkeys._bash_exe = real_exe, real_bash
    ok(h.code == 409 and "approval tag failed" in h.body["error"],
       "broken gpg -> the approval is refused outright")
    ok(len(db.track_get("t-1")["signatures"]) == 2,
       "and no approval record was stored for it")

    # ------------------------------------------------------------------ 7 ---
    print("\npassword change rotates the key, old tags stay verifiable")
    auth.set_password("duy", "brand-new-password", actor="duy")
    # new commit so the card is signable at a new head
    open(os.path.join(wt, "f2.txt"), "w").write("more\n")
    git(wt, "add", "-A"); git(wt, "commit", "-qm", "more")
    h = FakeH()
    routes_sign.sign_post(h, USER, {"card": "t-1", "meaning": "approved",
                                    "reason": "nochmal", "password": "brand-new-password"})
    ok(h.code == 200, "approval works with the NEW password")
    fpr2 = h.body["signature"]["git"]["fingerprint"]
    tag2 = h.body["signature"]["git"]["tag"]
    ok(fpr2 != fpr, "the key ROTATED (new fingerprint)")
    subprocess.run([gpg, "--batch", "--import", signkeys.public_key_path("duy", fpr2)],
                   capture_output=True, env=dict(os.environ, GNUPGHOME=auditor))
    lst = subprocess.run([gpg, "--batch", "--list-keys", fpr2],
                         capture_output=True, env=dict(os.environ, GNUPGHOME=auditor))
    ok(lst.returncode == 0, "auditor now holds the new public key too")
    r = git(repo, "-c", "gpg.program=" + gpg, "verify-tag", tag2, env=ver_env)
    ok(r.returncode == 0, "the new tag verifies")
    r = git(repo, "-c", "gpg.program=" + gpg, "verify-tag", tag, env=ver_env)
    ok(r.returncode == 0, "...and the OLD tag STILL verifies - rotation loses nothing")

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
