# -*- coding: utf-8 -*-
"""The harness loader - agent briefs and settings layers as DATA (`ops/harness/`).

ARCHITECTURE.md: the harness is code, policy is data. The briefs were the
exception - what a card worker is told about itself was a string constant in
drivers.py, and the board copilot's 10 KB system prompt was a constant in
copilot.py. Both are policy: the owner may reword them without touching the
daemon. They live in ops/harness/agents/*.md now, with ops/harness/settings/*.json as
the settings layer each surface runs under.

THE ONE LAW OF THIS MODULE: **it can never break a spawn.**
A card is the owner's work in flight. A typo in a markdown file must not be able
to strand it. So every public function is total - it returns the built-in
default rather than raising - and the built-in defaults below are the exact text
that used to be hardcoded, so "ops/harness/ is missing entirely" degrades to
precisely the old behaviour. Failures are not swallowed silently either: they
accumulate in errors(), which /loop/map surfaces, so a broken file is visible
instead of mysteriously ineffective.

WHAT IS DELIBERATELY NOT DATA
-----------------------------
The <helmdeck-ask> protocol text stays in ask.py. It is parsed by ask.parse()'s
regex, so prompt and parser must ship together; making it editable would let an
innocent reword silently break every question button the owner taps. Agent files
opt in with `ask_protocol: true` and place it with a {{ask_protocol}} marker.

CACHING
-------
Files are re-read when their mtime OR size changes (mtime alone has ~1s
granularity on some filesystems, so a fast edit can land inside the same tick
and be missed). Cheap enough to check on every spawn, which is what we want:
edit a brief, next turn uses it, no daemon restart.
"""
import json, os, threading

from daemon.paths import REPO_ROOT as ROOT
HARNESS = os.path.join(ROOT, "ops", "harness")
AGENTS = os.path.join(HARNESS, "agents")
SETTINGS = os.path.join(HARNESS, "settings")

_lock = threading.Lock()
_cache = {}          # path -> (stamp, parsed)
_errors = {}         # path -> message   (cleared for a path once it loads clean)

# ---------------------------------------------------------------------------
# BUILT-IN DEFAULTS - the exact constants that used to live in drivers.py /
# copilot.py. These are the floor: if ops/harness/ is deleted, mangled, or shipped
# without, every surface still gets the brief it had before this module existed.
# ---------------------------------------------------------------------------
_DEFAULT_CARD = (
    "You are working ONE HelmDeck card in an isolated git worktree. "
    "You CAN: edit files, run commands/ops/tests/builds, and commit on THIS branch. "
    "If you start a dev server, bind the port reserved for THIS card in "
    "$HELMDECK_DEV_PORT (when set) - not the project default - so parallel "
    "cards never fight over a port. "
    "You CANNOT (by design): merge to main, access secrets (.env/keys), or deploy - "
    "the owner accepts the card on the board, and accepting runs the repo deploy hook. "
    "Therefore NEVER end with just 'I cannot do X'. When your work is done and "
    "verified, end with a short DELIVERED summary and the sentence: "
    "'Ready for Review - move the card to Review; accepting it deploys.' "
    "If something truly blocks you, name the exact blocker and what the owner "
    "must change (a setting, a secret, a decision)."
    "\n\n"
    "Background tasks you launch (a background shell, a build, an export, an "
    "emulator) are YOUR work in flight. While ANY of them is still running, the "
    "card is NOT done: never write a DELIVERED summary, never say 'Ready for "
    "Review', never claim completion. If you end a turn while background tasks "
    "run, say exactly that instead - which tasks you are waiting on and what "
    "you will do with their results; the harness wakes you when they report. "
    "Deliver only after every background task has reported AND you have read "
    "its output and judged it good."
)

_DEFAULT_MACHINE = (
    "You are running ONE HelmDeck MACHINE task for the OWNER, on the owner's own "
    "Windows PC, in the working directory you were started in. This is not a git "
    "worktree and there is no branch. "
    "You CAN: run commands and PowerShell, start and control applications, read "
    "and write files, inspect and fix the system - this is the owner's machine and "
    "he asked for this task through his authenticated board. "
    "You SHOULD: prefer the reversible form of an action, say plainly what you "
    "changed, and never touch HelmDeck's own secrets (settings.json, users.json, "
    "helmdeck.db, tokens) or its git history. "
    "Ask for nothing you can find out yourself - look it up on the machine. "
    "NEVER end with just 'I cannot do X': if one route is blocked, try another, "
    "and if you are truly stuck, name the exact blocker and the one thing the "
    "owner must decide or provide. When it is done, end with a short DELIVERED "
    "summary of what actually changed on the machine."
    "\n\n"
    "Long-running foreground processes (a dev server like `wrangler dev` / `npm "
    "run dev`, a `serve`, a watcher, anything that stays in the foreground and "
    "never exits) MUST be started DETACHED - `Start-Process` in PowerShell, or a "
    "background shell - NEVER as a synchronous command you wait on. A synchronous "
    "foreground server never returns, so the call hangs your whole turn (and, on "
    "a desktop card, holds the single screen/keyboard lock and starves every "
    "other machine card). Launch it detached, then poll for readiness (a port "
    "check, `Get-CimInstance`, an HTTP request) to confirm it came up."
    "\n\n"
    "Background tasks you launch (a background shell, a build, an install, a "
    "long copy) are YOUR work in flight. While ANY of them is still running, "
    "the task is NOT done: never write a DELIVERED summary, never claim "
    "completion. If you end a turn while background tasks run, say exactly "
    "that instead - which tasks you are waiting on and what you will do with "
    "their results; the harness wakes you when they report. Deliver only after "
    "every background task has reported AND you have read its output and "
    "judged it good. (A detached dev server the owner asked you to leave "
    "running is not a background task in this sense - it is a deliverable.)"
)

# name -> (body, frontmatter). ask_protocol is on for the two worker surfaces,
# matching what drivers.py did by concatenating ask.BRIEF.
_DEFAULTS = {
    "card-worker": (_DEFAULT_CARD,
                    {"name": "card-worker", "settings": "card",
                     "setting_sources": "project", "ask_protocol": True}),
    "machine-worker": (_DEFAULT_MACHINE,
                       {"name": "machine-worker", "settings": "card",
                        "setting_sources": "project", "ask_protocol": True}),
    # The copilot's floor is a SHORT degraded-mode stub, not a copy of the real
    # 17 KB role: a full copy rots out of sync with the file (measured - the
    # copy that lived in copilot.py drifted ~1.9k chars behind), and the real
    # file now ships with EVERY install (git checkout; the desktop bundle
    # carries ops/harness as an extraResource). If this stub ever speaks, the
    # installation is broken and says so - errors() carries the missing path.
    # The PM's floor is the JSON-shape one-liner pm.py used to carry inline -
    # the plan PARSER depends on that shape, so the floor keeps plans parseable
    # even on a broken install (and the real 8.8 KB role is ops/harness/agents/
    # pm.md, shipped with every install like the other briefs).
    "pm": (
        "You are the HelmDeck PM/CTO. Reply with JSON: "
        "{summary, done_pct, milestones, next, risks}.",
        {"name": "pm", "settings": "", "setting_sources": "",
         "ask_protocol": False}),
    "board-copilot": (
        "You are HENRY, HelmDeck's board agent. Your full role file "
        "(ops/harness/agents/board-copilot.md) is MISSING from this "
        "installation - you are running in degraded mode. Answer questions "
        "briefly, take no board actions, and tell the owner in your first "
        "sentence that the installation is broken (harness role file missing) "
        "and needs repair.",
        {"name": "board-copilot", "settings": "copilot",
         "setting_sources": "", "ask_protocol": False}),
}

ASK_MARKER = "{{ask_protocol}}"


def _note(path, msg):
    _errors[path] = msg


def _stamp(path):
    """(mtime, size) or None. Size is in there because mtime granularity can be
    a full second - an edit landing in the same tick would otherwise be missed."""
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def _cached(path, parse):
    """Re-parse `path` only when it changed. Returns None if unreadable/invalid,
    and records why in errors(). Never raises."""
    try:
        stamp = _stamp(path)
        with _lock:
            hit = _cache.get(path)
            if hit and hit[0] == stamp:
                return hit[1]
        if stamp is None:
            _note(path, "missing")
            with _lock:
                _cache[path] = (stamp, None)
            return None
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        val = parse(raw)
        with _lock:
            _cache[path] = (stamp, val)
        _errors.pop(path, None)
        return val
    except Exception as e:                       # noqa: BLE001 - a loader may not raise
        _note(path, "%s: %s" % (type(e).__name__, str(e)[:200]))
        return None


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------
def _mini_yaml(text):
    """The flat `key: value` subset our frontmatter actually uses.

    PyYAML is used when importable, but this exists so the loader has NO import
    that can fail: the daemon must be able to spawn a card on a box where
    PyYAML was never installed. Handles quotes, and true/false/int coercion -
    which is the whole vocabulary of the agent schema."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        elif v.lower() in ("true", "false"):
            v = v.lower() == "true"
        elif v.lstrip("-").isdigit():
            v = int(v)
        out[k] = v
    return out


def _parse_agent(raw):
    """(body, frontmatter) from a `---`-delimited markdown agent file."""
    fm, body = {}, raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            head = raw[raw.find("\n", 3) + 1:end]
            body = raw[end + 4:].lstrip("\r\n")
            try:
                import yaml
                fm = yaml.safe_load(head) or {}
                if not isinstance(fm, dict):
                    raise ValueError("frontmatter is not a mapping")
            except Exception:
                fm = _mini_yaml(head)
    return body.strip(), fm


def _agent_file(name):
    return _cached(os.path.join(AGENTS, "%s.md" % name), _parse_agent)


def _resolve(body, fm):
    """Splice the fixed wire protocol into an editable body."""
    if not fm.get("ask_protocol"):
        return body.replace(ASK_MARKER, "").strip()
    try:
        from spine.ops import ask
        proto = ask.BRIEF
    except Exception:
        return body.replace(ASK_MARKER, "").strip()
    if ASK_MARKER in body:
        return body.replace(ASK_MARKER, proto).strip()
    return (body + "\n\n" + proto).strip()


# ---------------------------------------------------------------------------
# public API - every one of these is total
# ---------------------------------------------------------------------------
def brief(name, default=None):
    """The full system prompt for a surface: the editable body from
    ops/harness/agents/<name>.md with the fixed ask protocol spliced in.

    Falls back to the built-in default (or `default`) whenever the file is
    missing, unreadable, has no body, or fails to parse - so a bad edit costs
    the customisation, never the spawn."""
    d_body, d_fm = _DEFAULTS.get(name, ("", {}))
    if default is not None:
        d_body = default
    got = _agent_file(name)
    if not got or not got[0]:
        return _resolve(d_body, d_fm) if d_body else (d_body or "")
    body, fm = got
    # a file that forgot its frontmatter still gets the surface's normal wiring
    merged = dict(d_fm)
    merged.update(fm or {})
    return _resolve(body, merged)


def meta(name):
    """The agent's frontmatter, defaults filled in. Never raises."""
    d_body, d_fm = _DEFAULTS.get(name, ("", {}))
    got = _agent_file(name)
    merged = dict(d_fm)
    if got and isinstance(got[1], dict):
        merged.update(got[1])
    return merged


def settings_file(name):
    """Absolute path of the settings layer for surface `name`, or "" if there
    is none / it is not valid JSON.

    Validated as JSON here for a specific reason measured against the real CLI:
    `claude -p` SILENTLY IGNORES a settings file that fails validation (it says
    so in --help). A broken file would therefore not error, it would just hand
    the agent an empty layer - and the operator's personal config would be
    excluded by luck rather than by design. Better to catch what we can here
    and say so in errors()."""
    key = (meta(name) or {}).get("settings")
    if not key:
        return ""
    path = os.path.join(SETTINGS, "%s.json" % key)
    if _cached(path, json.loads) is None:
        return ""
    return path


def cli_args(name):
    """The settings-layer argv for a `claude` spawn on this surface.

    Returns [] when nothing is configured, which is exactly the pre-harness
    behaviour (inherit whatever cwd implies) - so wiring this in can only ever
    add isolation, never remove a flag someone depended on."""
    m = meta(name) or {}
    argv = []
    src = m.get("setting_sources")
    if src is not None:                 # "" is meaningful: load NO ambient layer
        argv += ["--setting-sources", str(src)]
    sf = settings_file(name)
    if sf:
        argv += ["--settings", sf]
    return argv


def errors():
    """{path: message} for every harness file that failed to load. Surfaced by
    /loop/map so a broken brief is visible, not just quietly ineffective."""
    with _lock:
        return dict(_errors)


def describe():
    """What each surface resolved to - for /loop/map and for a human check:
    `python spine/registry/harness.py`."""
    out = []
    for name in sorted(_DEFAULTS):
        m = meta(name)
        path = os.path.join(AGENTS, "%s.md" % name)
        out.append({
            "name": name,
            "source": "ops/harness/agents/%s.md" % name if os.path.exists(path) else "built-in default",
            "settings": (os.path.relpath(settings_file(name), ROOT).replace("\\", "/")
                         if settings_file(name) else ""),
            "setting_sources": m.get("setting_sources"),
            "ask_protocol": bool(m.get("ask_protocol")),
            "chars": len(brief(name)),
        })
    return {"agents": out, "errors": errors()}


# ---------------------------------------------------------------------------
# EDITING - read/write the policy data behind each surface.
#
# Everything below is the WRITE path (owner-only, audited by the caller). It is
# deliberately separated from the read path above: the read path is total and
# may never raise, because a spawn depends on it. These may and DO raise - a
# rejected edit must be loud, not silently ignored. That asymmetry is the point.
# ---------------------------------------------------------------------------
SCHEMA = os.path.join(HARNESS, "schema")
VERSIONS = os.path.join(HARNESS, ".versions")

# The three surfaces the board can spawn, and where each one's argv comes from.
# `builder` names the ONE function that assembles that surface's command line;
# preview() calls it rather than re-listing flags (CLAUDE.md: one owner).
SURFACES = [
    {"key": "card", "agent": "card-worker", "label": "Karte (Worker im Worktree)",
     "builder": "drivers.build_argv", "cwd": "<worktree der Karte>"},
    {"key": "machine", "agent": "machine-worker", "label": "Maschine (Task auf dem PC)",
     "builder": "drivers.build_argv", "cwd": "<Arbeitsordner des Tasks>"},
    # `agent` is the FILE key (ops/harness/agents/board-copilot.md) and deliberately
    # keeps its old name: renaming the file would break every brief lookup and
    # the settings mapping for a cosmetic win. The LABEL is what the owner reads.
    {"key": "pm", "agent": "board-copilot", "label": "PM / Henry",
     "builder": "copilot.build_argv", "cwd": "<repo root>"},
]

_BY_KEY = {s["key"]: s for s in SURFACES}
_BY_AGENT = {s["agent"]: s for s in SURFACES}


def _rel(path):
    """The shortest HONEST form of a path for display.

    Repo-relative inside the repo, `~/...` under the home dir, absolute
    otherwise. The operator's settings file lives four levels above a worktree,
    and "../../../../.claude/settings.json" tells the owner nothing about which
    file that is - `~/.claude/settings.json` tells him immediately."""
    p = os.path.abspath(path)
    try:
        inside = os.path.relpath(p, ROOT)
        if not inside.startswith(".."):
            return inside.replace("\\", "/")
    except ValueError:                      # different drive on Windows
        pass
    home = os.path.expanduser("~")
    try:
        under = os.path.relpath(p, home)
        if not under.startswith(".."):
            return "~/" + under.replace("\\", "/")
    except ValueError:
        pass
    return p.replace("\\", "/")


def _sha(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# schema validation
# ---------------------------------------------------------------------------
def load_schema(which):
    """The JSON Schema for "agent" or "settings", or {} if unreadable."""
    return _cached(os.path.join(SCHEMA, "%s.schema.json" % which), json.loads) or {}


def _validate_min(obj, schema):
    """The draft-07 subset our two schemas actually use, for boxes where
    jsonschema was never installed. Checks required / type / enum /
    additionalProperties - which is the whole vocabulary of agent.schema.json.
    Returns a list of human-readable errors."""
    errs = []
    if not isinstance(schema, dict) or not isinstance(obj, dict):
        return errs
    props = schema.get("properties") or {}
    for k in schema.get("required") or []:
        if k not in obj:
            errs.append("Pflichtfeld fehlt: %s" % k)
    if schema.get("additionalProperties") is False:
        for k in obj:
            if k not in props:
                errs.append("unbekannter Schluessel: %s (erlaubt: %s)"
                            % (k, ", ".join(sorted(props))))
    _types = {"string": str, "boolean": bool, "object": dict, "array": list,
              "number": (int, float), "integer": int}
    for k, spec in props.items():
        if k not in obj or not isinstance(spec, dict):
            continue
        want = _types.get(spec.get("type"))
        # bool is an int subclass in Python - keep "number" from accepting True
        if want and (not isinstance(obj[k], want)
                     or (spec.get("type") in ("number", "integer") and isinstance(obj[k], bool))):
            errs.append("%s muss %s sein" % (k, spec.get("type")))
        elif "enum" in spec and obj[k] not in spec["enum"]:
            errs.append("%s muss einer von %s sein" % (k, spec["enum"]))
    return errs


def validate(obj, which):
    """(errors, validator). Uses jsonschema when importable and falls back to
    the built-in subset otherwise - and SAYS which one ran, because "validated"
    means two different things here and the owner should see which he got."""
    schema = load_schema(which)
    if not schema:
        return (["Schema ops/harness/schema/%s.schema.json nicht lesbar" % which], "none")
    try:
        import jsonschema
        v = jsonschema.Draft7Validator(schema)
        errs = ["%s%s" % ("/".join(str(x) for x in e.path) + ": " if e.path else "", e.message)
                for e in sorted(v.iter_errors(obj), key=lambda e: list(e.path))]
        return (errs, "jsonschema")
    except ImportError:
        return (_validate_min(obj, schema), "builtin-subset")
    except Exception as e:                                   # noqa: BLE001
        return (["Validator-Fehler: %s" % str(e)[:200]], "error")


# ---------------------------------------------------------------------------
# versions - every write keeps the file it replaced, so a bad edit is revertable
# ---------------------------------------------------------------------------
def _vdir(kind, name):
    return os.path.join(VERSIONS, kind, name)


def versions(kind, name):
    """Prior contents of a harness file, newest first. Never raises."""
    d = _vdir(kind, name)
    out = []
    try:
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            stamp, _, who = fn.rpartition("__")
            out.append({"id": fn, "ts": stamp.replace("_", " ", 1) if stamp else fn,
                        "actor": (who.rsplit(".", 1)[0] if who else "?"),
                        "bytes": st.st_size, "_m": st.st_mtime})
    except OSError:
        pass
    # By MTIME, not by filename. The same-second collision suffix ("...-34-2__")
    # sorts BEFORE the unsuffixed "...-34__" lexically ("-" < "_"), so a
    # name sort silently mislabels the newest version as the oldest - and
    # "restore the most recent" would then restore the wrong text. Measured.
    out.sort(key=lambda v: (v["_m"], v["id"]), reverse=True)
    for v in out:
        v.pop("_m", None)
    return out


def _keep_version(kind, name, path, actor):
    """Snapshot the CURRENT bytes of `path` before it is overwritten. Best
    effort by design: failing to archive must not block the owner's edit, and a
    write that never happened has nothing to archive."""
    cur = _read_text(path)
    if cur is None:
        return ""
    import re, time as _t
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(actor))[:32] or "unknown"
    ext = os.path.splitext(path)[1]
    stamp = _t.strftime("%Y-%m-%d_%H-%M-%S")
    d = _vdir(kind, name)
    try:
        os.makedirs(d, exist_ok=True)
        # The stamp has 1-second granularity and an edit-then-revert lands well
        # inside one second, so the id needs a tiebreaker - but the tiebreaker
        # must also SORT right, which is the part that bit us: an "…-2__" suffix
        # collates BEFORE the unsuffixed "…__" ("-" < "_"), so history came back
        # in the wrong order and "restore the newest" restored the oldest.
        # A zero-padded sequence on EVERY id makes name order == time order.
        n = 1
        while True:
            vid = "%s-%03d__%s%s" % (stamp, n, safe, ext)
            if not os.path.exists(os.path.join(d, vid)):
                break
            n += 1
        # newline="\n": without it Windows rewrites every \n as \r\n, so a
        # snapshot was 12 bytes longer than the file it archived and a restore
        # silently changed the file's line endings.
        with open(os.path.join(d, vid), "w", encoding="utf-8", newline="\n") as f:
            f.write(cur)
        return vid
    except OSError:
        return ""


def version_text(kind, name, vid):
    """The bytes of one archived version, or None."""
    if os.sep in vid or "/" in vid or ".." in vid:      # no traversal out of the box
        return None
    return _read_text(os.path.join(_vdir(kind, name), vid))


def _nl_style(path):
    r"""The newline convention the file on disk already uses.

    core.autocrlf=true checks these files out with CRLF on Windows. Writing
    plain "\n" therefore rewrote every line ending on every save: `git diff`
    showed nothing (it normalises) but `git status` reported the file modified
    forever after, so a one-word brief edit looked like a whole-file rewrite.
    Match what is there; only a brand-new file picks LF."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return "\n"
    return "\r\n" if raw.count(b"\r\n") > raw.count(b"\n") - raw.count(b"\r\n") else "\n"


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline=_nl_style(path)) as f:
        f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# the editable documents
# ---------------------------------------------------------------------------
def settings_keys():
    """Which settings layers exist as far as the surfaces are concerned. Derived
    from the agent frontmatter, not a second hand-kept list - add a surface and
    its layer becomes writable by itself."""
    return {k for k in ((meta(s["agent"]) or {}).get("settings") for s in SURFACES) if k}


def agent_doc(name):
    """The raw markdown of ops/harness/agents/<name>.md plus what it resolves to.
    `text` is "" when the file does not exist - the surface is then running on
    the built-in default, and writing creates the file."""
    path = os.path.join(AGENTS, "%s.md" % name)
    raw = _read_text(path)
    m = meta(name)
    return {
        "name": name, "path": _rel(path), "exists": raw is not None,
        "text": raw or "", "sha256": _sha(raw) if raw is not None else "",
        "resolved_chars": len(brief(name)),
        "frontmatter": m,
        "ask_protocol": bool(m.get("ask_protocol")),
        "versions": versions("agents", name),
    }


def settings_doc(key):
    """The raw JSON of ops/harness/settings/<key>.json."""
    path = os.path.join(SETTINGS, "%s.json" % key)
    raw = _read_text(path)
    return {
        "key": key, "path": _rel(path), "exists": raw is not None,
        "text": raw or "", "sha256": _sha(raw) if raw is not None else "",
        "versions": versions("settings", key),
    }


def write_agent(name, text, actor="owner"):
    """Replace ops/harness/agents/<name>.md. Raises ValueError on a rejected edit.

    Validated BEFORE the write, against ops/harness/schema/agent.schema.json. The
    body is free prose (it is the policy), but the frontmatter drives real spawn
    flags - a typo'd `setting_sources` would hand the worker the operator's
    personal config, which is the entire class of bug this harness exists to
    close. So the frontmatter is schema-checked and the body is not."""
    if name not in _BY_AGENT:
        raise ValueError("unbekannte Surface: %s" % name)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("leerer Brief - das wuerde die Surface auf den Built-in-Default zuruecksetzen; "
                         "loesche die Datei bewusst, wenn du das willst")
    body, fm = _parse_agent(text)
    if not body.strip():
        raise ValueError("kein Body: die Frontmatter allein ist kein Brief")
    fm = dict(fm or {})
    fm.setdefault("name", name)
    if fm.get("name") != name:
        raise ValueError("frontmatter `name: %s` passt nicht zum Dateinamen %s"
                         % (fm.get("name"), name))
    errs, validator = validate(fm, "agent")
    if errs:
        raise ValueError("Frontmatter verletzt das Schema (%s): %s" % (validator, "; ".join(errs[:5])))
    st = fm.get("settings")
    if st and not os.path.exists(os.path.join(SETTINGS, "%s.json" % st)):
        raise ValueError("settings: %s zeigt auf ops/harness/settings/%s.json - die es nicht gibt" % (st, st))
    path = os.path.join(AGENTS, "%s.md" % name)
    vid = _keep_version("agents", name, path, actor)
    _atomic_write(path, text if text.endswith("\n") else text + "\n")
    return {"path": _rel(path), "kept_version": vid, "validator": validator,
            "sha256": _sha(text), "resolved_chars": len(brief(name))}


def write_settings(key, text, actor="owner"):
    """Replace ops/harness/settings/<key>.json. Raises ValueError on a rejected edit.

    Two checks, and the second is the one that matters: `claude -p` SILENTLY
    IGNORES a settings file that fails ITS validation. A file that is valid JSON
    but wrong in shape would therefore not error anywhere - the worker would
    just quietly run with an empty layer, and the isolation this file exists to
    provide would be gone with no symptom. Catching it at write time is the only
    moment it is cheap."""
    if key not in settings_keys():
        raise ValueError("unbekannte Settings-Ebene: %s" % key)
    if not isinstance(text, str):
        raise ValueError("settings muessen Text (JSON) sein")
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise ValueError("kein gueltiges JSON: %s" % str(e)[:200])
    if not isinstance(obj, dict):
        raise ValueError("die oberste Ebene muss ein Objekt sein")
    errs, validator = validate(obj, "settings")
    if errs:
        raise ValueError("verletzt das Schema (%s): %s" % (validator, "; ".join(errs[:5])))
    path = os.path.join(SETTINGS, "%s.json" % key)
    vid = _keep_version("settings", key, path, actor)
    _atomic_write(path, text if text.endswith("\n") else text + "\n")
    return {"path": _rel(path), "kept_version": vid, "validator": validator, "sha256": _sha(text)}


def restore(kind, name, vid, actor="owner"):
    """Put an archived version back. Goes through the normal write path, so a
    restore is validated exactly like a fresh edit and is itself versioned -
    reverting a revert is therefore always possible."""
    text = version_text(kind, name, vid)
    if text is None:
        raise ValueError("Version %s nicht gefunden" % vid)
    if kind == "agents":
        return write_agent(name, text, actor)
    if kind == "settings":
        return write_settings(name, text, actor)
    raise ValueError("unbekannte Art: %s" % kind)


# ---------------------------------------------------------------------------
# SPAWN PREVIEW - effective config WITH PROVENANCE
#
# The pattern is `git config --show-origin` / `kubectl describe`: do not tell
# the owner what the harness is configured to do, show him the resolved thing
# and where every piece of it came from. A card worker once ran for weeks under
# the operator's personal ~/.claude - a pinned model and an rtk hook on every
# Bash call - and nothing in the product could have revealed that, because
# nothing rendered what actually ran. This does.
# ---------------------------------------------------------------------------
def _claude_layers(sources):
    """The ambient settings layers the CLI would load, in precedence order.

    `sources` is the value of --setting-sources: None means the flag is not
    passed at all (CLI default = every ambient layer), "" means load none."""
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    known = [
        ("user", os.path.join(home, "settings.json"),
         "Die persoenliche Konfiguration des Operators auf diesem PC."),
        ("project", os.path.join(ROOT, ".claude", "settings.json"),
         "Die eigene .claude/settings.json des Repos - hier leben die Build-Loop-Hooks."),
        ("local", os.path.join(ROOT, ".claude", "settings.local.json"),
         "Ungetrackte lokale Overrides des Repos."),
    ]
    if sources is None:
        allowed, why = {"user", "project", "local"}, "kein --setting-sources: der CLI-Default laedt alles"
    else:
        allowed = {x.strip() for x in str(sources).split(",") if x.strip()}
        why = "--setting-sources %s" % (('"%s"' % sources) if sources == "" else sources)
    out = []
    for key, path, note in known:
        out.append({"layer": key, "path": _rel(path), "abs": path,
                    "exists": os.path.exists(path),
                    "included": key in allowed, "note": note, "reason": why})
    return out


def _hook_rows(path, layer, included):
    """Flatten one settings file's hook map into (event, matcher, command) rows.

    A hook is the sharpest end of a settings layer - it runs a command on the
    worker's machine - so the matrix lists them individually rather than saying
    "3 hooks". EXCLUDED rows are listed too, and that is the whole point: seeing
    that the operator's rtk hook is present-but-excluded is the answer to a very
    different question than not seeing it at all."""
    raw = _read_text(path)
    if raw is None:
        return []
    try:
        obj = json.loads(raw)
    except ValueError:
        return [{"event": "?", "matcher": "", "command": "(Datei ist kein gueltiges JSON)",
                 "origin": _rel(path), "layer": layer, "included": included, "broken": True}]
    rows = []
    hooks = obj.get("hooks") if isinstance(obj, dict) else None
    if not isinstance(hooks, dict):
        return rows
    for event in sorted(hooks):
        for grp in hooks[event] if isinstance(hooks[event], list) else []:
            if not isinstance(grp, dict):
                continue
            for h in grp.get("hooks") or []:
                if not isinstance(h, dict):
                    continue
                rows.append({
                    "event": event, "matcher": grp.get("matcher") or "*",
                    "command": str(h.get("command") or "")[:300],
                    "timeout": h.get("timeout"),
                    "origin": _rel(path), "layer": layer, "included": bool(included),
                })
    return rows


def _disables_hooks(path):
    """True when a settings file sets disableAllHooks. Never raises."""
    try:
        raw = _read_text(path)
        return bool(raw) and json.loads(raw).get("disableAllHooks") is True
    except Exception:                                        # noqa: BLE001
        return False


BRIEF_ARG_MARKER = "<brief>"


def _memory_isolation(sf):
    """Whether THIS settings file's own permissions.deny blocks a write into the
    shared auto-memory directory (debt: card-shares-the-operators-auto-memory).

    Read out of the REAL settings file at preview time, not asserted - so an
    edit that removes the deny line shows up here immediately, the same way a
    hook that disappears from a file shows up in the hook matrix. Deliberately
    NOT computing the actual memory_paths.auto value: the CLI derives it from a
    project identity that measurably does not just mean "this cwd" (every card
    worktree we measured shared one directory keyed off something else), and
    guessing that derivation here would be exactly the unverified
    reconstruction CLAUDE.md's NO MONKEY PATCHES rule forbids. What CAN be
    stated from the file alone, honestly: does this surface's own deny list
    cover it."""
    raw = _read_text(sf) if sf else None
    if raw is None:
        return {"denied": False, "note": "kein settings-layer - Memory-Schreibzugriff ungeprueft"}
    try:
        deny = ((json.loads(raw).get("permissions") or {}).get("deny")) or []
    except ValueError:
        return {"denied": False, "note": "settings-Datei ist kein gueltiges JSON"}
    hit = [d for d in deny if "projects" in d and ("Write(" in d or "Edit(" in d)]
    return {"denied": bool(hit), "patterns": hit,
            "note": ("Schreiben/Editieren unter ~/.claude/projects/** (das geteilte "
                     "Auto-Memory-Verzeichnis - kein Git, keine Historie) ist verboten."
                     if hit else
                     "Kein Deny fuer ~/.claude/projects/** gefunden - diese Surface "
                     "kann das geteilte Auto-Memory-Verzeichnis des Operators "
                     "beschreiben (debt: card-shares-the-operators-auto-memory).")}


def preview(surface_key, cfg=None):
    """What a spawn on this surface ACTUALLY runs, with provenance.

    argv comes from the same builder the real spawn calls, so it cannot drift.
    The system-prompt VALUE is replaced by a marker - it is several KB and is
    shown in full in its own editor - and `brief` carries its source file, byte
    count and content hash so the owner can confirm the running text is the text
    he edited. Never raises: this is a diagnostic, and a diagnostic that dies
    when something is wrong is worthless exactly when it is needed."""
    s = _BY_KEY.get(surface_key)
    if not s:
        return {"error": "unbekannte Surface: %s" % surface_key}
    agent = s["agent"]
    m = meta(agent)
    body = brief(agent)
    apath = os.path.join(AGENTS, "%s.md" % agent)
    araw = _read_text(apath)
    sf = settings_file(agent)
    out = {
        "key": s["key"], "agent": agent, "label": s["label"],
        "builder": s["builder"], "cwd": s["cwd"],
        "brief": {
            "source": _rel(apath) if araw is not None else "built-in default (spine/registry/harness.py)",
            "exists": araw is not None,
            "file_sha256": _sha(araw) if araw is not None else "",
            # the RESOLVED text is what the process is handed - hash that too,
            # because the ask protocol is spliced in after the file is read
            "resolved_sha256": _sha(body), "resolved_chars": len(body),
            "ask_protocol": bool(m.get("ask_protocol")),
        },
        "settings_layer": {"path": _rel(sf) if sf else "", "active": bool(sf),
                           "declared": m.get("settings") or "",
                           "note": ("" if sf or not m.get("settings") else
                                    "Die Datei ist deklariert, laedt aber nicht (kein gueltiges JSON) - "
                                    "die CLI wuerde sie STILL ignorieren.")},
        "memory": _memory_isolation(sf),
        "layers": _claude_layers(m.get("setting_sources")),
        "errors": errors(),
    }
    # -- the argv, from the one real builder -------------------------------
    try:
        if surface_key == "pm":
            from cells.copilot import copilot
            argv, role_in_turn = copilot.build_argv("<model>", "<session-id>", BRIEF_ARG_MARKER)
            out["note"] = ("Der Rollen-Prompt reist als --append-system-prompt." if not role_in_turn
                           else "cmd.exe-Fallback aktiv: die Rolle wird dem Turn vorangestellt "
                                "statt als --append-system-prompt uebergeben.")
        else:
            from spine.agent import drivers
            cfg = dict(cfg or {"type": "claude"})
            cfg.setdefault("perm", "acceptEdits")
            argv = drivers.build_argv(agent, cfg, BRIEF_ARG_MARKER,
                                      session_id="<session-id>", adopted_source=None)
            out["note"] = ("--model erscheint nur, wenn die Karte ein Modell gewaehlt hat; "
                           "--resume nur ab dem zweiten Turn.")
        out["argv"] = [str(a) for a in argv]
        # THE EXEC FORM, not just the logical argv. drivers._cmd_line rewrites
        # argv[0] before spawning: a `claude.cmd` shim is replaced by the real
        # bin\claude.exe (or node + cli.js), because routing a .cmd through
        # cmd.exe mangles quoted arguments - that is what once ATE --resume and
        # made every worker start with a fresh mind. A preview that showed only
        # the pre-rewrite form would hide the single most consequential thing
        # about how this process actually starts.
        from spine.agent import drivers as _d
        exec_argv = _d._cmd_line(list(argv))
        out["exec_form"] = ("argv-list" if _d.argv_form_safe(argv[0])
                            else "cmd.exe-string (Argumente koennen verstuemmelt werden)")
        out["exec"] = ([str(a) for a in exec_argv] if isinstance(exec_argv, list)
                       else [str(exec_argv)])
        out["exec_rewritten"] = bool(out["exec"] and out["exec"][0] != out["argv"][0])
    except Exception as e:                                   # noqa: BLE001
        out["argv"] = []
        out["argv_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    # -- the hook matrix ---------------------------------------------------
    rows = []
    disabled_by = []
    for lay in out["layers"]:
        rows += _hook_rows(lay["abs"], lay["layer"], lay["included"])
        if lay["included"] and _disables_hooks(lay["abs"]):
            disabled_by.append(lay["path"])
    if sf:
        rows += _hook_rows(sf, "explicit", True)
        if _disables_hooks(sf):
            disabled_by.append(_rel(sf))
    out["hooks"] = rows
    out["hooks_active"] = sum(1 for r in rows if r.get("included"))
    # `disableAllHooks` is in the settings schema, so the owner can set it in the
    # editor - and then this matrix would list hooks that never fire. We do NOT
    # model its precedence: nothing here has been probed against the real CLI,
    # and this file's whole job is to stop being confidently wrong. So say the
    # flag is set and that the list below is therefore unreliable, rather than
    # guessing which rows it kills.
    out["hooks_disabled_by"] = disabled_by
    return out


def preview_all(cfg_for=None):
    """Every surface, previewed. `cfg_for` may map a surface key to the driver
    cfg a real spawn would use, so the preview shows that card's actual model
    instead of a placeholder."""
    return [preview(s["key"], (cfg_for or {}).get(s["key"])) for s in SURFACES]


def document():
    """Everything /harness serves: the editable documents + the previews."""
    agents, sets = [], {}
    for s in SURFACES:
        agents.append(agent_doc(s["agent"]))
        key = (meta(s["agent"]) or {}).get("settings")
        if key and key not in sets:
            sets[key] = settings_doc(key)
    return {
        "surfaces": SURFACES,
        "agents": agents,
        "settings": [sets[k] for k in sorted(sets)],
        "previews": preview_all(),
        "errors": errors(),
    }


if __name__ == "__main__":
    import sys
    if "--preview" in sys.argv:
        print(json.dumps(preview_all(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(describe(), indent=2))
