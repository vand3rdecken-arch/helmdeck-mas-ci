# -*- coding: utf-8 -*-
"""Real auth, zero infra. Users live in users.json (never in git):
  {name, pw: "pbkdf2$<iters>$<salt>$<hash>", role: owner|operator|client,
   tokens: [{label, token, created}], created}

Humans log in with name+password -> server-side session (sessions.json,
HttpOnly cookie, 30-day expiry, sliding). Devices (glasses, APK, scripts) get
per-user API TOKENS issued and revoked from the Users panel - a token
authenticates AS that user with that user's role. First run: no users ->
the app shows a create-owner setup screen (POST /auth/setup, only works while
the user table is empty)."""
import hashlib, hmac, json, os, secrets, threading, time

from daemon.paths import DAEMON_ROOT as ROOT
USERS = os.path.join(ROOT, "users.json")
SESS = os.path.join(ROOT, "sessions.json")
SESSION_TTL = 30 * 86400
ROLES = ("owner", "operator", "client")

# -- role model ------------------------------------------------------------
# owner:    unrestricted - the only role that may touch identity (this
#           module), settings, policy, machine-capability grants and relay
#           pairing. System-wide blast radius stays owner-only, always.
# operator: trusted day-to-day admin for card lifecycle - move/delete/
#           archive, fast-track, set_driver, resolve_blocker/conflict, sign.
#           Everything a card can do to itself or the board, nothing that
#           reconfigures who else can do it.
# client:   file + comment on their OWN card only (new/steer/answer/cancel/
#           presence) - never a structural action on any card.
#
# `chat_admin_roles()` is the ONE place that answers "which roles may take a
# structural action on a card" - both the chat verb dispatcher
# (cells/copilot/copilot_actions.py) and the equivalent REST routes
# (cells/engineer/routes_track_actions.py, routes_tracks.py) call this
# instead of re-deriving their own role floor, so tightening
# policy.chat_admin_roles actually binds every path to the action, not just
# the chat one.
def chat_admin_roles():
    from spine.storage import events
    return (events.settings().get("policy") or {}).get(
        "chat_admin_roles", ["owner", "operator"])


def is_admin(user):
    return bool(user) and user.get("role") in chat_admin_roles()


def owns_card(user, track):
    """May `user` see/act on THIS card? True unconditionally for owner and
    operator - a client is the only role a card can be private FROM.

    This is the check three GET routes shipped without
    (spine/http/routes/routes_runs.py's screen recording + action log,
    routes_sign.py's signature metadata, routes_system.py's /history) -
    each one hand-rolled its own `user["role"]=="client" and t.get("client")
    != user["name"]` instead of calling one function, and the three misses
    were exactly the routes nobody thought to copy the pattern into.
    cells/engineer/routes_tracks.py and routes_track_actions.py now call
    this too, so there is exactly one place the ownership rule lives -
    a new route gets it right by construction instead of by remembering to
    paste four lines correctly.

    Takes the track dict directly rather than an id: every call site has
    already looked the card up (to 404 on a missing one, to act on it), so
    a second internal lookup here would just be a second place that lookup
    could drift from the caller's."""
    return user.get("role") != "client" or bool(track) and track.get("client") == user.get("name")

# -- brute-force lockout ---------------------------------------------------
# There was no limit of ANY kind on password attempts: the relay exposes the
# login to the internet and a guesser could run flat out forever. The audit
# events added alongside this are what make a limit possible at all - before
# them a failed attempt left no trace to count.
#
# State is in memory on purpose. Counting failures into users.json would write
# to a secrets file on every wrong password, which is both a disk-thrash and an
# invitation to corrupt it; a daemon restart clearing the counters is
# acceptable, because restarting the daemon is not something an attacker can do
# from outside.
#
# The trade-off, stated rather than hidden: a lockout is keyed on the USERNAME,
# so someone who knows the owner's name can lock him out for LOCK_FOR seconds
# by failing five times. That is the standard shape of this control and the
# reason the window is minutes and not hours. The alternative - keying on IP -
# is worthless here, because everything arrives through the relay wearing the
# same address.
LOCK_AFTER = 5           # failures within LOCK_WINDOW before the door shuts
LOCK_WINDOW = 15 * 60    # sliding window the failures are counted in
LOCK_FOR = 15 * 60       # how long it stays shut after that
_fails = {}              # name -> [monotonic timestamps of recent failures]
_fails_lock = threading.Lock()


def _locked_until(name):
    """Seconds remaining on this name's lockout, or 0. Prunes as it goes."""
    now = time.monotonic()
    with _fails_lock:
        hits = [t for t in _fails.get(name, []) if now - t < LOCK_WINDOW]
        if hits:
            _fails[name] = hits
        else:
            _fails.pop(name, None)
        if len(hits) < LOCK_AFTER:
            return 0
        return max(0, int(LOCK_FOR - (now - hits[-1])))


def _note_failure(name):
    with _fails_lock:
        now = time.monotonic()
        hits = [t for t in _fails.get(name, []) if now - t < LOCK_WINDOW]
        hits.append(now)
        _fails[name] = hits
        return len(hits)


def _clear_failures(name):
    with _fails_lock:
        _fails.pop(name, None)

def _load(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        return []

def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

# -- audit ---------------------------------------------------------------

def _audit(op, actor, subject, **extra):
    """Append an identity event to the append-only sink.

    This module imported `events` NOWHERE before: creating and deleting users,
    changing a password or a role, issuing and revoking device tokens, and
    every single login - successful or not - left no trace at all. The failed
    login is the one that hurts most: it was a silent `return None`, so there
    was no record to rate-limit or lock out on, and no way to see an attempt.

    Deliberately NOT recorded: passwords, password hashes, session ids and full
    token values. A token shows up as its label plus the last four characters -
    enough to point at one row in the Users panel, useless as a credential.

    UTC timestamp: events.emit() itself now stamps `at_utc` on every event
    (phase D) - it used to exist only here, computed by hand, because an audit
    timestamp that depends on the host timezone cannot be correlated across
    machines and goes ambiguous twice a year at the DST fold. Identity events
    were the first to get a real one; now nothing has to ask for it.

    Best-effort, like policy._mirror: auditing must not be the reason a login
    fails. That is the right trade today and the WRONG one under GxP, where a
    lost audit record has to fail the operation. Phase B territory, noted here
    so it is a decision and not an oversight.
    """
    try:
        from spine.storage import events
        events.emit("auth", "-", op=op, actor=actor or subject, subject=subject,
                    **extra)
    except Exception:
        pass


def _tail(token):
    """A token reduced to something identifiable but unusable."""
    return ("..." + token[-4:]) if token and len(token) > 4 else "?"

# -- device tokens at rest -------------------------------------------------
# Tokens used to sit in users.json in the CLEAR, and GET /users shipped them in
# full to the owner panel on every load. Anyone who could read the file - or
# capture one of those responses - held every device's access.
#
# They are hashed now. SHA-256 and deliberately NOT pbkdf2: this is not a
# password. A token is 24 bytes from secrets.token_urlsafe, so there is no
# low-entropy guess to slow down, and resolve() runs on EVERY authenticated
# request - 200k rounds per candidate token there would be a self-inflicted
# denial of service.
#
# Stored per token: `th` (the hash, what auth compares against), `id` (a short
# stable handle so the panel can revoke without ever holding the secret) and
# `tail` (the last 6 characters, purely so a human can tell two devices apart).
# 36 bits of a 192-bit token is not a credential.

def _token_hash(token):
    return hashlib.sha256((token or "").encode()).hexdigest()


def _token_record(token, label):
    th = _token_hash(token)
    return {"label": label or "device", "th": th, "id": th[:12],
            "tail": token[-6:], "created": time.strftime("%Y-%m-%d %H:%M:%S")}


def _migrate_tokens(users):
    """Fold any surviving plaintext token into its hash, once, in place.

    Self-healing on read rather than a boot step: a tool process that never
    runs the daemon's startup path still must not resurrect the cleartext.
    Returns True when something changed and the file needs writing."""
    touched = False
    for u in users:
        for t in u.get("tokens", []):
            if "token" in t and "th" not in t:
                raw = t.pop("token")
                t["th"] = _token_hash(raw)
                t["id"] = t["th"][:12]
                t.setdefault("tail", raw[-6:])
                touched = True
    return touched

# -- passwords -----------------------------------------------------------

def _hash_pw(password, salt=None, iters=200_000):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iters)
    return "pbkdf2$%d$%s$%s" % (iters, salt, h.hex())

def _check_pw(password, stored):
    try:
        _, iters, salt, want = stored.split("$")
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(h.hex(), want)
    except Exception:
        return False

# -- users ---------------------------------------------------------------

def list_users():
    users = _load(USERS)
    if _migrate_tokens(users):
        _save(USERS, users)
        _audit("token.migrate", "system", "-",
               note="plaintext device tokens folded into hashes")
    return users

def get_user(name):
    for u in list_users():
        if u["name"] == name:
            return u
    return None

def create_user(name, password, role, actor=None):
    if role not in ROLES:
        raise ValueError("bad role")
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("name must be alphanumeric (-/_ ok)")
    if len(password) < 8:
        raise ValueError("password: 8 chars minimum")
    users = list_users()
    if any(u["name"] == name for u in users):
        raise ValueError("user exists")
    users.append({"name": name, "pw": _hash_pw(password), "role": role,
                  "tokens": [], "created": time.strftime("%Y-%m-%d %H:%M:%S")})
    _save(USERS, users)
    _audit("user.create", actor, name, role=role, first_user=(len(users) == 1))
    return {"name": name, "role": role}

def delete_user(name, actor=None):
    users = list_users()
    if len([u for u in users if u["role"] == "owner"]) == 1 \
       and any(u["name"] == name and u["role"] == "owner" for u in users):
        raise ValueError("cannot delete the last owner")
    gone = next((u for u in users if u["name"] == name), None)
    _save(USERS, [u for u in users if u["name"] != name])
    # kill their sessions
    sess = _load(SESS)
    _save(SESS, [s for s in sess if s["user"] != name])
    _audit("user.delete", actor, name,
           role=(gone or {}).get("role"),
           tokens_killed=len((gone or {}).get("tokens") or []),
           sessions_killed=len([s for s in sess if s["user"] == name]),
           existed=gone is not None)

def set_password(name, password, actor=None):
    if len(password) < 8:
        raise ValueError("password: 8 chars minimum")
    users = list_users()
    for u in users:
        if u["name"] == name:
            u["pw"] = _hash_pw(password)
            _save(USERS, users)
            _audit("user.password", actor, name, self_service=(actor == name))
            return
    raise ValueError("no such user")

def set_role(name, role, actor=None):
    if role not in ROLES:
        raise ValueError("bad role")
    users = list_users()
    for u in users:
        if u["name"] == name:
            was = u["role"]                 # BEFORE value: an audit trail that
            u["role"] = role                # only records the new one cannot
            _save(USERS, users)             # answer "what was changed"
            _audit("user.role", actor, name, frm=was, to=role)
            return
    raise ValueError("no such user")

# -- device/API tokens ---------------------------------------------------

def issue_token(name, label, actor=None):
    """Mint a device token. The plaintext is returned HERE AND NOWHERE ELSE -
    only its hash is kept, so a lost token is re-issued, never recovered."""
    users = list_users()
    for u in users:
        if u["name"] == name:
            tok = "sdk_" + secrets.token_urlsafe(24)
            rec = _token_record(tok, label)
            u.setdefault("tokens", []).append(rec)
            _save(USERS, users)
            _audit("token.issue", actor, name,
                   label=rec["label"], tail=_tail(tok), token_id=rec["id"])
            return tok
    raise ValueError("no such user")

def revoke_token(name, ident, actor=None):
    """Revoke by token id (what the owner panel has) or by the full token
    (what a script that still holds one has). Never needs the cleartext."""
    users = list_users()
    th = _token_hash(ident)
    for u in users:
        if u["name"] == name:
            held = u.get("tokens", [])
            gone = [t for t in held if t.get("id") == ident or t.get("th") == th]
            keep = [t for t in held if t not in gone]
            u["tokens"] = keep
            _save(USERS, users)
            # log the MATCHED RECORD's id, never `ident` - a caller may pass the
            # full token here (a script that still holds one), and echoing that
            # into the append-only audit would write the secret down forever.
            # Caught by test_auth_audit's "no secret in the log" assertion.
            _audit("token.revoke", actor, name, removed=len(gone),
                   token_id=(gone[0].get("id") if gone else None),
                   by=("id" if any(t.get("id") == ident for t in gone) else "token"))
            return

# -- sessions ------------------------------------------------------------

def login(name, password):
    """name+password -> session id for the cookie, or None.

    Returns None for every kind of refusal - unknown user, wrong password and
    locked out are indistinguishable to the caller ON PURPOSE. Telling a
    guesser "that account exists but you are locked out" hands them a working
    account-enumeration oracle. The audit trail keeps them apart; the wire
    does not."""
    left = _locked_until(name)
    if left:
        _audit("login.blocked", name, name, locked_for_s=left)
        return None
    u = get_user(name)
    if not u:
        # Both misses are recorded, and they are recorded DIFFERENTLY. "no such
        # user" repeated across many names is someone enumerating accounts;
        # "bad password" repeated against one name is someone guessing it. A
        # single generic failure line cannot tell those apart. The response to
        # the caller stays identical either way - only the log distinguishes.
        n = _note_failure(name)
        _audit("login.failed", name, name, reason="no_such_user",
               fails=n, locks_out=(n >= LOCK_AFTER))
        return None
    if not _check_pw(password, u.get("pw", "")):
        n = _note_failure(name)
        _audit("login.failed", name, name, reason="bad_password", role=u["role"],
               fails=n, locks_out=(n >= LOCK_AFTER))
        return None
    _clear_failures(name)
    sid = secrets.token_urlsafe(32)
    sess = [s for s in _load(SESS) if s["expires"] > time.time()]
    sess.append({"sid": sid, "user": name, "expires": time.time() + SESSION_TTL})
    _save(SESS, sess)
    _audit("login", name, name, role=u["role"])
    return sid

def verify_password(name, password):
    """Prove it is still this person, WITHOUT minting anything.

    Re-authentication at a signing step needs exactly this and nothing else.
    login() is the wrong primitive for it: it creates a session, and through
    routes_auth it also mints a permanent device token on every call - so using
    it as a password check would pile up credentials every time someone signs.

    The lockout applies here too. A signing endpoint that skipped it would be a
    brute-force oracle with a nicer name, and would be the obvious way in once
    login is rate-limited.
    """
    if _locked_until(name):
        _audit("verify.blocked", name, name)
        return False
    u = get_user(name)
    if not u:
        _note_failure(name)
        _audit("verify.failed", name, name, reason="no_such_user")
        return False
    if not _check_pw(password, u.get("pw", "")):
        n = _note_failure(name)
        _audit("verify.failed", name, name, reason="bad_password",
               fails=n, locks_out=(n >= LOCK_AFTER))
        return False
    _clear_failures(name)
    return True


def logout(sid):
    sess = _load(SESS)
    who = next((s["user"] for s in sess if s["sid"] == sid), None)
    _save(SESS, [s for s in sess if s["sid"] != sid])
    _audit("logout", who, who, matched=who is not None)

def resolve(sid=None, token=None):
    """Session cookie or bearer token -> the user dict (public part) or None."""
    name = None
    if sid:
        now = time.time()
        for s in _load(SESS):
            if s["sid"] == sid and s["expires"] > now:
                name = s["user"]
                break
    if not name and token:
        th = _token_hash(token)
        for u in list_users():
            for t in u.get("tokens", []):
                if hmac.compare_digest(t.get("th", ""), th):
                    name = u["name"]
    if not name:
        return None
    u = get_user(name)
    return {"name": u["name"], "role": u["role"]} if u else None

def migrate_legacy(settings_users):
    """One-time: old settings.json token-users become real users with that
    token attached as a device token (they set a password via the owner)."""
    if list_users() or not settings_users:
        return False
    users = []
    for su in settings_users:
        users.append({"name": su["name"], "pw": _hash_pw(secrets.token_urlsafe(18)),
                      "role": su.get("role", "operator"),
                      "tokens": [_token_record(su["token"], "migrated")],
                      "created": time.strftime("%Y-%m-%d %H:%M:%S")})
    _save(USERS, users)
    return True
