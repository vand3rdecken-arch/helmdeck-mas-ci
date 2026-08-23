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
import hashlib, hmac, json, os, secrets, time

from daemon.paths import DAEMON_ROOT as ROOT
USERS = os.path.join(ROOT, "users.json")
SESS = os.path.join(ROOT, "sessions.json")
SESSION_TTL = 30 * 86400
ROLES = ("owner", "operator", "client")

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

    `at_utc` rides ALONGSIDE the local-time `ts` that events.emit() stamps
    (events.py:176). An audit timestamp that depends on the host timezone
    cannot be correlated across machines and goes ambiguous twice a year at the
    DST fold. Migrating `ts` itself touches every consumer and is phase D; the
    identity events - the ones an auditor reads first - get a real one now.

    Best-effort, like policy._mirror: auditing must not be the reason a login
    fails. That is the right trade today and the WRONG one under GxP, where a
    lost audit record has to fail the operation. Phase B territory, noted here
    so it is a decision and not an oversight.
    """
    try:
        from daemon.spine.storage import events
        events.emit("auth", "-", op=op, actor=actor or subject, subject=subject,
                    at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    **extra)
    except Exception:
        pass


def _tail(token):
    """A token reduced to something identifiable but unusable."""
    return ("..." + token[-4:]) if token and len(token) > 4 else "?"

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
    return _load(USERS)

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
    users = list_users()
    for u in users:
        if u["name"] == name:
            tok = "sdk_" + secrets.token_urlsafe(24)
            u.setdefault("tokens", []).append(
                {"label": label or "device", "token": tok,
                 "created": time.strftime("%Y-%m-%d %H:%M:%S")})
            _save(USERS, users)
            _audit("token.issue", actor, name,
                   label=label or "device", tail=_tail(tok))
            return tok
    raise ValueError("no such user")

def revoke_token(name, token, actor=None):
    users = list_users()
    for u in users:
        if u["name"] == name:
            before = len(u.get("tokens", []))
            u["tokens"] = [t for t in u.get("tokens", []) if t["token"] != token]
            _save(USERS, users)
            _audit("token.revoke", actor, name, tail=_tail(token),
                   removed=before - len(u["tokens"]))
            return

# -- sessions ------------------------------------------------------------

def login(name, password):
    """name+password -> session id for the cookie, or None."""
    u = get_user(name)
    if not u:
        # Both misses are recorded, and they are recorded DIFFERENTLY. "no such
        # user" repeated across many names is someone enumerating accounts;
        # "bad password" repeated against one name is someone guessing it. A
        # single generic failure line cannot tell those apart. The response to
        # the caller stays identical either way - only the log distinguishes.
        _audit("login.failed", name, name, reason="no_such_user")
        return None
    if not _check_pw(password, u.get("pw", "")):
        _audit("login.failed", name, name, reason="bad_password", role=u["role"])
        return None
    sid = secrets.token_urlsafe(32)
    sess = [s for s in _load(SESS) if s["expires"] > time.time()]
    sess.append({"sid": sid, "user": name, "expires": time.time() + SESSION_TTL})
    _save(SESS, sess)
    _audit("login", name, name, role=u["role"])
    return sid

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
        for u in list_users():
            for t in u.get("tokens", []):
                if hmac.compare_digest(t["token"], token):
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
                      "tokens": [{"label": "migrated", "token": su["token"],
                                  "created": time.strftime("%Y-%m-%d %H:%M:%S")}],
                      "created": time.strftime("%Y-%m-%d %H:%M:%S")})
    _save(USERS, users)
    return True
