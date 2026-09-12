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
USERS = os.path.join(ROOT, "users.json")            # accounts stay at root - credentials
# Login sessions are the `auth_sessions` table (state-into-db phase G; ledger
# step 10 imported state/sessions.json). The list file was read on EVERY
# request with a retry loop around Windows' os.replace window - a keyed row
# needs neither the rewrite nor the retry.
SESSION_TTL = 30 * 86400
ROLES = ("owner", "operator", "client", "quality", "auditor")

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
# quality:  (ops/docs/backlog/rbac-gxp card 3) the SoD approver counterpart -
#           may accept/sign a card, may NOT file/dispatch one (tracks_new_post
#           refuses this role explicitly). With policy.sod_accept on, a
#           quality actor additionally cannot accept a card THEY dispatched
#           (cells/engineer/lanemachine.py's SoD check, keyed on the card's
#           own `dispatched_by` - see dispatch.py's new_track).
# auditor:  read-only, everywhere - zero write capabilities in the permission
#           matrix (spine/auth/permissions.py), by construction rather than
#           by remembering to exclude it from each write path.
#
# `chat_admin_roles()` is the ONE place that answers "which roles may take a
# structural action on a card" - both the chat verb dispatcher
# (cells/copilot/copilot_actions.py) and the equivalent REST routes
# (cells/engineer/routes_track_actions.py, routes_tracks.py) call this
# instead of re-deriving their own role floor, so tightening the underlying
# capability actually binds every path to the action, not just the chat one.
#
# Card 2's deferred promise, paid: this used to read settings.json's
# policy.chat_admin_roles - a THIRD storage location independent of both
# policy_live.json's "policies" and the new "permissions" matrix (spine/auth/
# permissions.py). Now it derives from that SAME matrix (capability
# cards.admin), so there is exactly one place that answers "who may
# structurally touch a card" instead of two that could silently drift apart.
# settings.json's old policy.chat_admin_roles key is no longer read here -
# still technically writable via the chat "configure" verb (policy.* is in
# ALLOWED_CONFIG), but inert; changing WHO is admin now goes through
# permissions.set_role_caps("<role>", [...,"cards.admin"], actor).
def chat_admin_roles():
    from spine.auth import permissions
    return [r for r in ROLES if permissions.can({"role": r}, "cards.admin")]


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
    could drift from the caller's.

    The onboarding example card (accounts-boards-prd phase 3) has no
    `client` - it belongs to nobody, so the ownership match above would hide
    it from every client-role account, exactly the "empty screen" the PRD's
    4.2 setup flow exists to prevent. It is everyone's guide, so it is
    visible unconditionally, the same way owner/operator already are."""
    return (user.get("role") != "client" or bool(track) and
            (track.get("example") or track.get("client") == user.get("name")))

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
    # os.replace in _save briefly exclusive-locks the target on Windows; a
    # concurrent reader then gets PermissionError (winerror 5/32), which used
    # to 500 every request in that instant (measured 2026-09-10 00:00: five
    # hits, each one a dropped phone message). Retry through the window - it
    # is a few ms long - instead of treating it as a real ACL problem.
    for attempt in range(5):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:
            return []
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))

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


def _token_record(token, label, expires_days=None, device=None,
                  unused_days=None):
    th = _token_hash(token)
    rec = {"label": label or "device", "th": th, "id": th[:12],
           "tail": token[-6:], "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    if device:
        rec["device"] = device
    if expires_days:
        rec["expires"] = time.strftime("%Y-%m-%d",
            time.localtime(time.time() + expires_days * 86400))
    if unused_days:
        rec["unused_days"] = int(unused_days)
    return rec


# How long a token that has NEVER been used stays redeemable (debt
# pair-token-no-ttl). A credential nobody ever presented is either a leak or
# litter; either way it should not still be a key a month later. Real devices
# claim within seconds - resolve() writes `last_used` on the very first
# authenticated call - so this window is only ever spent by tokens that were
# minted and abandoned.
UNUSED_TTL_DAYS = 30
# Pairing is the tight case the debt names: the QR/link window is 15 minutes,
# and the token inside that payload used to outlive it forever. One day is the
# slack for "the owner generated the code and the phone gets set up this
# evening", not for "someone finds the screenshot next month".
PAIR_UNUSED_TTL_DAYS = 1


def _token_expired(t):
    """DERIVED on every resolve, never a stored flag: a hard expiry date, or a
    token that was issued with a claim window and never presented inside it.

    Records written before this existed carry neither field and are therefore
    unaffected - nothing already in a user's hands expires retroactively."""
    exp = t.get("expires")
    if exp and exp < time.strftime("%Y-%m-%d"):
        return True
    unused = t.get("unused_days")
    if unused and not t.get("last_used"):
        try:
            born = time.mktime(time.strptime(
                (t.get("created") or "")[:19], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            return False        # unparseable stamp: do not lock a device out
        return time.time() - born > int(unused) * 86400
    return False


STALE_DAYS = 90  # card 5 debt (rbac-audit-hardening-partial): access-review
                 # signal, not an enforcement - a stale token still works
                 # until someone revokes it, this only flags it for review.


def _token_stale(t):
    """Unused (or never used) for STALE_DAYS - review signal for the Users
    panel, computed live from created/last_used, never a stored flag."""
    basis = t.get("last_used") or t.get("created")
    if not basis:
        return False
    try:
        age_s = time.time() - time.mktime(time.strptime(basis[:19], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return False
    return age_s > STALE_DAYS * 86400


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
    # kill their sessions (count them first - the audit row below says how many)
    from spine.storage import db
    sessions_killed = sum(1 for s in db.auth_sessions_all() if s["user"] == name)
    db.auth_sessions_drop_account(name)
    # ...and their saved profile. The rows key on the NAME (accounts-boards-prd
    # phase 1, spine/storage/userconfig.py), so leaving them behind means a
    # LATER account created with the same name silently inherits a stranger's
    # language and appearance - the same class of bug as a resurrected session.
    # Best-effort: a db that will not open must not block removing an account.
    config_dropped = 0
    try:
        from spine.storage import db
        config_dropped = db.user_config_drop_user(name)
    except Exception:
        pass
    # ...and their personal boards, for exactly the same reason: `boards.owner`
    # is the account NAME too (accounts-boards-prd phase 2). The shared default
    # board has owner="" and is never touched here - it outlives its creator,
    # which is what lets an owner be replaced without the workspace losing the
    # board every account lands on.
    boards_dropped = 0
    try:
        from spine.storage import db
        boards_dropped = db.boards_drop_user(name)
    except Exception:
        pass
    _audit("user.delete", actor, name,
           role=(gone or {}).get("role"),
           tokens_killed=len((gone or {}).get("tokens") or []),
           sessions_killed=sessions_killed,
           config_rows_dropped=config_dropped,
           boards_dropped=boards_dropped,
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

def issue_token(name, label, actor=None, expires_days=None, device=None,
                unused_days=UNUSED_TTL_DAYS):
    """Mint a device token. The plaintext is returned HERE AND NOWHERE ELSE -
    only its hash is kept, so a lost token is re-issued, never recovered.
    `expires_days` is optional (card 5 debt) - None keeps today's behaviour
    (never expires); resolve() refuses a token past its `expires` date.
    `unused_days` is the claim window for a token that is never presented
    (see _token_expired) - pass None for a credential that must stay valid
    even if it sits unused.

    `device` is a stable per-installation id the CALLER supplies, and it makes
    the token list a DEVICE list: one live credential per device, replacing
    that device's previous one instead of stacking beside it. This is the fix
    for the panel's 123-line raw token list - /auth/login minted a fresh
    "web-login" token on EVERY sign-in, so a phone that reconnects weekly grew
    a row a week, all of them live, none of them distinguishable. Grouping is
    recorded AT ISSUE TIME by the only party that knows which device this is
    (NO-MONKEY-PATCH law) - never reconstructed later by pattern-matching
    labels, which is what "web-login #7" would have forced."""
    users = list_users()
    for u in users:
        if u["name"] == name:
            tok = "sdk_" + secrets.token_urlsafe(24)
            rec = _token_record(tok, label, expires_days=expires_days,
                                device=device, unused_days=unused_days)
            held = u.setdefault("tokens", [])
            replaced = 0
            if device:
                replaced = len([t for t in held if t.get("device") == device])
                held[:] = [t for t in held if t.get("device") != device]
            held.append(rec)
            _save(USERS, users)
            _audit("token.issue", actor, name,
                   label=rec["label"], tail=_tail(tok), token_id=rec["id"],
                   expires=rec.get("expires"), device=device,
                   replaced=replaced)
            return tok
    raise ValueError("no such user")


def sweep_tokens(actor="system"):
    """Garbage-collect tokens _token_expired() already refuses. Housekeeping
    ONLY: an expired token stops authenticating the moment it expires, whether
    or not this ever runs - this just stops the panel filling with corpses.
    Returns how many were dropped."""
    users = list_users()
    dropped = 0
    for u in users:
        held = u.get("tokens") or []
        keep = [t for t in held if not _token_expired(t)]
        if len(keep) != len(held):
            dropped += len(held) - len(keep)
            u["tokens"] = keep
    if dropped:
        _save(USERS, users)
        _audit("token.sweep", actor, "-", removed=dropped)
    return dropped


def last_active(u):
    """When this account was last seen, derived from its devices' own
    `last_used` stamps - the panel's "last activity" column. None for an
    account that has never presented a token (web session only)."""
    stamps = [t.get("last_used") for t in (u.get("tokens") or []) if t.get("last_used")]
    return max(stamps) if stamps else None


def _touch_token(name, token_id):
    """Best-effort, throttled to once/day: resolve() runs on EVERY
    authenticated request, so this must not rewrite users.json every time -
    only when the stored last_used is missing or already a day stale."""
    today = time.strftime("%Y-%m-%d")
    try:
        users = _load(USERS)
        for u in users:
            if u["name"] != name:
                continue
            for t in u.get("tokens", []):
                if t.get("id") == token_id:
                    if (t.get("last_used") or "")[:10] == today:
                        return  # already touched today, skip the write
                    t["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    _save(USERS, users)
                    return
    except Exception:
        pass  # never let a bookkeeping write fail an actual auth check

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
    from spine.storage import db
    db.auth_session_put(sid, name, time.time() + SESSION_TTL)
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
    from spine.storage import db
    who = db.auth_session_delete(sid)
    _audit("logout", who, who, matched=who is not None)

def resolve(sid=None, token=None):
    """Session cookie or bearer token -> the user dict (public part) or None."""
    name = None
    if sid:
        from spine.storage import db
        hit = db.auth_session_get(sid)
        if hit and hit[1] > time.time():
            name = hit[0]
    if not name and token:
        th = _token_hash(token)
        for u in list_users():
            for t in u.get("tokens", []):
                if hmac.compare_digest(t.get("th", ""), th):
                    if _token_expired(t):
                        continue  # expired: same as not matching at all
                    name = u["name"]
                    _touch_token(u["name"], t["id"])
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
