# -*- coding: utf-8 -*-
"""The companion registry - the daemon half of the glasses SENSING layer.

Phase 1 of the native companion (docs/glasses-reference.md §11). It exists
because of one platform fact that is measured, not assumed: **a native app can
never draw a pixel on the glasses lens** - only the registered webapp renders
there (`native-companion-plan.md:57`, `AGENTS.md:263-270`). So the companion is
not a second UI. It is a sensing layer: it captures what the webview
structurally cannot (mic, camera, background execution, phone notifications)
and hands it to THIS backend, which the webapp on the lens then displays.

Three things live here, each one lifted from a decision the reference project
already paid for:

1. VALET TICKETS, not a second shared secret (§2.1). Every enrolled device holds
   its OWN revocable credential. Only `sha256hex(token)` is ever stored; the
   token itself is returned exactly once, at mint time, and is unrecoverable
   afterwards. This is deliberately NOT `auth.issue_token()`: an auth token
   authenticates AS a user and carries that user's whole role, so a phone in a
   pocket would hold owner powers. A ticket carries SCOPES instead - a mic
   device cannot read the board, and revoking it touches nothing else.

2. BACKEND-DRIVEN CONFIG (§2.4). Every toggle and interval the companion obeys
   comes from here, because "a native app you must rebuild to retune is a native
   app you will stop retuning" (`android/README.md:62-63`). Note the default
   poll interval: 60s, never faster. The reference project shipped 10s, called
   it "near-planning", and wrote the rule down - *"never ship a fast poll"*
   (§2.5). Push is the live path; this is the safety net.

3. A COMMAND QUEUE CONSUMED ON PROOF. §2.4's `_cmd` row is "consumed after
   execution so it can't re-fire". The word after matters, and it is also the
   repo's own NO-MONKEY-PATCHES law: load-bearing state is folded in at EVENT
   TIME from the runtime's own signal, at exactly ONE owner, never assumed from
   a stored flag. So `pending()` is a pure read that consumes nothing - a device
   that fetches and then dies gets the command again - and `ack()` is the single
   mutation point, moving a command out of pending only on the device's report
   that it actually ran. Consuming on read would silently drop a command every
   time a phone lost signal mid-fetch, and would look exactly like a bug in the
   sensor.

FAIL-SAFE (§2.1, copied deliberately): a missing or corrupt store degrades to
"no devices enrolled" - the companion surface answers 403 and the owner can
re-pair. It never raises into the daemon and never locks the owner out, because
owner auth does not live here.

The store (companion.json) holds live credentials-by-hash and is git-ignored
with the other secrets. Writes are atomic (temp + os.replace) - AGENTS.md:413.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "companion.json")

# The daemon is a ThreadingHTTPServer, so "a device polls while the owner queues
# a command" is the NORMAL case, not a race to hand-wave. Every public mutation
# below is a read-modify-write of the whole file, which without this lock loses
# updates - measured, not feared: 8 threads queueing 40 commands landed 5 of
# them, and on Windows the shared .tmp name made 7 of the 8 die outright with
# PermissionError (two writers in os.replace on the same path).
#
# RLock, not Lock: save_config() ends by calling config(), and ack()/pending()
# share helpers, so the critical sections nest by design.
#
# Why a lock is safe here where [turn-locks] deadlocked: that one wrapped an
# UNBOUNDED read of a child process's stdout. These sections are pure in-memory
# work plus one small bounded file write - nothing inside can block forever.
_LOCK = threading.RLock()

# What a ticket may do. A device is enrolled for exactly what it needs; phases
# 2-4 hand out the narrower ones rather than widening an existing ticket.
SCOPES = ("config", "observe", "command")

# Commands are one-shot and time-bounded. A phone that is off for a day must not
# come back and fire yesterday's capture at a moment nobody asked for it.
COMMAND_TTL = 600          # 10 min, the same window §2.2 uses for pairing
MAX_ATTEMPTS = 3           # redelivery cap; matches the self-fix budget idea

# Bounded observation intake. The sensing layer streams; the board does not need
# history, only the newest value per key (§2.5 "newest-frame-only").
MAX_OBSERVATION_BYTES = 64 * 1024

DEFAULT_CONFIG = {
    # §2.5 transport discipline. 60s is the SAFETY NET, not the live path.
    "poll_seconds": 60,
    # Every sensing capability defaults OFF. Phase 1 ships the foundation only;
    # a capability turns on when its phase lands AND the owner enables it.
    "mic_enabled": False,
    "camera_enabled": False,
    "notifications_enabled": False,
    # §2.6: the foreground service is what keeps items 1-4 alive at all.
    "foreground_service": True,
    # Capped exponential backoff, both ends (§2.5).
    "backoff_min_seconds": 1,
    "backoff_max_seconds": 30,
}


def _load():
    """Never raises. A corrupt store reads as empty - see FAIL-SAFE above."""
    if not os.path.exists(STORE):
        return {"devices": [], "config": {}, "commands": [], "observations": {}}
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
    except (ValueError, OSError):
        return {"devices": [], "config": {}, "commands": [], "observations": {}}
    if not isinstance(d, dict):
        return {"devices": [], "config": {}, "commands": [], "observations": {}}
    d.setdefault("devices", [])
    d.setdefault("config", {})
    d.setdefault("commands", [])
    d.setdefault("observations", {})
    return d


def _save(d):
    # Unique temp name per writer, belt-and-braces behind _LOCK: two writers on
    # ONE tmp path is the Windows PermissionError above, and a shared name would
    # make any future lock-bypassing caller fail loudly at the worst moment.
    tmp = "%s.%d.%d.tmp" % (STORE, os.getpid(), threading.get_ident())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, STORE)
    except BaseException:
        try:
            os.unlink(tmp)          # never leave a half-written temp behind
        except OSError:
            pass
        raise


def _hash(token):
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _now():
    return int(time.time())


# -- devices / tickets ---------------------------------------------------

def mint_ticket(label, scopes=("config", "observe", "command"), actor="owner"):
    """Enroll a device. Returns {device, token} - the ONLY time the token is
    ever available. Only its hash is persisted, so a lost token is re-minted,
    never recovered."""
    with _LOCK:
        label = (label or "").strip() or "companion"
        bad = [s for s in scopes if s not in SCOPES]
        if bad:
            raise ValueError("unknown scope(s): %s" % ", ".join(sorted(bad)))
        token = "hdc_" + secrets.token_urlsafe(24)     # 24 random bytes, per §2.1
        dev = {
            "id": "dev_" + secrets.token_hex(6),
            "label": label,
            "hash": _hash(token),
            "scopes": sorted(set(scopes)),
            "revoked": False,
            "created": _now(),
            "created_by": actor,
            "last_seen": None,
        }
        d = _load()
        d["devices"].append(dev)
        _save(d)
        return {"device": _public(dev), "token": token}


def _public(dev):
    """A device as the API may show it - never the hash."""
    return {k: v for k, v in dev.items() if k != "hash"}


def list_devices():
    return [_public(x) for x in _load().get("devices", [])]


def revoke(device_id, actor="owner"):
    """Revoke ONE device. Tickets are revocable one by one (§2.1) - that is the
    whole reason they are not a shared secret."""
    with _LOCK:
        d = _load()
        for dev in d["devices"]:
            if dev.get("id") == device_id and not dev.get("revoked"):
                dev["revoked"] = True
                dev["revoked_at"] = _now()
                dev["revoked_by"] = actor
                _save(d)
                return _public(dev)
        return None


def authorize(bearer, scope=None):
    """Resolve a presented ticket to its device, or None.

    Hash-compare in constant time: a plain `==` on secrets leaks length and
    prefix through timing. Updates last_seen as an OBSERVATION (the device
    demonstrably called), which is also how the owner sees a dead device.
    """
    with _LOCK:
        if not bearer:
            return None
        h = _hash(bearer)
        d = _load()
        for dev in d.get("devices", []):
            if dev.get("revoked"):
                continue
            if not hmac.compare_digest(str(dev.get("hash") or ""), h):
                continue
            if scope and scope not in (dev.get("scopes") or []):
                return None
            dev["last_seen"] = _now()
            try:
                _save(d)
            except OSError:
                pass          # last_seen is telemetry; never fail a live call for it
            return _public(dev)
        return None


    # -- backend-driven config ----------------------------------------------

def config():
    """Effective config = defaults + owner overrides. The device gets the
    resolved dict, so an unknown key on an older APK is simply ignored rather
    than crashing it."""
    d = _load()
    out = dict(DEFAULT_CONFIG)
    for k, v in (d.get("config") or {}).items():
        out[k] = v
    return out


def save_config(patch, actor="owner"):
    with _LOCK:
        d = _load()
        cfg = dict(d.get("config") or {})
        for k, v in (patch or {}).items():
            cfg[k] = v
        d["config"] = cfg
        d["config_updated"] = _now()
        d["config_updated_by"] = actor
        _save(d)
        return config()


    # -- commands: queued here, consumed ON PROOF ----------------------------

def queue_command(kind, device_id=None, actor="owner", **args):
    """Queue a one-shot command. `device_id=None` means "any enrolled device"."""
    with _LOCK:
        kind = (kind or "").strip()
        if not kind:
            raise ValueError("command kind required")
        cmd = {
            "id": "cmd_" + secrets.token_hex(6),
            "kind": kind,
            "args": args or {},
            "device": device_id,
            "state": "pending",
            "created": _now(),
            "created_by": actor,
            "attempts": 0,
        }
        d = _load()
        d["commands"].append(cmd)
        _save(d)
        return dict(cmd)


def _live(cmd, now):
    return (cmd.get("state") == "pending"
            and now - int(cmd.get("created") or 0) < COMMAND_TTL
            and int(cmd.get("attempts") or 0) < MAX_ATTEMPTS)


def pending(device_id):
    """The device's work list. A PURE READ of what is due - it consumes nothing.

    It does record delivery (attempts/delivered_at), which is an observation of
    something that actually happened, not a claim that the command ran. The
    attempts counter is what stops a command that crashes its device from
    redelivering forever.
    """
    with _LOCK:
        now = _now()
        d = _load()
        out = []
        for cmd in d.get("commands", []):
            if not _live(cmd, now):
                continue
            if cmd.get("device") and cmd["device"] != device_id:
                continue
            cmd["attempts"] = int(cmd.get("attempts") or 0) + 1
            cmd["delivered_at"] = now
            cmd["delivered_to"] = device_id
            out.append({k: cmd[k] for k in ("id", "kind", "args")})
        if out:
            _save(d)
        return out


def ack(command_id, device_id, ok=True, result=None):
    """THE single owner of a command's terminal state, moved only on the
    device's report that it ran. Idempotent: a duplicate ack (a retry after a
    dropped response) is a no-op that returns the already-settled command, not
    an error - the device must be able to retry safely."""
    with _LOCK:
        d = _load()
        for cmd in d.get("commands", []):
            if cmd.get("id") != command_id:
                continue
            if cmd.get("state") != "pending":
                return dict(cmd)                  # already settled; stay idempotent
            cmd["state"] = "done" if ok else "failed"
            cmd["settled_at"] = _now()
            cmd["settled_by"] = device_id
            if result is not None:
                cmd["result"] = result
            _save(d)
            return dict(cmd)
        return None


def list_commands(include_settled=False):
    now = _now()
    out = []
    for cmd in _load().get("commands", []):
        if include_settled or _live(cmd, now):
            c = dict(cmd)
            if c.get("state") == "pending" and not _live(cmd, now):
                # DERIVED, not stored: expiry is a function of the clock, so it
                # is computed on read rather than written by a sweeper that may
                # never run.
                c["state"] = "expired"
            out.append(c)
    return out


def sweep(max_settled=200):
    """Bound the store. Keeps the newest settled commands for the audit trail
    and drops the rest; live commands are never touched."""
    with _LOCK:
        now = _now()
        d = _load()
        live = [c for c in d.get("commands", []) if _live(c, now)]
        settled = [c for c in d.get("commands", []) if not _live(c, now)]
        settled.sort(key=lambda c: int(c.get("settled_at") or c.get("created") or 0))
        d["commands"] = live + settled[-max_settled:]
        _save(d)
        return {"live": len(live), "kept": len(settled[-max_settled:])}


    # -- observation intake --------------------------------------------------

def record(device_id, key, value):
    """Newest-value-per-key from the sensing layer (§2.5). Bounded on purpose:
    this is a hand-off point to the board, not a time-series database."""
    with _LOCK:
        key = (key or "").strip()
        if not key:
            raise ValueError("observation key required")
        blob = json.dumps(value)
        if len(blob) > MAX_OBSERVATION_BYTES:
            raise ValueError("observation too large (%d bytes, max %d)"
                             % (len(blob), MAX_OBSERVATION_BYTES))
        d = _load()
        d.setdefault("observations", {})[key] = {
            "value": value, "device": device_id, "at": _now()}
        _save(d)
        return d["observations"][key]


def observations():
    return _load().get("observations", {})
