# -*- coding: utf-8 -*-
"""POST /gxp/activate - the UI entry point for GxP mode (ops/docs/backlog/
rbac-gxp card 6; spine/auth/gxp.py's own module docstring, WHY THIS IS CODE
AND NOT A POLICY FLAG). Deliberately the ONLY write route this module has:
deactivation stays host-filesystem + daemon-restart only, by design.

Re-auth pattern is identical to routes_sign.py's (the existing GxP
e-signature precedent): password verified via auth.verify_password, actor is
ALWAYS the authenticated session's own name, never a body field - an actor
string is spoofable, a verified password is not. The capability check
(gxp.activate, owner-only in the seeded matrix) runs centrally in server.py
before this handler is even reached; this function only handles what a
capability check cannot: re-authentication and the write itself.

`new_repos` (card 6 follow-up, "the scope field needs to be more than a
freeform text box"): paths the owner wants to CREATE, not pick from what
already exists. Each one is git-init'd via spine.git.gitutil.init_repo
(idempotent - an already-git path is untouched) before being folded into
the same `repos` list `gxp.activate()` widens scope with, so "create new"
and "select existing" both end up as one signed action, one audit event.
"""
import json

from spine.auth import auth


def gxp_state_get(self, user):
    from spine.auth import gxp
    from spine.storage import events
    st = gxp.state()
    s = events.settings()
    known = set((s.get("pm") or {}).get("repos") or [])
    known |= set((s.get("repo_hooks") or {}).keys())
    default_repo = s.get("default_repo")
    if default_repo:
        known.add(default_repo)
    # no point re-offering a repo that's already in scope
    known -= set(st.get("repos") or [])
    st["known_repos"] = sorted(known)
    return self._send(200, json.dumps(st))


def gxp_activate_post(self, user, body):
    if not auth.verify_password(user["name"], body.get("password") or ""):
        return self._send(401, json.dumps({"error": "password not accepted"}))
    from spine.auth import gxp
    from spine.git import gitutil
    repos = body.get("repos")
    new_repos = body.get("new_repos")
    if repos is not None and not isinstance(repos, list):
        return self._send(400, json.dumps({"error": "repos must be a list of paths, or omitted for workspace-wide scope"}))
    if new_repos is not None and not isinstance(new_repos, list):
        return self._send(400, json.dumps({"error": "new_repos must be a list of paths"}))
    created = []
    for p in (new_repos or []):
        p = (p or "").strip()
        if not p:
            continue
        try:
            rec = gitutil.init_repo(p, actor=user["name"])
        except Exception as e:
            return self._send(400, json.dumps({"error": "could not create/init %r: %s" % (p, str(e)[:200])}))
        created.append(rec["path"])
    # None here still means "leave scope at workspace-wide if the owner
    # picked/created nothing at all" - the exact pre-existing "empty box"
    # contract (spine/auth/gxp.py's activate()), now just fed from two
    # sources (picked + created) instead of one freeform box.
    picked = set(repos or []) | set(created)
    combined = sorted(picked) if picked else None
    rec = gxp.activate(repos=combined, four_eyes=bool(body.get("four_eyes")),
                       activated_by=user["name"], created_repos=created)
    rec["created_repos"] = created
    return self._send(200, json.dumps(rec))


GET_ROUTES = {"/gxp/state": gxp_state_get}
GET_CAPS = {"/gxp/state": "gxp.activate"}
POST_ROUTES = {"/gxp/activate": gxp_activate_post}
POST_CAPS = {"/gxp/activate": "gxp.activate"}
