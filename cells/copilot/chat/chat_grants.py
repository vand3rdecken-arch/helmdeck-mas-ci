# -*- coding: utf-8 -*-
"""Chat consent: an admin may read someone's PRIVATE Henry chat only while that
person has granted it (backlog/team-rooms-member, stage 7).

The default is closed - for everyone, the owner included: /chat/history only
ever returns the caller's own account. This module is the single, audited door
around that rule.

ONE OWNER PER FACT (CLAUDE.md, no monkey patches):
  - a grant is a RECORDED fact (account, grantee, created, expires, revoked) in
    chat_grants, written only by grant()/revoke() from the authenticated
    account's own request.
  - "is it active" is DERIVED at every read from those facts and the clock -
    active() - never a stored open/closed flag.
  - every read made under a grant is its own row (chat_grant_reads) AND an
    event in the append-only audit, so the account can see who read what, when.

WHAT THIS IS NOT. A product rule, not cryptography: whoever runs the daemon can
still open helmdeck.db (debt room-chat-consent-is-policy-not-crypto).
"""
import secrets
import time

from spine.storage import db

MAX_HOURS = 24 * 7
MIN_HOURS = 1


def _emit(kind_op, actor, **fields):
    try:
        from spine.storage import events
        events.emit("chat_grant", "-", op=kind_op, actor=actor, **fields)
    except Exception:                                            # noqa: BLE001
        pass          # the audit mirror must never break the grant itself


def active(g, now=None):
    """DERIVED, never stored: not revoked and not expired."""
    now = time.time() if now is None else now
    return not g.get("revoked") and g["expires"] > now


def grant(account, grantee, hours):
    """`account` lets `grantee` read its private chat for `hours`. The grantee
    must be an existing admin (cards.admin) other than the account itself."""
    from spine.auth import auth
    if grantee == account:
        raise ValueError("you cannot grant yourself")
    u = auth.get_user(grantee)
    if not u or not auth.is_admin(u):
        raise ValueError("%s is not an admin" % grantee)
    hours = int(hours)
    if not MIN_HOURS <= hours <= MAX_HOURS:
        raise ValueError("hours must be between %d and %d" % (MIN_HOURS, MAX_HOURS))
    now = time.time()
    g = {"id": "g" + secrets.token_hex(4), "account": account, "grantee": grantee,
         "created": now, "expires": now + hours * 3600, "revoked": None}
    db.chat_grant_put(g)
    _emit("grant", account, grantee=grantee, hours=hours, grant=g["id"])
    return g


def revoke(account, grant_id):
    """Only the account that gave a grant may withdraw it; effective at once."""
    for g in db.chat_grants_of(account=account):
        if g["id"] == grant_id:
            if not g["revoked"]:
                g["revoked"] = time.time()
                db.chat_grant_put(g)
                _emit("revoke", account, grantee=g["grantee"], grant=grant_id)
            return g
    raise ValueError("unknown grant")


def given(account):
    """Grants this account made, newest first, each with `active` derived now
    and the reads made under it - what the owner of the chat gets to see."""
    reads = {}
    for r in db.chat_grant_reads_of(account):
        reads.setdefault(r["grant_id"], []).append(r)
    out = []
    for g in db.chat_grants_of(account=account):
        out.append(dict(g, active=active(g), reads=reads.get(g["id"], [])))
    return out


def received(reader):
    """The ACTIVE grants naming `reader`: whose chat they may open right now."""
    return [dict(g, active=True) for g in db.chat_grants_of(grantee=reader) if active(g)]


def read(reader, account, limit=200):
    """`reader` opens `account`'s private chat. Allowed ONLY under an active
    grant naming them; the read is recorded (table + audit event) BEFORE the
    entries are returned. Raises PermissionError otherwise - the same answer
    whether the account exists, has a chat or never granted anything."""
    live = [g for g in db.chat_grants_of(account=account, grantee=reader) if active(g)]
    if not live:
        raise PermissionError("no active grant")
    g = live[0]
    entries = db.chat_tail(account, limit)
    db.chat_grant_read_add(g["id"], account, reader, len(entries))
    _emit("read", reader, account=account, grant=g["id"], n=len(entries))
    return {"account": account, "grant": g["id"], "expires": g["expires"], "entries": entries}
