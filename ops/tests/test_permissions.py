# -*- coding: utf-8 -*-
"""Self-sandboxing test for the permission registry (ops/docs/backlog/rbac-gxp,
card 2): spine/auth/permissions.py's matrix/can/require/cap_for + the coverage
guarantee that keeps the migration honest as more route modules move onto it.

What this pins down:
  1. the closed CAPS vocabulary matches what the seeded matrix actually grants -
     no stray capability string that isn't in CAPS, and no owner/operator/
     client behaviour beyond what's declared
  2. can()/require(): owner/operator/client get exactly the seeded caps, no
     user at all gets nothing
  3. set_role_caps() round-trips through policy.swap and never touches other
     roles' lists (the "replaces the whole permissions key" trap this module's
     docstring warns about)
  4. cap_for() resolves both table-dispatched routes (GET_CAPS/POST_CAPS) and
     PATTERNS path-param routes correctly, and returns None for an unmigrated
     route (the additive-rollout contract - a None here means "defer to the
     handler's own inline check", not "no capability required")
  5. COVERAGE: every key in every migrated module's GET_CAPS/POST_CAPS is
     also a key in that module's GET_ROUTES/POST_ROUTES (and vice versa) -
     this is the mechanical version of "jede Route hat genau 1 Capability"
     from the card's acceptance criteria, for the modules migrated so far.

End-to-end route behavior (a client actually getting a 403 from a live HTTP
request) is covered by ops/tests/test_server_routes.py, not duplicated here -
this file is the registry's own unit test.

Run: py -3.12 ops/tests/test_permissions.py
"""
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
    tmp = tempfile.mkdtemp(prefix="helmdeck-permissions-test-")

    # db FIRST: policy.swap()/load() are db-backed (config-consolidation
    # phase 3) - sandbox DBPATH+ROOT together or a policy.swap() call here
    # would mutate the REAL production policy_doc row (measured 2026-09-03:
    # exactly this gap in a sibling test archived the real settings.json).
    # daemon.paths.DAEMON_ROOT stays REAL: policy.SEED binds to it at import
    # time and must keep resolving to the real tracked policy_seed.json
    # (read-only, safe) - only db.ROOT/DBPATH move.
    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    db.init()

    from spine.auth import policy
    policy.LIVE = os.path.join(tmp, "policy_live.json")  # SEED stays real (read-only)

    from spine.auth import permissions
    from spine.auth import auth

    # ------------------------------------------------------------------ 1 ---
    print("\nCAPS vocabulary matches the seeded matrix")
    m = permissions.matrix()
    ok(set(m) == {"owner", "operator", "client", "quality", "auditor"},
       "matrix has all 5 roles (card 3 added quality/auditor)")
    ok(m["quality"] == set(), "quality carries no HTTP capability - its power is structural (SoD in lanemachine)")
    ok(m["auditor"] <= {"settings.read", "recordings.view", "audit.read"} and
       not (m["auditor"] & {"settings.write", "users.manage", "devices.manage", "gxp.activate"}),
       "auditor is read-only: zero write capabilities, by construction")
    all_granted = set()
    for role, caps in m.items():
        all_granted |= caps
    ok(all_granted <= set(permissions.CAPS),
       "no capability in the matrix that isn't in the closed CAPS vocabulary")
    ok(m["client"] == set(), "client is seeded with zero capabilities")
    ok("gxp.activate" in m["owner"] and "gxp.activate" not in m["operator"],
       "gxp.activate is owner-only, as designed")
    ok("recordings.view" in m["owner"] and "recordings.view" in m["operator"],
       "recordings.view is owner+operator, matching today's /runs behaviour")

    # ------------------------------------------------------------------ 2 ---
    print("\ncan()/require()")
    owner = {"name": "duy", "role": "owner"}
    operator = {"name": "sam", "role": "operator"}
    client = {"name": "ext", "role": "client"}
    ok(permissions.can(owner, "users.manage"), "owner can users.manage")
    ok(not permissions.can(operator, "users.manage"), "operator cannot users.manage")
    ok(not permissions.can(client, "recordings.view"), "client cannot recordings.view")
    ok(not permissions.can(None, "settings.read"), "no user at all -> can() is False")
    ok(permissions.require(owner, "settings.read") is None,
       "require() is None (allowed) for an owner on settings.read")
    denial = permissions.require(client, "settings.read")
    ok(denial is not None and denial[0] == 403, "require() denies a client with 403")
    ok("settings.read" in denial[1], "denial body names the missing capability")

    # ------------------------------------------------------------------ 3 ---
    print("\nset_role_caps() never clobbers another role's list")
    before_operator = set(permissions.matrix()["operator"])
    permissions.set_role_caps("client", ["recordings.view"], actor="duy")
    after = permissions.matrix()
    ok(after["client"] == {"recordings.view"}, "client's new list took effect")
    ok(after["operator"] == before_operator,
       "operator's list is untouched by a client-only edit")
    ok(after["owner"] == m["owner"], "owner's list is untouched too")
    # restore for the rest of this test run
    permissions.set_role_caps("client", [], actor="duy")
    ok(permissions.matrix()["client"] == set(), "client restored to zero caps")

    # ------------------------------------------------------------------ 4 ---
    print("\ncap_for(): table-dispatched routes, PATTERNS, and unmigrated routes")
    ok(permissions.cap_for("GET", "/settings", ["settings"]) == "settings.read",
       "table-dispatched GET_CAPS resolves")
    ok(permissions.cap_for("POST", "/settings", ["settings"]) == "settings.write",
       "table-dispatched POST_CAPS resolves")
    ok(permissions.cap_for("GET", "/audit", ["audit"]) == "audit.read",
       "routes_audit.py's GET_CAPS resolves")
    ok(permissions.cap_for("GET", "/users", ["users"]) == "users.manage",
       "PATTERNS exact match resolves (/users)")
    ok(permissions.cap_for("POST", "/users/duy/role", ["users", "duy", "role"]) == "users.manage",
       "PATTERNS prefix match resolves (/users/<name>/<action>)")
    ok(permissions.cap_for("GET", "/devices/abc123/queue", ["devices", "abc123", "queue"]) == "devices.use",
       "PATTERNS wildcard-segment match resolves (/devices/<id>/queue)")
    ok(permissions.cap_for("GET", "/tracks", ["tracks"]) is None,
       "an unmigrated route (e.g. /tracks) returns None - defers to its own inline check")
    ok(permissions.cap_for("GET", "/runs/somecard/timeline", ["runs", "somecard", "timeline"]) is None,
       "runs_item_get's resource-ownership route is deliberately undeclared, not gated centrally")

    # ------------------------------------------------------------------ 5 ---
    print("\ncoverage: every migrated module's *_CAPS matches its *_ROUTES 1:1")
    for name in permissions._CAP_MODULES:
        mod = permissions._import_module(name)
        ok(mod is not None, "%s imports cleanly" % name)
        if mod is None:
            continue
        for table, caps_name in (("GET_ROUTES", "GET_CAPS"), ("POST_ROUTES", "POST_CAPS")):
            routes = set(getattr(mod, table, {}) or {})
            caps = getattr(mod, caps_name, {}) or {}
            if not routes and not caps:
                continue
            extra_caps = set(caps) - routes
            ok(not extra_caps,
               "%s.%s: no %s entry naming a route absent from %s (got %s)"
               % (name, caps_name, caps_name, table, extra_caps))
            for p, cap in caps.items():
                ok(cap in permissions.CAPS,
                   "%s.%s['%s'] = %r is in the closed CAPS vocabulary" % (name, caps_name, p, cap))
        # every PATTERNS cap is also a real, closed-vocabulary capability
    for method, kind, pat, cap in permissions.PATTERNS:
        ok(cap in permissions.CAPS, "PATTERNS entry %r uses a real capability" % (pat,))

    # ------------------------------------------------------------------ 6 ---
    print("\nauth.chat_admin_roles() derives from the matrix (cards.admin)")
    ok(set(auth.chat_admin_roles()) == {"owner", "operator"},
       "default matches the old settings.json default exactly (%r)" % (auth.chat_admin_roles(),))
    permissions.set_role_caps("client", ["cards.admin"], actor="duy")
    ok("client" in auth.chat_admin_roles(),
       "granting cards.admin to client changes chat_admin_roles() live - one source of truth")
    permissions.set_role_caps("client", [], actor="duy")
    ok("client" not in auth.chat_admin_roles(), "revoking it removes client again")

    print("\nnew-cap rollout seam (found 2026-09-03 adding templates.*): a stored")
    print("matrix must not deny-forever a cap that postdates it, and must keep")
    print("denying a cap that was deliberately revoked")
    # simulate a workspace whose matrix was stored BEFORE templates.* existed:
    # a legacy permissions dict without _known_caps, owner list = the rollout
    # vocabulary minus a DELIBERATE revocation (gxp.activate stripped).
    legacy_owner = [c for c in permissions._ROLLOUT_CAPS if c != "gxp.activate"]
    policy.swap("policies", {"permissions": {"owner": legacy_owner}},
                actor="duy", note="simulate pre-templates stored matrix")
    m = permissions.matrix()
    ok("templates.manage" in m["owner"],
       "a cap UNKNOWN to the stored matrix (postdates _ROLLOUT_CAPS) gets its "
       "seeded default - the owner is not 403'd on his own new feature")
    ok("gxp.activate" not in m["owner"],
       "a cap the stored matrix KNEW and omitted stays revoked - the seam "
       "never re-grants a deliberate revocation")
    # after ANY tracked matrix edit, the doc carries its own vocabulary and
    # the frozen tuple is out of the loop: revoking templates.manage now must
    # stick, exactly like any rollout-era cap.
    permissions.set_role_caps("owner", sorted(set(m["owner"]) - {"templates.manage"}),
                              actor="duy")
    ok("_known_caps" in (policy.get_policies().get("permissions") or {}),
       "set_role_caps stamps _known_caps, making the vocabulary explicit")
    ok("templates.manage" not in permissions.matrix()["owner"],
       "post-stamp, revoking a NEW cap sticks too (no eternal re-grant)")
    ok("_known_caps" not in permissions.matrix(),
       "_known_caps is vocabulary metadata, never surfaced as a role")

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
