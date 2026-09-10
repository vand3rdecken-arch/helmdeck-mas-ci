# -*- coding: utf-8 -*-
"""Invitation objects - ONE flow for "get a person into this workspace"
(owner decree 2026-09-09, 22:15: creating a user and inviting them are the
SAME act, and the role is chosen AT invitation time, like Jira).

WHAT THIS REPLACES. `settings.registration` used to hold ONE global
`invite_code` plus a `default_role`: a single shared secret, valid forever,
reusable by anyone who saw it, handing out whatever role the workspace
happened to be set to at redemption time. Three things wrong with that at
once - no expiry, no single-use, and a role that is a workspace-wide mode
rather than a property of the invitation. An invitation here is an OBJECT:
its own code, its own role, its own expiry, redeemable exactly once.

STORAGE is daemon/state/invites.json - the SAME tier as auth.py's
sessions.json (`ROOT/state/`, git-ignored as `daemon/state/`), and for the
same reason: a pending invitation is a bearer secret with an expiry that the
runtime keeps about its own machinery. It is not an account (users.json) and
not a durable artefact (content/).

DERIVED, NEVER STORED (the NO-MONKEY-PATCH law). "Is this invitation still
usable" is computed from `expires`/`used_by`/`revoked` on every read - there
is no `open` flag anyone could forget to flip. sweep() only garbage-collects
records that have been dead for a while; it never decides liveness.

owner is NOT an invitable role. A link that mints an unrestricted account is
a different risk class from a link that mints a client - promoting someone to
owner stays a deliberate act by an existing owner on an existing account
(POST /users/<name>/role).
"""
import json
import os
import secrets
import threading
import time

from daemon.paths import DAEMON_ROOT as ROOT

INVITES = os.path.join(ROOT, "state", "invites.json")

# Excludes O/0 and I/1 - an invitation code has to survive being dictated over
# the phone. Ported verbatim from the app's own genInviteCode (settings.tsx,
# card 20260909-214625) rather than invented a second time; the generator moved
# server-side because the code is now a stored object the daemon has to
# recognise later, not a string the owner pastes into a settings field.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
ROLES = ("client", "operator")
DEFAULT_TTL_DAYS = 7
# How long a spent (used/revoked/expired) invitation stays visible before
# sweep() drops it - the owner panel shows recent history, the audit sink
# keeps the permanent record.
KEEP_SPENT_DAYS = 30

# Redemption is a read-modify-write on a shared file and "exactly once" is the
# whole point, so the claim runs under a lock. Two people opening the same link
# at the same second is the ordinary case this exists for, not an exotic one.
#
# CEILING, stated rather than hidden: this lock is PROCESS-local, so single-use
# holds because exactly one daemon owns this file - which the singleton lock in
# spine/http/server.serve() enforces (_take_singleton_lock evicts a prior
# daemon before binding). A second daemon pointed at the same daemon/ would
# race here. That is the same assumption users.json and sessions.json already
# make, so this adds no new one.
_lock = threading.Lock()


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _stamp(seconds_ahead):
    return time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(time.time() + seconds_ahead))


def _load():
    if not os.path.exists(INVITES):
        return []
    try:
        with open(INVITES, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        return []


def _save(rows):
    os.makedirs(os.path.dirname(INVITES), exist_ok=True)
    tmp = INVITES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    os.replace(tmp, INVITES)


def _audit(op, actor, code, **extra):
    """Same best-effort contract as auth._audit. The CODE is written down on
    purpose: unlike a device token it is not a long-lived credential, it dies
    on first use, and without it the audit line cannot answer "which invitation
    did this account come from" - the one question an access review asks."""
    try:
        from spine.storage import events
        events.emit("auth", "-", op=op, actor=actor or "-", subject=code, **extra)
    except Exception:
        pass


def gen_code():
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def state(inv):
    """The one function that answers "what is this invitation" - derived from
    the record every time, in a fixed precedence: a revoked invitation reads
    revoked even after it would also have expired."""
    if inv.get("revoked"):
        return "revoked"
    if inv.get("used_by"):
        return "used"
    if (inv.get("expires") or "") <= _now():
        return "expired"
    return "open"


def _public(inv):
    return {"code": inv["code"], "role": inv["role"], "state": state(inv),
            "created": inv.get("created"), "created_by": inv.get("created_by"),
            "expires": inv.get("expires"), "used_by": inv.get("used_by"),
            "used_at": inv.get("used_at"), "note": inv.get("note", "")}


def create(role, actor, ttl_days=None, note=""):
    """Mint an invitation. Returns the public record INCLUDING the code - the
    caller shows it once; nothing is hidden here, because unlike a device token
    the code is only useful until someone signs up with it."""
    if role not in ROLES:
        raise ValueError("role must be one of: %s" % ", ".join(ROLES))
    try:
        days = int(ttl_days or DEFAULT_TTL_DAYS)
    except (TypeError, ValueError):
        raise ValueError("ttl_days must be a number")
    if not 1 <= days <= 90:
        raise ValueError("ttl_days must be between 1 and 90")
    with _lock:
        rows = _load()
        live = {r["code"] for r in rows}
        code = gen_code()
        while code in live:                      # 32^8 - a formality, not a loop
            code = gen_code()
        inv = {"code": code, "role": role, "created": _now(),
               "created_by": actor or "-", "expires": _stamp(days * 86400),
               "used_by": None, "used_at": None, "revoked": False,
               "revoked_by": None, "note": (note or "")[:80]}
        rows.append(inv)
        _save(rows)
    _audit("invite.create", actor, code, role=role, expires=inv["expires"])
    return _public(inv)


def list_all():
    """Newest first: open invitations, then recent history. State is derived
    per row, so a caller filters on `state` instead of on a stored flag."""
    return sorted((_public(r) for r in _load()),
                  key=lambda r: r.get("created") or "", reverse=True)


def count_open():
    return sum(1 for r in _load() if state(r) == "open")


def revoke(code, actor=None):
    code = (code or "").strip().upper()
    with _lock:
        rows = _load()
        inv = next((r for r in rows if r["code"] == code), None)
        if not inv:
            raise ValueError("no such invitation")
        if state(inv) == "used":
            raise ValueError("already used - remove the member instead")
        inv["revoked"] = True
        inv["revoked_by"] = actor or "-"
        inv["revoked_at"] = _now()
        _save(rows)
    _audit("invite.revoke", actor, code, role=inv["role"])
    return _public(inv)


def peek(code):
    """The role this code would grant, or ValueError with a reason a human can
    act on. Read-only - used to validate before anything irreversible happens."""
    code = (code or "").strip().upper()
    inv = next((r for r in _load() if r["code"] == code), None)
    if not inv:
        raise ValueError("unknown invitation code")
    st = state(inv)
    if st != "open":
        raise ValueError({"used": "this invitation has already been used",
                          "revoked": "this invitation was revoked",
                          "expired": "this invitation has expired"}[st])
    return inv["role"]


def claim(code, name):
    """Atomically mark the code spent BY `name` and return its role. Raises for
    anything not open.

    Claim-then-create (with release() below on failure) rather than
    create-then-mark: the window between the two is where a single-use code
    would be redeemable twice, and losing an invitation to a failed signup is
    the cheap side of that trade - the owner mints another in one tap."""
    code = (code or "").strip().upper()
    with _lock:
        rows = _load()
        inv = next((r for r in rows if r["code"] == code), None)
        if not inv:
            raise ValueError("unknown invitation code")
        st = state(inv)
        if st != "open":
            raise ValueError({"used": "this invitation has already been used",
                              "revoked": "this invitation was revoked",
                              "expired": "this invitation has expired"}[st])
        inv["used_by"] = name
        inv["used_at"] = _now()
        _save(rows)
    _audit("invite.redeem", name, code, role=inv["role"], subject_user=name)
    return inv["role"]


def release(code, name):
    """Undo a claim() whose signup then failed - only if this code is still
    held by that same name, so a later legitimate redemption is never undone
    by a straggling error path."""
    code = (code or "").strip().upper()
    with _lock:
        rows = _load()
        inv = next((r for r in rows if r["code"] == code), None)
        if not inv or inv.get("used_by") != name:
            return False
        inv["used_by"] = None
        inv["used_at"] = None
        _save(rows)
    _audit("invite.release", name, code, reason="signup failed")
    return True


def migrate_legacy(actor="system"):
    """Fold the ONE global settings.registration.invite_code into a real
    invitation object, once, and clear the setting.

    The old code keeps working - it becomes THIS invitation's code, so a link
    already sent out still lets exactly one person in, now with the role the
    workspace's `default_role` said at migration time and a real expiry. That
    is the "migrieren statt abschneiden" half of the owner's decree; the
    "ablösen" half is clearing the key so there is exactly one door left.

    Idempotent and derived: it does nothing once the key is empty, so it is
    safe on every boot rather than gated on a stored migration flag."""
    try:
        from spine.storage import events
    except Exception:
        return False
    reg = events.settings().get("registration") or {}
    code = (reg.get("invite_code") or "").strip()
    if not code:
        return False
    role = reg.get("default_role") or "client"
    if role not in ROLES:
        role = "client"
    with _lock:
        rows = _load()
        if not any(r["code"] == code for r in rows):
            rows.append({"code": code, "role": role, "created": _now(),
                         "created_by": actor,
                         "expires": _stamp(DEFAULT_TTL_DAYS * 86400),
                         "used_by": None, "used_at": None, "revoked": False,
                         "revoked_by": None,
                         "note": "migrated from the global invite code"})
            _save(rows)
    # Clear the retired keys through the normal settings path, so the change is
    # mirrored/checkpointed like any other settings edit instead of being poked
    # into the file behind the store's back.
    try:
        events.save_settings({"registration": {"open": bool(reg.get("open")),
                                               "invite_code": "",
                                               "default_role": ""}},
                             actor=actor,
                             reason="global invite code became an invitation object")
    except Exception:
        pass
    _audit("invite.migrate", actor, code, role=role,
           note="global registration.invite_code became an invitation object")
    return True


def sweep():
    """Drop invitations that have been spent for longer than KEEP_SPENT_DAYS.
    Garbage collection only - an invitation's usability is decided by state(),
    never by whether this ran."""
    cutoff = _stamp(-KEEP_SPENT_DAYS * 86400)
    with _lock:
        rows = _load()
        keep = [r for r in rows
                if state(r) == "open"
                or (r.get("used_at") or r.get("revoked_at") or r.get("expires")
                    or "9999") > cutoff]
        if len(keep) == len(rows):
            return 0
        _save(keep)
    _audit("invite.sweep", "system", "-", removed=len(rows) - len(keep))
    return len(rows) - len(keep)
