# -*- coding: utf-8 -*-
"""The harness loader - agent briefs and settings layers as DATA (`harness/`).

ARCHITECTURE.md: the harness is code, policy is data. The briefs were the
exception - what a card worker is told about itself was a string constant in
drivers.py, and the board copilot's 10 KB system prompt was a constant in
copilot.py. Both are policy: the owner may reword them without touching the
daemon. They live in harness/agents/*.md now, with harness/settings/*.json as
the settings layer each surface runs under.

THE ONE LAW OF THIS MODULE: **it can never break a spawn.**
A card is the owner's work in flight. A typo in a markdown file must not be able
to strand it. So every public function is total - it returns the built-in
default rather than raising - and the built-in defaults below are the exact text
that used to be hardcoded, so "harness/ is missing entirely" degrades to
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, "harness")
AGENTS = os.path.join(HARNESS, "agents")
SETTINGS = os.path.join(HARNESS, "settings")

_lock = threading.Lock()
_cache = {}          # path -> (stamp, parsed)
_errors = {}         # path -> message   (cleared for a path once it loads clean)

# ---------------------------------------------------------------------------
# BUILT-IN DEFAULTS - the exact constants that used to live in drivers.py /
# copilot.py. These are the floor: if harness/ is deleted, mangled, or shipped
# without, every surface still gets the brief it had before this module existed.
# ---------------------------------------------------------------------------
_DEFAULT_CARD = (
    "You are working ONE HelmDeck card in an isolated git worktree. "
    "You CAN: edit files, run commands/tests/builds, and commit on THIS branch. "
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
    # The copilot's default is EMPTY on purpose. Its prompt is 10 KB of board
    # vocabulary (every action type, the capability charter, planning
    # discipline); a truncated copy here would rot out of sync with the real
    # file and be worse than nothing. copilot.py keeps its own constant as the
    # fallback and passes it in via `default=`.
    "board-copilot": ("", {"name": "board-copilot", "settings": "copilot",
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
        import ask
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
    harness/agents/<name>.md with the fixed ask protocol spliced in.

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
    `python daemon/harness.py`."""
    out = []
    for name in sorted(_DEFAULTS):
        m = meta(name)
        path = os.path.join(AGENTS, "%s.md" % name)
        out.append({
            "name": name,
            "source": "harness/agents/%s.md" % name if os.path.exists(path) else "built-in default",
            "settings": (os.path.relpath(settings_file(name), ROOT).replace("\\", "/")
                         if settings_file(name) else ""),
            "setting_sources": m.get("setting_sources"),
            "ask_protocol": bool(m.get("ask_protocol")),
            "chars": len(brief(name)),
        })
    return {"agents": out, "errors": errors()}


if __name__ == "__main__":
    print(json.dumps(describe(), indent=2))
