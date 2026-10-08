# -*- coding: utf-8 -*-
"""The ACCOUNT's provider keys (DeepSeek, Anthropic, ...): one row per
(account, provider), encrypted at rest, entered in the UI.

home: its OWN table `user_secret` (ledger migration 20), because
  - not `user_config`: that table is a closed whitelist of pure VIEW prefs any
    role may write (userconfig.py), and /harness/export hands every row of it
    out as `user_overlays`;
  - not workspace settings (settings.json / workspace_config): workspace-wide,
    not per account, plaintext on disk, and exported unmasked by default.
The shape is user_config's own (rows key on the account NAME - see
userconfig.py for why a rename is blocked rather than cascaded), plus the three
things a secret needs that a preference does not:

  - ENCRYPTION AT REST. daemon/backups/ and the checkpoints copy helmdeck.db, so
    a plaintext column would put every key into every backup. Windows DPAPI
    (CryptProtectData, current-user scope, via ctypes - no dependency): the
    blob only opens as the Windows account the daemon runs under. The row's
    (account, provider) is mixed in as DPAPI entropy, so a ciphertext copied
    onto another account's row decrypts to nothing. Where DPAPI does not exist
    the store REFUSES to save: a secret is never written as plaintext
    ("no key" is a visible state, "a key in the clear" is the bug).
  - NEVER RETURNED. status() answers set/hint/last-test, never the value. The
    value leaves this module only through env_for(), for one engine spawn.
  - NEVER EXPORTED. Nothing in routes_settings reads this table, and
    test_user_secrets asserts the export document carries no row of it.

Self-scoped like PUT /me/config: the account written to is the session's, never
the body's. Roles: the work these keys pay for runs on the owner's machine, so
only owner and operator may store one (a `client` files cards, it cannot start
an engine); and there is NO fallback to anyone else's key - an account without
a key simply has no such provider.
"""
import base64
import datetime
import json
import re
import sys
import time

# provider id -> the environment variable the OpenCode/OMP engines read it
# from. A CLOSED set, in code: adding one is a deliberate act with a name, a
# label and (verified against the CLI) the variable that connects it.
PROVIDERS = {
    "deepseek":   {"label": "DeepSeek",   "env": "DEEPSEEK_API_KEY"},
    "anthropic":  {"label": "Anthropic",  "env": "ANTHROPIC_API_KEY"},
    "openai":     {"label": "OpenAI",     "env": "OPENAI_API_KEY"},
    "openrouter": {"label": "OpenRouter", "env": "OPENROUTER_API_KEY"},
    "opencode":   {"label": "OpenCode Zen", "env": "OPENCODE_API_KEY"},
}
ROLES = ("owner", "operator")
RUNNING_STALE_S = 150      # a test "running" longer than this is read as interrupted (the daemon died mid-test)
MIN_LEN, MAX_LEN = 8, 512
_VALUE_RE = re.compile(r"[!-~]+")   # printable ASCII; used with fullmatch - `$` would pass a trailing newline


class SecretStoreUnavailable(RuntimeError):
    """No at-rest encryption on this platform - the store refuses to save."""


# -- DPAPI (ctypes) ------------------------------------------------------------

def available():
    return sys.platform == "win32"


def _blob(data):
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf, DATA_BLOB


def _crypt(data, entropy, protect):
    import ctypes
    if not available():
        raise SecretStoreUnavailable("no at-rest encryption on this platform (Windows DPAPI only)")
    inb, keep1, B = _blob(data)
    ent, keep2, _ = _blob(entropy)
    out = B()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inb), None, ctypes.byref(ent), None, None, 0x01, ctypes.byref(out))  # UI_FORBIDDEN
    if not ok:
        raise ValueError("DPAPI %s failed (%d)" % ("encrypt" if protect else "decrypt", ctypes.GetLastError()))
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _entropy(user, provider):
    return ("helmdeck:user_secret:%s:%s" % (user, provider)).encode("utf-8")


def encrypt(user, provider, value):
    return base64.b64encode(_crypt(value.encode("utf-8"), _entropy(user, provider), True)).decode("ascii")


def decrypt(user, provider, blob):
    return _crypt(base64.b64decode(blob), _entropy(user, provider), False).decode("utf-8")


# -- rows ---------------------------------------------------------------------

def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def validate(provider, value):
    """None if (provider, value) may be stored, else the reason - the one gate
    both the route and the tests go through."""
    if provider not in PROVIDERS:
        return "unknown provider '%s' - choices: %s" % (provider, ", ".join(sorted(PROVIDERS)))
    if not isinstance(value, str):
        return "key must be a string"
    if not (MIN_LEN <= len(value) <= MAX_LEN):
        return "key must be %d-%d characters" % (MIN_LEN, MAX_LEN)
    if not _VALUE_RE.fullmatch(value):
        return "key must be printable ASCII without spaces (a pasted line break is the usual cause)"
    return None


def may_store(role):
    return role in ROLES


def put(user, provider, value):
    """Store (replace) one key. Returns None on success, else the reason. The
    previous test result is dropped: it described a different key."""
    from spine.storage import db
    err = validate(provider, value)
    if err:
        return err
    blob = encrypt(user, provider, value)           # raises SecretStoreUnavailable - no plaintext fallback
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO user_secret(user,provider,value_enc,hint,updated_at,test) "
                  "VALUES(?,?,?,?,?,NULL)", (user, provider, blob, value[-4:], _now()))
    db.bump()
    return None


def delete(user, provider):
    from spine.storage import db
    with db.conn() as c:
        n = c.execute("DELETE FROM user_secret WHERE user=? AND provider=?", (user, provider)).rowcount
    if n:
        db.bump()
    return bool(n)


def drop_user(user):
    """Called from auth.delete_user: the rows key on the NAME, so without this a
    later account of the same name would inherit a stranger's API keys."""
    from spine.storage import db
    with db.conn() as c:
        n = c.execute("DELETE FROM user_secret WHERE user=?", (user,)).rowcount
    return n


def count(user):
    """STORED KEYS of this account (a keyless row only carries a test result)."""
    from spine.storage import db
    return db.conn().execute("SELECT COUNT(*) FROM user_secret WHERE user=? AND value_enc!=''",
                             (user,)).fetchone()[0]


def status(user):
    """What the UI may show: every known provider with set / hint / last test.
    NEVER the value."""
    from spine.storage import db
    rows = {r[0]: r for r in db.conn().execute(
        "SELECT provider,hint,updated_at,test,value_enc!='' FROM user_secret WHERE user=?", (user,)).fetchall()}
    out = []
    for pid, meta in PROVIDERS.items():
        r = rows.get(pid)
        has_key = bool(r and r[4])
        try:
            test = json.loads(r[3]) if r and r[3] else None
        except ValueError:
            test = None
        if test and test.get("status") == "running" and time.time() - test.get("started", 0) > RUNNING_STALE_S:
            # DERIVED at read time, never a stored flag: the thread that would
            # have finished this test died with the daemon
            test = {"ok": False, "status": "error", "reason": "the test was interrupted", "model": "", "ms": 0}
        out.append({"id": pid, "label": meta["label"], "env": meta["env"], "set": has_key,
                    "hint": ("..." + r[1]) if has_key else "", "updated_at": r[2] if has_key else "",
                    "test": test})
    return out


def _write_test(user, provider, result):
    """UPSERT the test JSON. A provider that needs no key (the Zen free tier)
    has no key row - it gets one with value_enc='' that only carries the result;
    set/get/env_for/count all read `value_enc != ''` as "no key"."""
    from spine.storage import db
    with db.conn() as c:
        n = c.execute("UPDATE user_secret SET test=? WHERE user=? AND provider=?",
                      (json.dumps(result), user, provider)).rowcount
        if not n:
            c.execute("INSERT INTO user_secret(user,provider,value_enc,hint,updated_at,test) VALUES(?,?,?,?,?,?)",
                      (user, provider, "", "", _now(), json.dumps(result)))


def mark_running(user, provider):
    """Claim a test for this (account, provider). False if one is already running
    (fresh) - the button is idempotent, a double tap spends one request."""
    from spine.storage import db
    cur = {s["id"]: s for s in status(user)}[provider]["test"]
    if cur and cur.get("status") == "running":
        return False
    _write_test(user, provider, {"ok": False, "status": "running", "reason": "", "model": "", "ms": 0,
                                 "started": time.time()})
    db.bump()
    return True


def record_test(user, provider, result):
    """Remember the outcome of a Test (no secret in it) so the UI shows it
    without re-spending a request. bump(): the app learns of it from the
    daemon's event stream and reloads - no polling."""
    from spine.storage import db
    _write_test(user, provider, dict(result, at=_now()))
    db.bump()


def get(user, provider):
    """The decrypted key, or None. For env_for() and the provider test ONLY."""
    from spine.storage import db
    r = db.conn().execute("SELECT value_enc FROM user_secret WHERE user=? AND provider=?",
                          (user, provider)).fetchone()
    if not r or not r[0]:
        return None
    try:
        return decrypt(user, provider, r[0])
    except (ValueError, SecretStoreUnavailable):
        return None          # a blob that will not open (other machine/account) reads as "no key"


def env_for(user, providers=None):
    """{ENV_VAR: key} for ONE engine spawn, from THIS account's own keys only -
    never another account's, never the owner's as a fallback."""
    out = {}
    for pid in (providers or PROVIDERS):
        v = get(user, pid) if user else None
        if v:
            out[PROVIDERS[pid]["env"]] = v
    return out
