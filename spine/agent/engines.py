# -*- coding: utf-8 -*-
"""Engine registry + availability snapshot - the Paseo provider-snapshot
shape (packages/server/src/server/agent/provider-snapshot-manager.ts,
read 2026-09-13), sized for HelmDeck.

WHY THIS EXISTS: every native driver (omp/codex/opencode/pi) was wired into
drivers.run() on 2026-08-24, but the ONLY place a card could pick one was
`settings.drivers`, whose defaults name claude + claude-desktop and nothing
else. So the New-Request picker (surfaces/app/src/app/new.tsx, keys of
settings.drivers) never showed another engine - even on a machine where the
onboarding had just installed one - and the daemon refused it as "unknown
driver". Users could not select. Paseo solves this with a builtin provider
manifest + a per-provider availability probe (`client.isAvailable()`:
binary resolves and answers `--version`) folded into a snapshot the app
renders: ready ones selectable, unavailable ones shown with the reason.
Same here.

Two facts per engine, kept apart on purpose:
  status    - DERIVED from the runtime's own signal at probe time (the binary
              resolves on PATH and `--version` exits 0). Never a stored flag.
  verified  - whether HelmDeck's DRIVER for it has ever run a real turn
              (build plan Cards 6/7/8; debt `codex-opencode-pi-drivers-
              unverified`). A binary being present is not the same claim
              as the driver working - the picker says so.

`settings.drivers` still wins for anything it names (custom exe, tool
grants, record) - the builtin row is the DEFAULT config a bare `{"type":
<id>}` would be, so an engine works out of the box once its CLI exists.

Settings row keys the UI edits (Paseo's ProviderOverride, trimmed to what
the drivers here honour): `enabled` (False hides the engine from the picker
and refuses it at filing - Paseo's provider toggle), `exe` (executable
override, honoured by every driver's build_argv), `env` (extra environment
for the spawn, honoured by every driver's _env). Anything else in the row
(allowed_tools, record, perm, model) is left untouched by the editor.

Probe results are cached: hits for PROBE_HIT_TTL (a CLI does not uninstall
itself mid-session), misses for PROBE_MISS_TTL (the user may be installing
it right now - same reasoning as setup.js's cachedProbe). `?refresh=1`
on /engines forces a re-probe."""
import os
import shutil
import subprocess
import threading
import time

PROBE_HIT_TTL = 600.0
PROBE_MISS_TTL = 60.0
PROBE_TIMEOUT = 20.0

# id -> builtin definition. `type` is the drivers.run() dispatch kind, `bin`
# the CLI name resolved on PATH, `verified` = a real turn has run through
# HelmDeck's driver (omp: build plan Card 8; claude: every card ever).
BUILTIN = (
    {"id": "claude", "label": "Claude Code", "type": "claude", "bin": "claude",
     "verified": True},
    {"id": "claude-desktop", "label": "Claude Code (Desktop)", "type": "claude",
     "bin": "claude", "verified": True},
    {"id": "omp", "label": "OMP", "type": "omp", "bin": "omp", "verified": True},
    {"id": "codex", "label": "Codex", "type": "codex", "bin": "codex",
     "verified": False},
    {"id": "opencode", "label": "OpenCode", "type": "opencode", "bin": "opencode",
     "verified": False},
    {"id": "pi", "label": "Pi", "type": "pi", "bin": "pi", "verified": False},
)
_BY_ID = {e["id"]: e for e in BUILTIN}

# Off-PATH install locations the drivers themselves already fall back to
# (omp_driver.OMP). Kept here so the probe and the spawn agree.
_FALLBACK_PATHS = {
    "omp": [os.path.expandvars(r"C:\Users\%USERNAME%\AppData\Local\omp\omp.exe")],
}

_cache = {}            # id -> (expires_at, entry)
_lock = threading.Lock()


def _settings_drivers():
    try:
        from spine.storage import events
        return dict(events.settings().get("drivers") or {})
    except Exception:              # noqa: BLE001 - registry must never crash a route
        return {}


def known():
    """Every driver name a card may carry: builtin ids + settings.drivers keys."""
    names = set(_BY_ID)
    names.update(_settings_drivers().keys())
    return names


def config(name):
    """The driver cfg drivers.run() gets for a card's driver name, or None
    when the name is unknown. settings.drivers wins; a builtin falls back
    to its bare `{"type": ...}`. One resolver for turnrunner AND the
    machine-task path, so both agree on what a name means."""
    name = name or "claude"
    cfg = _settings_drivers().get(name)
    if cfg:
        return dict(cfg)
    b = _BY_ID.get(name)
    if b:
        return {"type": b["type"]}
    return None


def _definition(name):
    """Builtin definition, or a synthetic one for a settings-only driver
    (its `type` decides which CLI it is)."""
    b = _BY_ID.get(name)
    if b:
        return b
    cfg = _settings_drivers().get(name) or {}
    kind = cfg.get("type") or "claude"
    base = next((e for e in BUILTIN if e["type"] == kind), None)
    return {"id": name, "label": name, "type": kind,
            "bin": base["bin"] if base else None,
            "verified": bool(base and base["verified"]) if kind != "cmd" else True}


def _resolve_exe(name, defn):
    """Absolute spawn argv for the engine's CLI, or None. Mirrors what the
    drivers spawn: settings `exe` first, PATH next, then the driver's own
    off-PATH fallback. A claude.cmd shim is seen through (agentcli.
    _real_claude_exe - the shim is not safely quotable, and the probe
    should exercise the same binary a turn would)."""
    cfg = _settings_drivers().get(name) or {}
    exe = cfg.get("exe")
    if exe:
        return [exe] if os.path.isfile(exe) or shutil.which(exe) else None
    b = defn.get("bin")
    if not b:
        return None
    found = shutil.which(b)
    if not found and b == "claude":
        # the daemon's own resolver (HELMDECK_CLAUDE / PATH / the npm default
        # dir) - the probe must judge the binary a turn would actually spawn
        try:
            from spine.agent import agentcli
            if os.path.isfile(agentcli.CLAUDE):
                found = agentcli.CLAUDE
        except Exception:      # noqa: BLE001
            pass
    if not found:
        for p in _FALLBACK_PATHS.get(b, []):
            if os.path.isfile(p):
                found = p
                break
    if not found:
        return None
    if found.lower().endswith((".cmd", ".bat")):
        try:
            from spine.agent import agentcli
            real = agentcli._real_claude_exe(found) if b == "claude" else None
        except Exception:          # noqa: BLE001
            real = None
        if real:
            return list(real)
    return [found]


def _probe(name, defn):
    """One availability probe = the runtime's own answer to `--version`."""
    row = _settings_drivers().get(name) or {}
    entry = {"id": name, "label": defn["label"], "type": defn["type"],
             "verified": bool(defn.get("verified")),
             "configured": name in _settings_drivers(),
             "enabled": row.get("enabled", True) is not False,
             # the editable part of the row, so the settings editor can
             # round-trip it (save_settings merges per driver id - the
             # app must send the WHOLE row back, never a partial)
             "config": {k: v for k, v in row.items() if k in ("exe", "env", "enabled")},
             "status": "unavailable", "version": "", "error": ""}
    if defn["type"] in ("http", "cmd"):
        # no binary to probe: an http endpoint / shell command is whatever
        # settings says it is - treat as ready, the turn reports failures
        entry["status"] = "ready"
        return entry
    argv = _resolve_exe(name, defn)
    if not argv:
        entry["error"] = "not installed (`%s` not on PATH)" % (defn.get("bin") or name)
        return entry
    try:
        r = subprocess.run(argv + ["--version"], capture_output=True, text=True,
                           timeout=PROBE_TIMEOUT,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        entry["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        return entry
    out = ((r.stdout or "") + " " + (r.stderr or "")).strip()
    if r.returncode != 0:
        entry["error"] = ("`--version` exited %d: %s" % (r.returncode, out[:160])).strip()
        return entry
    entry["status"] = "ready"
    entry["version"] = out.splitlines()[0][:80] if out else "ok"
    entry["exe"] = argv[0]
    return entry


def entry(name, refresh=False):
    defn = _definition(name)
    now = time.time()
    with _lock:
        hit = _cache.get(name)
        if hit and not refresh and hit[0] > now:
            return dict(hit[1])
    e = _probe(name, defn)
    ttl = PROBE_HIT_TTL if e["status"] == "ready" else PROBE_MISS_TTL
    with _lock:
        _cache[name] = (time.time() + ttl, e)
    return dict(e)


def snapshot(refresh=False):
    """All selectable engines with live status - what /engines serves and
    the New-Request picker renders. Builtin order first, then any extra
    settings-only drivers."""
    names = [e["id"] for e in BUILTIN]
    names += sorted(n for n in _settings_drivers() if n not in _BY_ID)
    return [entry(n, refresh=refresh) for n in names]


def check_selectable(name):
    """Refuse a card driver the daemon could not run: unknown names always,
    and a KNOWN engine whose CLI is not present. Returns an error string
    or None. claude is exempt from the availability half - its own spawn
    path has reported 'claude not found' loudly since day one, and the
    sandboxed test suites file claude cards on boxes without it."""
    if name not in known():
        return "unknown driver '%s' - choices: %s" % (name, ", ".join(sorted(known())))
    e = entry(name)
    if not e["enabled"]:
        return "driver '%s' is switched off in settings" % name
    if e["type"] != "claude" and e["status"] != "ready":
        return "driver '%s' is not available: %s" % (name, e["error"] or "not installed")
    return None


def invalidate():
    with _lock:
        _cache.clear()
