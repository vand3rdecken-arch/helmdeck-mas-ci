# -*- coding: utf-8 -*-
"""The ACCOUNT's profile: config lives on the account, not on the device.

Phase 1 of ops/docs/backlog/accounts-boards-prd (owner decree 2026-09-01: "let
users create account, log in and then save all config cleanly"). db.py holds
the rows; this module owns everything that makes them safe to expose over an
endpoint any authenticated role may call:

  - the WHITELIST. `PUT /me/config` is reachable by a `client` account - the
    weakest role there is - so the set of writable keys is closed here, in
    code, and is a set of pure VIEW preferences. It can never grow into
    workspace policy: two users with different `auto_accept_green` on one
    shared daemon is not personalization, it is incoherence (the layering the
    superseded per-user-ui-config card argued out; PRD section 3 keeps it).
  - the VALIDATOR per key, so a stored value is always something the renderers
    can actually render - the app must never have to defend against `lang:
    {"$ne": null}` arriving from a compromised client.
  - the SIZE BOUND. Self-scoped writes are unmetered by design (no capability
    to revoke), so the bound is what stops an account from turning its profile
    into free storage on the owner's disk.
  - RESOLUTION. `resolve()` overlays the account's stored rows on the
    workspace defaults. Absent means absent: an account with no `lang` row
    still renders in the workspace language, so shipping this feature resets
    nobody's setup.

WHY the rows key on the user NAME (PRD section 8's open item, decided here):
users.json is the account store and the auth law is fixed, so a config row can
only reference an account by its name. That makes a rename an IDENTITY change,
not an edit - so renaming is BLOCKED while config rows exist, rather than
cascaded. Two reasons the block wins over the cascade: (1) there is no rename
today (spine/auth/auth.py has create/delete/set_password/set_role and no
rename), so blocking forecloses nothing that works - it only fixes the shape
of a feature before it is written; (2) a cascade has to be transactional
across users.json AND every name-keyed table that will exist by phase 2
(`boards.owner`), and a half-applied cascade orphans a user's whole board set
silently. `rename_block_reason()` is the guard a future rename must call; it
derives the answer from the table, never from a stored flag.
"""

# Whitelisted profile keys. ADDING ONE IS A DELIBERATE ACT: it must be a pure
# view preference (see the module docstring), it must have a validator below,
# and the app must declare it in the `Profile` interface in client.ts or the
# ts-contract test in ops/tests/test_harness_layer.py fails.
LANGS = ("de", "en")
BACKDROPS = ("mesh", "aurora", "ember", "forest", "mono")

MAX_VALUE_BYTES = 4096     # per key, JSON-encoded
MAX_KEYS_PER_WRITE = 16


def _valid_lang(v):
    return v in LANGS


def _valid_appearance(v):
    # Exactly the shape settings.appearance has, so the resolved profile is a
    # drop-in for what the app reads today. Unknown sub-keys are REJECTED, not
    # dropped: silently discarding half a write is how a client ends up
    # believing it saved something it did not.
    if not isinstance(v, dict):
        return False
    if set(v) - {"backdrop"}:
        return False
    return v.get("backdrop", "mesh") in BACKDROPS


KEYS = {
    "lang": _valid_lang,
    "appearance": _valid_appearance,
}


def defaults():
    """The workspace layer the account's rows sit on top of. Read live from
    settings.json every call - an owner changing the workspace language still
    moves every account that never picked one."""
    from spine.storage import events
    s = events.settings()
    pol = s.get("policy") or {}
    return {
        "lang": pol.get("lang", "de"),
        "appearance": s.get("appearance") or {"backdrop": "mesh"},
    }


def stored(user):
    """Only the rows this account actually chose (no defaults folded in)."""
    from spine.storage import db
    rows = db.user_config_get(user)
    # A key retired from the whitelist stays on disk but stops being served -
    # the resolved profile must only ever contain keys the app declares.
    return {k: v for k, v in rows.items() if k in KEYS}


def resolve(user):
    """The profile the client renders: workspace defaults, overlaid by the
    account's own rows."""
    out = defaults()
    out.update(stored(user))
    return out


def validate(patch):
    """(cleaned, error). `cleaned` is patch restricted to whitelisted keys with
    valid values; a single bad key fails the WHOLE write rather than being
    dropped, so a caller is never told "ok" about a value that did not land."""
    if not isinstance(patch, dict):
        return None, "config must be an object"
    if not patch:
        return None, "config is empty"
    if len(patch) > MAX_KEYS_PER_WRITE:
        return None, "too many keys (max %d)" % MAX_KEYS_PER_WRITE
    import json
    for k, v in patch.items():
        if k not in KEYS:
            return None, "unknown config key: %s" % str(k)[:40]
        if not KEYS[k](v):
            return None, "invalid value for %s" % k
        if len(json.dumps(v).encode("utf-8")) > MAX_VALUE_BYTES:
            return None, "value for %s exceeds %d bytes" % (k, MAX_VALUE_BYTES)
    return dict(patch), None


def write(user, patch, actor=None, migrate=False):
    """Write one account's own profile rows. Returns (written, skipped, error).

    `migrate=True` is the one-time device->account push (PRD section 4.3): it
    writes ONLY keys the account does not already have, so a device that has
    been rendering with local preferences can hand them up without ever
    resetting a setup the user already made somewhere else. The "only once"
    property is not a client flag and not a marker row - after the first push
    the account HAS the rows, so a second push writes nothing. Derived from the
    state itself, per the no-monkey-patches law."""
    from spine.storage import db, events
    cleaned, err = validate(patch)
    if err:
        return [], [], err
    if migrate and stored(user):
        # PRD 4.3 reads "if the account has NO stored profile" - a profile that
        # was already established anywhere is never partially back-filled from
        # a device, because the device's other values are by definition older
        # than the choice the user made on the account.
        return [], sorted(cleaned), None
    written = db.user_config_put(user, cleaned, only_absent=migrate)
    if written:
        # Audit law: who changed their own view, when. Values are NOT logged -
        # the append-only sink is world-readable to auditors and a profile is
        # the user's, not the workspace's; the KEYS are what an access review
        # needs. `user` and `actor` are the same by construction here (the
        # route is self-scoped) and both are recorded so that stays checkable.
        events.emit("user_config", "-", op="write", user=user,
                    actor=actor or user, keys=sorted(written),
                    migrate=bool(migrate))
    return sorted(written), sorted(set(cleaned) - set(written)), None


def rename_block_reason(name):
    """None if renaming account `name` is safe, else the reason to refuse.

    THE GUARD for the decision in this module's docstring. No rename exists in
    auth.py today; this is here so the one that gets written cannot quietly
    orphan a profile - it must call this and surface the refusal."""
    from spine.storage import db
    n = len(db.user_config_get(name))
    if not n:
        return None
    return ("%s holds %d saved profile setting(s), which key on the account "
            "name - renaming would orphan them. Delete the account or leave "
            "the name as it is; a name is an identity here, not a label."
            % (name, n))
