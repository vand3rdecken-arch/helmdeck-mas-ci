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

def create_user(name, password, role):
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
    return {"name": name, "role": role}

def delete_user(name):
    users = list_users()
    if len([u for u in users if u["role"] == "owner"]) == 1 \
       and any(u["name"] == name and u["role"] == "owner" for u in users):
        raise ValueError("cannot delete the last owner")
    _save(USERS, [u for u in users if u["name"] != name])
    # kill their sessions
    _save(SESS, [s for s in _load(SESS) if s["user"] != name])

def set_password(name, password):
    if len(password) < 8:
        raise ValueError("password: 8 chars minimum")
    users = list_users()
    for u in users:
        if u["name"] == name:
            u["pw"] = _hash_pw(password)
            _save(USERS, users)
            return
    raise ValueError("no such user")

def set_role(name, role):
    if role not in ROLES:
        raise ValueError("bad role")
    users = list_users()
    for u in users:
        if u["name"] == name:
            u["role"] = role
            _save(USERS, users)
            return
    raise ValueError("no such user")

# -- device/API tokens ---------------------------------------------------

def issue_token(name, label):
    users = list_users()
    for u in users:
        if u["name"] == name:
            tok = "sdk_" + secrets.token_urlsafe(24)
            u.setdefault("tokens", []).append(
                {"label": label or "device", "token": tok,
                 "created": time.strftime("%Y-%m-%d %H:%M:%S")})
            _save(USERS, users)
            return tok
    raise ValueError("no such user")

def revoke_token(name, token):
    users = list_users()
    for u in users:
        if u["name"] == name:
            u["tokens"] = [t for t in u.get("tokens", []) if t["token"] != token]
            _save(USERS, users)
            return

# -- sessions ------------------------------------------------------------

def login(name, password):
    """name+password -> session id for the cookie, or None."""
    u = get_user(name)
    if not u or not _check_pw(password, u.get("pw", "")):
        return None
    sid = secrets.token_urlsafe(32)
    sess = [s for s in _load(SESS) if s["expires"] > time.time()]
    sess.append({"sid": sid, "user": name, "expires": time.time() + SESSION_TTL})
    _save(SESS, sess)
    return sid

def logout(sid):
    _save(SESS, [s for s in _load(SESS) if s["sid"] != sid])

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
