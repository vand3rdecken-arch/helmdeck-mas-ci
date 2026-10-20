# -*- coding: utf-8 -*-
"""External-agent access: an account lets ANOTHER harness (Claude Code, Cursor,
Codex, any MCP client) reach named rooms and cards through /mcp.

home: its OWN table `access_grants` (ledger migration 22), because a grant is
a scoped, expiring credential with an audit trail. Not users.tokens (a device
token authenticates AS the whole account, every room and card), not
chat_grants (account -> named admin, read-only, no bearer token), not
user_config (view prefs, exported).

THE RULE - a grant can never reach further than its issuer:
  - at ISSUE time every scope entry is checked against the issuer's own access
    (room membership; sees_card for read, owns_card for write).
  - at EVERY CALL the same check runs again, live (authorize). Leaving a room,
    losing a card or the account being deleted closes the grant's door at
    once - there is no stored "still allowed" flag to go stale.
  - ACTIVE (not revoked, not expired) is derived from the row and the clock.

SHARING = A ONE-TIME CLAIM CODE, never the token. grant() returns a code
(hdc_...) that goes into the share link; the first claim() mints the token and
burns the code, so a link that leaks later (chat history, link preview) opens
nothing, and the issuer never holds the token at all. Only sha256s are stored.
Calls are rate-limited per grant (allow()). Every call is a row in access_grant_uses AND an event in the
append-only audit.

IDENTITY: the external agent is its OWN principal - agent_name() (the grant's
label) authors its room posts (byKind "agent", on_behalf = issuer) and
agent_actor() ("agent:<grant id>") is the actor in every audit row and steer.
The issuer is who it acts FOR: its reach and its plan share, never its name.
"""
import hashlib
import secrets
import time

from spine.storage import db

PREFIX = "hdm_"
CLAIM_PREFIX = "hdc_"
RATE_WINDOW_S = 60
RATE_CALLS = 60       # any tool call per grant per window
RATE_WRITES = 10      # of those, writes (post/steer/answer) - each can start a paid turn
MAX_HOURS = 24 * 30
MIN_HOURS = 1
MAX_SCOPE = 50
LABEL_MAX = 60
KINDS = ("room", "card")


def _th(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _emit(op, actor, **fields):
    try:
        from spine.storage import events
        events.emit("access_grant", fields.pop("card", "-"), op=op, actor=actor, **fields)
    except Exception:                                            # noqa: BLE001
        pass          # the audit mirror must never break the grant itself


def active(g, now=None):
    """DERIVED, never stored: not revoked and not expired."""
    now = time.time() if now is None else now
    return not g.get("revoked") and g["expires"] > now


def _issuer(g):
    from spine.auth import auth
    u = auth.get_user(g["issuer"])
    return {"name": u["name"], "role": u["role"]} if u else None


def issuer_reaches(user, kind, tid, write):
    """Can `user` (the issuer) ITSELF do this right now? The one check used at
    issue time and at every call."""
    if not user:
        return False
    if kind == "room":
        from cells.copilot.chat import rooms
        return rooms.is_member(tid, user["name"])
    from cells.engineer.cards import sessions
    from spine.auth import auth
    t = sessions.get_track(tid)
    if not t:
        return False
    return auth.owns_card(user, t) if write else auth.sees_card(user, t)


def _clean_scope(user, scope):
    if not isinstance(scope, list) or not scope:
        raise ValueError("scope must be a non-empty list")
    if len(scope) > MAX_SCOPE:
        raise ValueError("at most %d scope entries" % MAX_SCOPE)
    out, seen = [], set()
    for e in scope:
        if not isinstance(e, dict):
            raise ValueError("scope entry must be an object")
        kind, tid = e.get("kind"), str(e.get("id") or "")
        # levels: read < write (post/steer/answer) < code (cards only: submit a
        # patch proposal). code implies write.
        code = kind == "card" and bool(e.get("code"))
        write = bool(e.get("write")) or code
        if kind not in KINDS or not tid:
            raise ValueError("scope entry needs kind room|card and an id")
        if (kind, tid) in seen:
            continue
        seen.add((kind, tid))
        if not issuer_reaches(user, kind, tid, write):
            # same answer for "unknown" and "not yours": no existence oracle
            raise ValueError("you cannot %s %s %s yourself" %
                             ("write" if write else "read", kind, tid))
        out.append({"kind": kind, "id": tid, "write": write, "code": code})
    return out


def public(g):
    """What the issuer sees of a grant: never a hash."""
    return {"id": g["id"], "label": g["label"], "hint": g["hint"], "scope": g["scope"],
            "created": g["created"], "expires": g["expires"], "revoked": g.get("revoked"),
            "active": active(g), "claimed": not g.get("claim_th"),
            "sealed_only": bool(g.get("sealed_only"))}


def grant(user, label, scope, hours, sealed_only=True):
    """Issue a grant. Returns (public view, one-time claim code) - the code
    exists only here; the token is minted later, by whoever claims it."""
    label = (label or "").strip()
    if not label or len(label) > LABEL_MAX:
        raise ValueError("label required (max %d chars)" % LABEL_MAX)
    from spine.auth import auth
    if label.lower() == "henry" or any(u["name"].lower() == label.lower() for u in auth.list_users()):
        # the agent posts under this name: it must never read as a person or Henry
        raise ValueError("label must not be an account name or Henry")
    hours = int(hours)
    if not MIN_HOURS <= hours <= MAX_HOURS:
        raise ValueError("hours must be between %d and %d" % (MIN_HOURS, MAX_HOURS))
    clean = _clean_scope(user, scope)
    code = CLAIM_PREFIX + secrets.token_urlsafe(24)
    now = time.time()
    g = {"id": "ag" + secrets.token_hex(5), "issuer": user["name"], "label": label,
         # placeholder no token hashes to (not hex): unusable until claimed
         "th": "unclaimed:" + secrets.token_hex(16), "hint": "", "scope": clean,
         "created": now, "expires": now + hours * 3600, "revoked": None,
         "claim_th": _th(code), "sealed_only": bool(sealed_only)}
    db.access_grant_put(g)
    _emit("grant", user["name"], grant=g["id"], label=label, hours=hours,
          scope=[("%s:%s%s" % (e["kind"], e["id"], ":w" if e["write"] else "")) for e in clean])
    return public(g), code


class SealedOnly(Exception):
    """The grant exists but answers only end-to-end (sealed) requests."""


def claim(code, sealed=False):
    """Redeem a one-time code for the grant's token. Returns (token, grant) or
    None - for an unknown, used, revoked or expired code alike. A sealed-only
    grant raises SealedOnly on a plain claim WITHOUT burning the code, so the
    person can still redeem it the right way."""
    if not code or not code.startswith(CLAIM_PREFIX):
        return None
    g = db.access_grant_by_claim(_th(code))
    if not g or not active(g):
        return None
    if g.get("sealed_only") and not sealed:
        raise SealedOnly()
    token = PREFIX + secrets.token_urlsafe(32)
    if db.access_grant_redeem(_th(code), _th(token), token[-4:], time.time()) != 1:
        return None                 # lost a race with another claim
    _emit("claim", g["issuer"], grant=g["id"], label=g["label"])
    return token, dict(g, claim_th=None)


_calls = {}       # grant id -> [(ts, write)] - in memory: a restart resets a window, nothing more


def allow(g, write):
    """Sliding-window rate limit per grant. False = refuse this call."""
    now = time.time()
    hist = [h for h in _calls.get(g["id"], []) if now - h[0] < RATE_WINDOW_S]
    if len(hist) >= RATE_CALLS or (write and sum(1 for h in hist if h[1]) >= RATE_WRITES):
        _calls[g["id"]] = hist
        return False
    hist.append((now, bool(write)))
    _calls[g["id"]] = hist
    return True


def revoke(user, gid):
    for g in db.access_grants_of(user["name"]):
        if g["id"] == gid:
            if not g.get("revoked"):
                g["revoked"] = time.time()
                db.access_grant_put(g)
                _emit("revoke", user["name"], grant=gid)
            return public(g)
    raise ValueError("no such grant")


def mine(user):
    out = []
    for g in db.access_grants_of(user["name"]):
        v = public(g)
        v["uses"] = db.access_grant_uses_of(g["id"], limit=20)
        out.append(v)
    return out


def resolve(token):
    """Bearer token -> the ACTIVE grant, or None. Only hdm_ tokens."""
    if not token or not token.startswith(PREFIX):
        return None
    g = db.access_grant_by_th(_th(token))
    return g if g and active(g) else None


def authorize(g, kind, tid, write=False, code=False):
    """May this grant do this NOW? Scope entry + the issuer's live access.
    `code` (submit a patch) needs the entry's code level AND the issuer's
    ownership of the card (write reach)."""
    if not active(g):
        return False
    for e in g["scope"]:
        if e["kind"] == kind and e["id"] == tid:
            if code and not e.get("code"):
                return False
            if (write or code) and not e["write"]:
                return False
            return issuer_reaches(_issuer(g), kind, tid, write or code)
    return False


def record(g, tool, target, ok):
    db.access_grant_use_add(g["id"], tool, target, ok)
    _emit("use", g["issuer"], grant=g["id"], label=g["label"], tool=tool,
          target=target, ok=bool(ok))


def drop_user(name):
    return db.access_grants_drop_user(name)


def agent_name(g):
    return g["label"]


def agent_actor(g):
    """The audit actor of everything the agent does: stable per grant, never
    an account name (so no route can mistake it for a person's own act)."""
    return "agent:%s" % g["id"]


def issuer(g):
    return _issuer(g)
