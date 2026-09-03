# -*- coding: utf-8 -*-
"""Self-sandboxing test for Separation of Duties (ops/docs/backlog/rbac-gxp,
card 3): cells/engineer/lanemachine.py's `_sod_block_reason`, the accept-side
counterpart to gxp.py's own chokepoint (same shape, same position in
_move_lane, deliberately a SEPARATE check - a repo can run GxP without SoD or
SoD without GxP).

What this pins down:
  1. policy.sod_accept OFF (the shipped default) blocks nobody - owner,
     operator and even the card's own dispatcher can all still accept,
     unchanged from before this card
  2. ON: a non-quality role (owner, operator, or an unknown/agent name) is
     refused, named, with its actual role in the message
  3. ON: a quality actor who is NOT the card's dispatcher is allowed through
  4. ON: a quality actor who IS the card's own dispatcher is refused - the
     actual Separation of Duties property, not just a role check
  5. tracks_new_post (cells/engineer/routes_tracks.py) refuses quality/auditor
     unconditionally, independent of the sod_accept knob - the dispatch-side
     half of "quality can accept but not dispatch"
  6. auth.ROLES actually includes quality/auditor now, and create_user accepts
     them (no separate role-validation path missed)

Run: py -3.12 ops/tests/test_sod_accept.py
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
    tmp = tempfile.mkdtemp(prefix="helmdeck-sod-test-")

    # db FIRST: policy is db-backed (config-consolidation phase 3) - sandbox
    # DBPATH+ROOT together, never DBPATH alone (measured 2026-09-03 in a
    # sibling test: that gap archived the real daemon/settings.json).
    # daemon.paths.DAEMON_ROOT stays REAL so policy.SEED keeps resolving to
    # the real tracked policy_seed.json (read-only, safe).
    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    db.init()

    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    from spine.auth import policy
    policy.LIVE = os.path.join(tmp, "policy_live.json")

    from cells.engineer.cards import lanemachine

    auth.create_user("duy", "a-real-password", "owner")
    auth.create_user("sam", "a-real-password", "operator")
    auth.create_user("qa", "a-real-password", "quality")
    ok("quality" in auth.ROLES and "auditor" in auth.ROLES,
       "auth.ROLES includes quality and auditor")
    ok(auth.get_user("qa")["role"] == "quality", "create_user accepts the quality role")

    CARD = {"id": "t-sod-1", "dispatched_by": "sam"}

    # ------------------------------------------------------------------ 1 ---
    print("\nsod_accept OFF (shipped default) - nobody is blocked")
    ok(not policy.get_policies().get("sod_accept", False), "default is off")
    for actor in ("duy", "sam", "qa", "unknown-agent"):
        ok(lanemachine._sod_block_reason(actor, CARD) is None,
           "%s passes while SoD is off" % actor)

    # ------------------------------------------------------------------ 2 ---
    print("\nsod_accept ON - non-quality roles are refused, named")
    policy.swap("policies", {"sod_accept": True}, actor="duy")
    ok(policy.get_policies().get("sod_accept") is True, "policy flipped on")
    r = lanemachine._sod_block_reason("duy", CARD)
    ok(r is not None and "owner" in r, "owner refused, told its actual role")
    r = lanemachine._sod_block_reason("sam", CARD)
    ok(r is not None and "operator" in r, "operator refused, told its actual role")
    r = lanemachine._sod_block_reason("henry", CARD)
    ok(r is not None and "not a real account" in r,
       "an agent/unknown name refused as a non-account, not as a wrong role")

    # ------------------------------------------------------------------ 3 ---
    print("\nsod_accept ON - a quality actor who did NOT dispatch this card passes")
    ok(lanemachine._sod_block_reason("qa", CARD) is None,
       "qa (quality, not the dispatcher) is allowed through")

    # ------------------------------------------------------------------ 4 ---
    print("\nsod_accept ON - the real SoD property: quality dispatcher can't self-accept")
    auth.create_user("qa2", "a-real-password", "quality")
    SELF_DISPATCHED = {"id": "t-sod-2", "dispatched_by": "qa2"}
    r = lanemachine._sod_block_reason("qa2", SELF_DISPATCHED)
    ok(r is not None and "dispatched this card" in r,
       "qa2 dispatched this card and is refused despite holding the quality role")
    ok(lanemachine._sod_block_reason("qa", SELF_DISPATCHED) is None,
       "a DIFFERENT quality actor (qa) may accept the same card")

    # ------------------------------------------------------------------ 5 ---
    print("\ntracks_new_post refuses quality/auditor unconditionally (dispatch side)")
    import json as _json
    class _FakeSelf:
        def _send(self, code, body, ctype="application/json"):
            self.sent = (code, _json.loads(body) if isinstance(body, str) else body)
    from cells.engineer.routes import routes_tracks
    for role, name in (("quality", "qa"), ("auditor", "aud1")):
        if role == "auditor":
            auth.create_user(name, "a-real-password", "auditor")
        fs = _FakeSelf()
        routes_tracks.tracks_new_post(fs, {"name": name, "role": role}, {"task": "x"})
        ok(fs.sent[0] == 403 and "error" in fs.sent[1],
           "%s cannot file/dispatch a new card (403)" % role)

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
