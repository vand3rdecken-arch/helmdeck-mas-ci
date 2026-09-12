# -*- coding: utf-8 -*-
"""Self-sandboxing test for card 6 (ops/docs/backlog/rbac-gxp): GxP-mode
activation from the UI - POST /gxp/activate (spine/http/routes/routes_gxp.py)
and spine/auth/gxp.py's new activate() function. Extends the
test_gxp_guard.py/test_gxp_signature.py/test_gxp_tag.py family.

What this pins down:
  1. gxp.activate() writes a real gxp.lock that gxp.active()/state() read back
     correctly - activated_by is exactly the name passed in, at_utc is real
  2. scope only grows: activating again with a DIFFERENT repo list unions
     with what was already there, never drops a repo; once workspace-wide
     (repos=None), a later call with a specific repos list stays
     workspace-wide
  3. the daemon route requires (a) the gxp.activate capability - denied for
     non-owner roles even with the correct password, and (b) a correct
     password - denied for the owner with the WRONG password, even though
     the capability check passes
  4. activated_by in the resulting lock is ALWAYS the authenticated caller's
     own name, never a body field (the actor-string-forgeability the module
     docstring warns policy.swap() is vulnerable to)
  5. the activation is audited: an events.emit("gxp", op="activate", ...)
     row exists, readable via events.query_audit (card 5's shared filter)
  6. the picker follow-up: GET /gxp/state's known_repos surfaces
     settings.pm.repos + repo_hooks keys + default_repo (minus whatever is
     already in scope), and POST /gxp/activate's new_repos creates + git
     init's a brand-new path (spine.git.gitutil.init_repo) before folding
     it into scope - and is idempotent against a path that is already a
     git repo, per init_repo's own contract

Run: py -3.12 ops/tests/test_gxp_activate.py
"""
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-gxpactivate-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import policy
    from spine.auth import gxp
    gxp.LOCK = os.path.join(tmp, "gxp.lock")
    db.init(role="tool")

    auth.create_user("duy", "a-real-password", "owner")
    auth.create_user("sam", "a-real-password", "operator")

    REPO_A = os.path.join(tmp, "repo-a")
    REPO_B = os.path.join(tmp, "repo-b")

    # ------------------------------------------------------------------ 1 ---
    print("\ngxp.activate() writes a real, readable lock")
    ok(not gxp.active(), "starts off")
    rec = gxp.activate(repos=[REPO_A], four_eyes=False, activated_by="duy")
    ok(gxp.active(), "now active")
    ok(rec["activated_by"] == "duy", "activate() return value names the activator")
    ok(rec["scope"] == "repos" and rec["repos"] == [os.path.abspath(REPO_A)],
       "scoped to the one repo given")
    st = gxp.state()
    ok(st["active"] and st["activated_by"] == "duy", "state() agrees")

    # ------------------------------------------------------------------ 2 ---
    print("\nscope only ever grows")
    gxp.activate(repos=[REPO_B], four_eyes=False, activated_by="duy")
    st = gxp.state()
    ok(set(st["repos"]) == {os.path.abspath(REPO_A), os.path.abspath(REPO_B)},
       "second activate() UNIONS the new repo in, doesn't replace (%r)" % (st["repos"],))
    gxp.activate(repos=None, four_eyes=False, activated_by="duy")
    ok(gxp.state()["scope"] == "workspace", "repos=None widens to the whole workspace")
    gxp.activate(repos=[REPO_A], four_eyes=False, activated_by="duy")
    ok(gxp.state()["scope"] == "workspace",
       "a later specific-repo call cannot NARROW back from workspace-wide")

    # reset for the route-level tests below
    os.remove(gxp.LOCK)
    ok(not gxp.active(), "lock removed for the route tests")

    # ------------------------------------------------------------------ 3+4 -
    print("\nPOST /gxp/activate: capability gate + real password re-auth + real HTTP round trip")
    import http.client
    from spine.http import server
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        def req(method, path, body=None, cookie=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Content-Type": "application/json"}
            if cookie:
                headers["Cookie"] = "sd_session=%s" % cookie
            conn.request(method, path, body=payload, headers=headers)
            r = conn.getresponse()
            data = r.read()
            conn.close()
            try:
                parsed = json.loads(data) if data else None
            except ValueError:
                parsed = None
            return r.status, parsed

        owner_sid = auth.login("duy", "a-real-password")
        operator_sid = auth.login("sam", "a-real-password")

        status, resp = req("POST", "/gxp/activate",
                           {"repos": [REPO_A], "password": "a-real-password"},
                           cookie=operator_sid)
        ok(status == 403, "operator refused by the capability gate (got %d)" % status)
        ok(not gxp.active(), "...and nothing was written")

        status, resp = req("POST", "/gxp/activate",
                           {"repos": [REPO_A], "password": "WRONG-password"},
                           cookie=owner_sid)
        ok(status == 401, "owner with the WRONG password refused (got %d)" % status)
        ok(not gxp.active(), "...and nothing was written despite passing the capability gate")

        status, resp = req("POST", "/gxp/activate",
                           {"repos": [REPO_A], "password": "a-real-password"},
                           cookie=owner_sid)
        ok(status == 200, "owner with the correct password succeeds (got %d)" % status)
        ok(gxp.active(), "mode is active immediately - no daemon restart needed")
        ok(resp.get("activated_by") == "duy", "activated_by is the authenticated caller")

        # actor-forgery attempt: a body field claiming to be someone else must
        # be ignored - activated_by is ALWAYS the session's own name.
        status, resp2 = req("POST", "/gxp/activate",
                            {"repos": [REPO_A], "password": "a-real-password", "activated_by": "henry"},
                            cookie=owner_sid)
        ok(resp2.get("activated_by") == "duy",
           "a spoofed activated_by in the body is ignored - still 'duy', not 'henry'")

        # -- 6a: known_repos surfaces already-known paths, not the active one --
        os.remove(gxp.LOCK)
        orig_settings = events.settings
        events.settings = lambda: {"pm": {"repos": [REPO_A]},
                                   "repo_hooks": {REPO_B: {"deploy": "x"}},
                                   "default_repo": REPO_A}
        try:
            status, resp = req("GET", "/gxp/state", cookie=owner_sid)
            known = set(resp.get("known_repos") or [])
            ok({REPO_A, REPO_B} <= known, "known_repos surfaces pm.repos + repo_hooks keys (%r)" % known)
            gxp.activate(repos=[REPO_A], activated_by="duy")
            status, resp = req("GET", "/gxp/state", cookie=owner_sid)
            known2 = set(resp.get("known_repos") or [])
            ok(REPO_A not in known2 and REPO_B in known2,
               "an already-in-scope repo is dropped from known_repos, not re-offered (%r)" % known2)
        finally:
            events.settings = orig_settings
        os.remove(gxp.LOCK)

        # -- 6b: new_repos creates + git-inits a brand-new path -----------------
        NEW_REPO = os.path.join(tmp, "created-by-picker")
        ok(not os.path.isdir(NEW_REPO), "path does not exist yet")
        status, resp = req("POST", "/gxp/activate",
                           {"new_repos": [NEW_REPO], "password": "a-real-password"},
                           cookie=owner_sid)
        ok(status == 200, "activation with only new_repos succeeds (got %d)" % status)
        ok(os.path.isdir(os.path.join(NEW_REPO, ".git")), "the path is now a real git repo")
        rc = __import__("subprocess").run(["git", "-C", NEW_REPO, "log", "--oneline"],
                                          capture_output=True, text=True)
        ok(rc.returncode == 0 and rc.stdout.strip(),
           "it has a seed commit, not an empty init (audit trail needs history)")
        ok(resp.get("created_repos") == [os.path.abspath(NEW_REPO)],
           "the route reports which repos it created (%r)" % resp.get("created_repos"))
        ok(os.path.abspath(NEW_REPO) in (resp.get("repos") or []),
           "the newly-created repo landed in scope, not just on disk")
        os.remove(gxp.LOCK)
    finally:
        httpd.shutdown()

    # ------------------------------------------------------------------ 5 ---
    print("\nthe activation is audited and readable via query_audit")
    rows = events.query_audit(kind="gxp")
    ok(any(r.get("op") == "activate" and r.get("actor") == "duy" for r in rows),
       "an activate event exists, actor=duy")

    # ------------------------------------------------------------------ 6c --
    print("\ngitutil.init_repo() is idempotent on an already-git path")
    from spine.git import gitutil
    already = os.path.join(tmp, "already-a-repo")
    os.makedirs(already)
    __import__("subprocess").run(["git", "-C", already, "init", "-q"])
    __import__("subprocess").run(["git", "-C", already, "-c", "user.email=a@a.a",
                                  "-c", "user.name=a", "commit", "--allow-empty", "-qm", "x"])
    head_before = __import__("subprocess").run(["git", "-C", already, "rev-parse", "HEAD"],
                                               capture_output=True, text=True).stdout.strip()
    rec = gitutil.init_repo(already, actor="duy")
    ok(rec["git_initialized"] is False, "an already-git path is reported untouched")
    head_after = __import__("subprocess").run(["git", "-C", already, "rev-parse", "HEAD"],
                                              capture_output=True, text=True).stdout.strip()
    ok(head_before == head_after, "no new commit was added to an existing repo (%s -> %s)" % (head_before, head_after))

    print()
    if _fails:
        print("FAILED (%d):" % len(_fails))
        for msg in _fails:
            print("  - " + msg)
        return 1
    print("all green - %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
