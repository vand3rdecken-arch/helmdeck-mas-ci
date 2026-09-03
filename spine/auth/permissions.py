# -*- coding: utf-8 -*-
"""The permission registry (ops/docs/backlog/rbac-gxp, card 2) - the "EIN Guard"
that answers "can role X ever do Y" from data, instead of ~85 scattered inline
`if user["role"] != "owner"` checks across spine/http/routes and cells/*/routes_*.py.

Mirrors spine/registry/cells.py deliberately: PURE DATA + light live-read
helpers, no caching, lazy imports to dodge cycles (NO-MONKEY-PATCH law - one
owner, read live, never a stored reconstructed flag). Where cells.py answers
"is this whole path-space on", this answers "may THIS role reach it" - same
shape, one layer finer.

WHAT THIS IS NOT (read before adding a check here):
  - Not a resource-ownership check. "Can operators ever accept a card" is a
    capability question; "does THIS card belong to THIS user" is not - that
    stays a manual auth.owns_card()/devices.resolve() call in the handler,
    same as today. A capability matrix answers the first question only.
  - Not a replacement for gxp.py's own chokepoint. GxP's `accept_block_reason`
    gates the lane-transition itself, re-derived from git at accept-time; this
    module gates who may call the HTTP endpoint that *starts* that machinery.
    Two different jobs, both real.

STORAGE: policy_live.json["policies"]["permissions"], seeded in
policy_seed.json under the same key. `policy.swap("policies", {"permissions":
{...}}, actor)` already does the right thing - it replaces exactly that
sub-dict (policy.py's `after.update(patch)` at the top level of "policies"),
so no changes to policy.py were needed. Every matrix edit is therefore
automatically mirrored to the append-only events sink via policy.swap's
existing `_mirror` call - no new audit plumbing.

MIGRATION STATE (2026-08-26): this module and its central enforcement point
in spine/http/server.py are LIVE. Route modules are migrated incrementally,
one at a time, additively - `cap_for()` returns None for anything not yet
declared in GET_CAPS/POST_CAPS/PATTERNS, so an undeclared route's existing
inline check remains its only enforcement (zero behaviour change for the
unmigrated majority). See spine/registry/debt.py "rbac-permission-registry-
partial" for exactly which modules are migrated vs. still inline-only.
"""
import re

# Closed vocabulary. A capability not listed here cannot appear in the matrix
# (validated by ops/tests/test_permissions_seed.py) - this is what keeps the
# matrix reviewable as a single flat list instead of accreting free strings.
CAPS = (
    "settings.read", "settings.write",
    "users.manage",
    "recordings.view",
    "audit.read",
    "devices.manage", "devices.use",
    "chat.use",
    "gxp.activate",
    # "may take a structural action on a card" (move/delete/archive/
    # set_driver/resolve_blocker/resolve_conflict/fast_track) - auth.py's
    # chat_admin_roles() derives from this, replacing the settings.json
    # policy.chat_admin_roles it used to read independently.
    "cards.admin",
    # owner-only diagnostic/introspection reads (cell source for the
    # code-map UI today; room for other read-only harness-internals routes
    # later without inventing a new cap per route).
    "system.introspect",
    # billing-container projects: list is team-visible (owner+operator,
    # same tier as recordings.view), create/update/delete is owner-only.
    "projects.view", "projects.manage",
    # PM (proactive daily-loop) cell: economics/plan/report/reconcile are
    # team-visible, config/consolidate (changes the loop's own policy) is
    # owner-only.
    "pm.view", "pm.manage",
    # process TEMPLATES (config-consolidation, process/config split
    # 2026-09-03): the reusable step SHAPE is config, same tier as projects -
    # view is team-visible, save/delete/from_process is owner-only. A
    # process RUN stays open to every role (processes_get/processes_new_post
    # carry no cap), same as before this split.
    "templates.view", "templates.manage",
)

# role -> tuple(cap) as shipped. This is the CURRENT effective behaviour,
# read by hand off the inline checks in routes_settings.py, routes_runs.py,
# routes_audit.py, routes_devices.py, routes_misc.py, and server.py's /users
# + client-blanket-POST blocks, at the moment of migration - not guessed.
# `auditor`/`quality` (card 3) are not seeded here yet; card 3 adds them via
# a tracked policy.swap, same as any other matrix change.
_DEFAULT_MATRIX = {
    "owner": (
        "settings.read", "settings.write", "users.manage", "recordings.view",
        "audit.read", "devices.manage", "devices.use", "chat.use",
        "gxp.activate", "cards.admin", "system.introspect",
        "projects.view", "projects.manage", "pm.view", "pm.manage",
        "templates.view", "templates.manage",
    ),
    "operator": (
        "recordings.view", "devices.manage", "devices.use", "chat.use",
        "cards.admin", "projects.view", "pm.view", "templates.view",
    ),
    "client": (),
    # card 3 (ops/docs/backlog/rbac-gxp): quality is the SoD approver - its
    # real power (accept a card, subject to lanemachine._sod_block_reason) is
    # enforced structurally, not through an HTTP capability, so it carries no
    # extra caps here beyond the baseline every role gets implicitly (none are
    # in CAPS without being listed - "no caps" really does mean no caps).
    "quality": (),
    # auditor is read-only, everywhere, by construction: every capability
    # here is a *.read/view one, and NONE of the write caps (settings.write,
    # users.manage, devices.manage, gxp.activate) are listed for it.
    "auditor": ("settings.read", "recordings.view", "audit.read"),
}


def _policies():
    try:
        from spine.auth import policy
        return policy.get_policies()
    except Exception:
        return {}


# The CAPS vocabulary as it stood when matrices STARTED being stored (the
# original rbac ship, 3149243, 2026-08-26 - read off that commit, not
# guessed). A stored matrix carrying no explicit `_known_caps` list was
# necessarily written against exactly this vocabulary, so its silences are
# only meaningful for THESE caps: a cap absent from such a matrix that is
# also absent from this tuple provably POST-DATES the store and was never
# deliberately revoked - it gets its seeded default. This is the new-cap
# rollout seam the original design lacked (found 2026-09-03 adding
# templates.*, the first cap after rollout: the owner himself was 403'd on
# his own live workspace because the stored matrix could never learn a new
# cap). set_role_caps() stamps `_known_caps` = CAPS on every write, so from
# the first post-fix matrix edit onward this frozen tuple is no longer
# consulted - the doc carries its own vocabulary.
_ROLLOUT_CAPS = (
    "settings.read", "settings.write", "users.manage", "recordings.view",
    "audit.read", "devices.manage", "devices.use", "chat.use",
    "gxp.activate", "cards.admin", "system.introspect",
    "projects.view", "projects.manage", "pm.view", "pm.manage",
)


def matrix():
    """role -> set(cap), read live from the policy plane every call (no
    caching - same contract as cells.enabled()). Falls back to the seeded
    default for any role missing from a hand-edited policy_live.json, so a
    partial/legacy file degrades to "no extra capabilities" rather than
    granting nothing-checked-means-everything-allowed.

    A stored role list is authoritative ONLY for caps its matrix could have
    known (its `_known_caps` stamp, or _ROLLOUT_CAPS for a pre-stamp doc) -
    a cap added to the code AFTER the matrix was stored gets its seeded
    default instead of being silently denied-forever. A cap the owner
    actually revoked stays revoked: it is in the known vocabulary, so the
    stored silence keeps meaning "no"."""
    live = _policies().get("permissions") or {}
    known = set(live.get("_known_caps") or _ROLLOUT_CAPS)
    out = {}
    for role, caps in _DEFAULT_MATRIX.items():
        if role in live:
            out[role] = set(live[role]) | {c for c in caps if c not in known}
        else:
            out[role] = set(caps)
    for role, caps in live.items():
        if role not in out and role != "_known_caps":
            out[role] = set(caps)
    return out


def can(user, cap):
    """Does `user`'s role carry capability `cap`? False for no user at all."""
    if not user:
        return False
    return cap in matrix().get(user.get("role"), set())


def require(user, cap):
    """None if `user` may exercise `cap`, else a (code, body) tuple for the
    caller to `self._send(*denial)`. `cap` must be in CAPS - a typo here fails
    the coverage test, not a silent open door."""
    if can(user, cap):
        return None
    return (403, '{"error": "forbidden: requires %s"}' % cap)


def set_role_caps(role, caps, actor):
    """Read-merge-write through policy.swap so editing one role's list can
    never wipe another's (policy.swap's patch replaces the WHOLE "permissions"
    key, not a per-role merge - see this module's docstring). Stamps
    `_known_caps` = the full CAPS vocabulary at write time, so matrix() can
    tell a deliberate revocation (cap known, absent from the role) from a
    cap that simply didn't exist yet (see _ROLLOUT_CAPS above)."""
    from spine.auth import policy
    current = {r: sorted(c) for r, c in matrix().items()}
    current[role] = sorted(set(caps) & set(CAPS))
    current["_known_caps"] = sorted(CAPS)
    policy.swap("policies", {"permissions": current}, actor=actor,
                note="permissions.set_role_caps(%s)" % role)


# ---- route -> capability lookup -------------------------------------------

# Table-dispatched modules that declare GET_CAPS/POST_CAPS (parallel to their
# GET_ROUTES/POST_ROUTES dicts, same keys). Bare module names, resolved the
# same lazy two-candidate way cells._import_by_bare_name does, so this stays
# import-cycle-free. Add a module here ONLY once its *_CAPS dict is added AND
# its old inline checks are removed (see debt.py for the ones not yet moved).
_CAP_MODULES = (
    "routes_settings",
    "routes_runs",
    "routes_audit",
    "routes_devices",
    "routes_misc",
    "routes_gxp",
    "routes_projects",
    "routes_pm",
)


def _import_module(name):
    import importlib
    for cand in ("spine.http.routes." + name, "cells.engineer.routes." + name,
                 "cells.copilot.routes." + name):
        try:
            return importlib.import_module(cand)
        except ImportError:
            continue
    return None


# Inline path-param routes (server.py's manual if-chains) that are migrated.
# (method, kind, pattern, cap). kind "exact" matches path segments 1:1 with
# `*` as a wildcard segment; "prefix" is a plain str.startswith(). Mirrors
# Cell.owns()'s prefix/exact split, method-aware.
PATTERNS = (
    ("GET", "exact", "/users", "users.manage"),
    ("POST", "exact", "/users", "users.manage"),
    ("POST", "prefix", "/users/", "users.manage"),
    ("POST", "exact", "/devices/*/revoke", "devices.manage"),
    ("GET", "exact", "/devices/*/queue", "devices.use"),
    ("GET", "exact", "/devices/*/card/*", "devices.use"),
    ("POST", "exact", "/devices/*/stream", "devices.use"),
    ("POST", "exact", "/devices/*/submit", "devices.use"),
    # /checkpoints itself (list) is deliberately undeclared - every role may
    # list checkpoints (id/actor/reason/ts only, no values); diff/restore
    # carry or mutate real settings VALUES, same secret class settings.read/
    # write already protect.
    ("GET", "exact", "/checkpoints/*/diff", "settings.read"),
    ("POST", "exact", "/checkpoints/*/restore", "settings.write"),
    ("GET", "exact", "/cells/*/source", "system.introspect"),
    ("POST", "exact", "/projects/*/update", "projects.manage"),
    ("POST", "exact", "/projects/*/delete", "projects.manage"),
    ("POST", "exact", "/process_templates/*/delete", "templates.manage"),
)


def _pattern_cap(method, path, parts):
    for m, kind, pat, cap in PATTERNS:
        if m != method:
            continue
        if kind == "prefix":
            if path.startswith(pat):
                return cap
        else:
            pp = pat.strip("/").split("/")
            if len(pp) == len(parts) and all(a == "*" or a == b for a, b in zip(pp, parts)):
                return cap
    return None


def cap_for(method, path, parts):
    """The capability required to call `method path`, or None if this route
    is not yet migrated (in which case its own inline check is the only
    enforcement, and this function must stay a no-op for it)."""
    cap = _pattern_cap(method, path, parts)
    if cap:
        return cap
    # One table per METHOD, not "GET or else POST". Before PUT existed the
    # else-branch was harmless; with `PUT /me/config` live it would have made a
    # put route silently inherit whatever the SAME PATH's POST_CAPS said - a
    # capability answer for a question nobody asked. An unknown method gets no
    # table and therefore no capability, which is the same no-op contract this
    # function already has for an unmigrated route.
    table = {"GET": "GET_CAPS", "POST": "POST_CAPS", "PUT": "PUT_CAPS",
             "DELETE": "DELETE_CAPS"}.get(method)
    if not table:
        return None
    for name in _CAP_MODULES:
        mod = _import_module(name)
        if mod is None:
            continue
        caps = getattr(mod, table, None)
        if caps and path in caps:
            return caps[path]
    return None
