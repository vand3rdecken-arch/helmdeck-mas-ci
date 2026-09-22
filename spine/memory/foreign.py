# -*- coding: utf-8 -*-
"""Bring an existing agent memory INTO HelmDeck.

Owner 2026-09-22: "if users only used claude or other system let him pull this
from other systems as well". Someone arriving from Claude Code, Cursor, Codex
or Windsurf already has months of accumulated notes and rules. Asking them to
start empty is asking them to throw that away, and they will simply not
switch.

THE SHAPE IS BORROWED, NOT INVENTED. Two shipped products already do exactly
this and their adapter lists are the documented prior art
(ops/docs/backlog/memory-as-knowledge-system/field-survey.md):
  - Amp offers to generate its AGENTS.md "by reading your project and other
    agents' files (.cursorrules, .cursor/rules, .windsurfrules, .clinerules,
    CLAUDE.md, .github/copilot-instructions.md)".
  - Devin auto-ingests .rules, .mdc, .cursorrules, .windsurf, CLAUDE.md and
    AGENTS.md, but deliberately "won't automatically pull in more general file
    types like .md" - scope by KNOWN LOCATION, never by extension.
And the Data Transfer Project's shape: one adapter per source, each converting
into ONE shared model, so a new source is an adapter and not a new pipeline.

THREE RULES, each earned the hard way this week.

1. DISCOVERY REPORTS WHAT IT DID NOT FIND. A source that is absent says so by
   name. The failure this whole card began with was a lookup that returned
   empty and got read as "there is nothing" - an importer that silently finds
   nothing is the same lie at install time, when the user has the least
   ability to notice.

2. NOTHING IS OVERWRITTEN. A name that already exists is SKIPPED and named in
   the report. An import runs on a machine whose memory may already matter;
   merge semantics for prose are a research problem (Signal and WhatsApp both
   refuse it) and we refuse it too.

3. PROVENANCE SURVIVES THE CROSSING. Every imported note keeps where it came
   from in `source`, and its `kind` reflects WHO wrote it: notes the owner's
   own agent wrote about him rank owner-fact; rules and skills are project
   instructions, not facts about the world.
"""
import io
import os
import re

MAX_NOTE = 20000
SKIP_DIRS = ("node_modules", ".git", "__pycache__", "build", "dist")


def _home():
    return os.path.expanduser("~")


def _read(path, limit=MAX_NOTE * 2):
    try:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


def _slug(text, fallback="note"):
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "")).strip("-").lower()
    return (s or fallback)[:60]


# ---------------------------------------------------------------------------
# One entry per known source. `find` returns [{id,label,kind,path,count,note}].
# A source that exists but is EMPTY is still returned, with count 0 - "you have
# Cursor rules but the folder is empty" is information; silence is not.

def _claude_memory(repo):
    """The CLI's own auto-memory, per project. The richest source there is:
    these are notes the owner's agent wrote about the owner."""
    base = os.path.join(_home(), ".claude", "projects")
    out = []
    if not os.path.isdir(base):
        return out
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for d in names:
        mem = os.path.join(base, d, "memory")
        if not os.path.isdir(mem):
            continue
        try:
            n = len([f for f in os.listdir(mem)
                     if f.endswith(".md") and f != "MEMORY.md"])
        except OSError:
            continue
        if not n or _throwaway(d):
            continue
        # THE PROJECT IS THE HEADLINE, the tool is the footnote. Owner, seeing
        # the first build: "warum gibt es 4 mal claude code importieren". Claude
        # Code keeps ONE memory PER PROJECT DIRECTORY, so five rows are five
        # different memories - but labelled by the tool they all read as the
        # same offer repeated, and the thing that actually distinguishes them
        # sat in grey underneath. Swapped.
        out.append({"id": "claude-memory:" + d, "label": _project_label(d),
                    "kind": "owner-fact", "path": mem, "count": n,
                    "note": "Claude Code"})
    return out


# Temp and worktree project dirs are SCRATCH, not memory: a sandbox daemon, an
# e2e shim, a card's worktree. Offering "1 Eintrag aus AppData-Local-Temp-hd-
# e2e-shim" next to "91 Eintraege aus swarmdeck" gives both the same weight and
# buries the one that matters. Matched on the path shape the CLI itself encodes.
_THROWAWAY = ("appdata-local-temp", "-worktrees-", "-tmp-", "appdata-roaming-temp")


def _throwaway(slug):
    low = slug.casefold()
    return any(m in low for m in _THROWAWAY)


def _project_label(slug):
    """A SHORT, HONEST key - not a reconstructed path.

    The CLI flattens both path separators AND hyphens into "-", so a slug is
    genuinely ambiguous: "Downloads-glass-crud-harness" could be three folders
    or one folder named glass-crud-harness. The first cut split on "-" and
    confidently produced "crud/harness", which is a made-up path - the same
    reconstruct-instead-of-ask mistake this whole card is about.

    So: strip the prefix we can DERIVE (the user's own home directory, which
    we know) and show the rest verbatim. It is the CLI's own project key,
    truthfully, and short enough to read on a phone."""
    prefix = _home().replace(":", "").replace(os.sep, "-").replace("/", "-")
    prefix = prefix.replace(" ", "-") + "-"
    s = slug
    for cand in (prefix, prefix.replace("C-", "C--", 1)):
        if s.lower().startswith(cand.lower()):
            s = s[len(cand):]
            break
    s = s.strip("-") or slug
    return s if len(s) <= 46 else s[:22] + "…" + s[-22:]


def _md_rules(repo):
    """Instruction files, at the exact KNOWN names both Amp and Devin scan.
    Never a bare *.md sweep - that is how an importer swallows a README."""
    names = ("CLAUDE.md", "AGENTS.md", ".cursorrules", ".windsurfrules",
             ".clinerules", os.path.join(".github", "copilot-instructions.md"))
    out = []
    roots = [(_home(), os.path.join(".claude", "CLAUDE.md"), "persönlich")]
    for root, rel, where in roots:
        p = os.path.join(root, rel)
        if os.path.isfile(p) and os.path.getsize(p) > 32:
            out.append({"id": "rules:user-claude-md", "label": "CLAUDE.md (%s)" % where,
                        "kind": "project", "path": p, "count": 1, "note": rel})
    if repo:
        for name in names:
            p = os.path.join(repo, name)
            if os.path.isfile(p) and os.path.getsize(p) > 32:
                out.append({"id": "rules:" + _slug(name), "label": name,
                            "kind": "project", "path": p, "count": 1,
                            "note": "im Projekt"})
    return out


def _skills(repo):
    """SKILL.md files - the convention Devin and Amp both settled on. Scanned
    at the documented locations only."""
    out = []
    spots = [(os.path.join(_home(), ".agents", "skills"), "persönlich")]
    if repo:
        spots += [(os.path.join(repo, ".agents", "skills"), "Projekt"),
                  (os.path.join(repo, ".claude", "skills"), "Projekt")]
    for base, where in spots:
        if not os.path.isdir(base):
            continue
        n = 0
        for entry in sorted(os.listdir(base))[:500]:
            if os.path.isfile(os.path.join(base, entry, "SKILL.md")):
                n += 1
        if n:
            out.append({"id": "skills:" + _slug(base), "label": "Skills (%s)" % where,
                        "kind": "project", "path": base, "count": n,
                        "note": base})
    return out


def _dir_of_md(source_id, label, path, kind, note):
    if not os.path.isdir(path):
        return []
    try:
        n = len([f for f in os.listdir(path) if f.endswith(".md")])
    except OSError:
        return []
    return [{"id": source_id, "label": label, "kind": kind, "path": path,
             "count": n, "note": note}]


def _codex(repo):
    return _dir_of_md("codex-memories", "Codex Memories",
                      os.path.join(_home(), ".codex", "memories"),
                      "owner-fact", "~/.codex/memories")


def _windsurf(repo):
    return _dir_of_md("windsurf-memories", "Windsurf/Cascade Memories",
                      os.path.join(_home(), ".codeium", "windsurf", "memories"),
                      "owner-fact", "~/.codeium/windsurf/memories")


def _cursor(repo):
    out = []
    for base, where in ((os.path.join(_home(), ".cursor", "rules"), "persönlich"),
                        (os.path.join(repo or "", ".cursor", "rules"), "Projekt")):
        if not base or not os.path.isdir(base):
            continue
        try:
            n = len([f for f in os.listdir(base) if f.endswith((".mdc", ".md"))])
        except OSError:
            continue
        out.append({"id": "cursor-rules:" + _slug(where), "label": "Cursor Rules (%s)" % where,
                    "kind": "project", "path": base, "count": n, "note": base})
    return out


def _ai_memory(repo):
    """akitaonrails/ai-memory keeps a markdown wiki as its source of truth."""
    out = []
    for base in (os.path.join(_home(), ".ai-memory", "wiki"),
                 os.path.join(repo or "", "wiki")):
        if base and os.path.isdir(base) and os.path.isfile(os.path.join(base, "MEMORY.md")):
            n = len([f for f in os.listdir(base) if f.endswith(".md")])
            out.append({"id": "ai-memory:" + _slug(base), "label": "ai-memory Wiki",
                        "kind": "owner-fact", "path": base, "count": n, "note": base})
    return out


ADAPTERS = (
    ("claude-memory", "Claude Code", _claude_memory),
    ("rules", "Regeldateien", _md_rules),
    ("skills", "Skills", _skills),
    ("codex", "Codex", _codex),
    ("windsurf", "Windsurf", _windsurf),
    ("cursor", "Cursor", _cursor),
    ("ai-memory", "ai-memory", _ai_memory),
)


def discover(repo=None):
    """({sources}, {absent}) - what is here, and what is NOT, by name.

    The second half is the point. A user who used Cursor and sees no mention
    of Cursor cannot tell whether we looked and found nothing or never looked
    at all - and at install time he has no way to check."""
    found, absent = [], []
    for key, label, fn in ADAPTERS:
        try:
            got = fn(repo) or []
        except Exception as e:                                   # noqa: BLE001
            absent.append({"id": key, "label": label,
                           "why": "Fehler beim Suchen: %s" % str(e)[:80]})
            continue
        if got:
            found.extend(got)
        else:
            # "nothing found" and "could not look" are DIFFERENT answers, and
            # conflating them is the exact failure this card exists to end.
            # Without a project, the project-scoped half was never searched.
            project_scoped = key in ("rules", "cursor", "ai-memory")
            why = ("nichts gefunden an den bekannten Orten"
                   if (repo or not project_scoped) else
                   "kein Projekt gewählt, im Projekt wurde nicht gesucht")
            absent.append({"id": key, "label": label, "why": why})
    return found, absent


def _notes_from(src):
    """[(name, content)] for one source. Pure reading - no db, so a preview
    costs exactly what an import costs and cannot diverge from it."""
    p = src["path"]
    out = []
    if src["id"].startswith(("rules:",)):
        body = _read(p)
        if body:
            out.append((_slug(os.path.basename(p).replace(".md", "")) or "rules", body))
        return out
    if src["id"].startswith("skills:"):
        for entry in sorted(os.listdir(p))[:500]:
            f = os.path.join(p, entry, "SKILL.md")
            if os.path.isfile(f):
                body = _read(f)
                if body:
                    out.append(("skill-" + _slug(entry), body))
        return out
    # every remaining adapter is a flat directory of markdown
    try:
        names = sorted(os.listdir(p))
    except OSError:
        return out
    for fn in names[:500]:
        if not fn.endswith((".md", ".mdc")) or fn == "MEMORY.md":
            continue
        body = _read(os.path.join(p, fn))
        if body:
            out.append((_slug(fn.rsplit(".", 1)[0]), body))
    return out


def preview(src):
    """[(name, chars, collides)] - exactly what an import would do, computed
    the same way. A preview that runs different code than the import is a
    promise nobody checked."""
    from spine.storage import db
    existing = set(db.memory_all() or {})
    out = []
    for name, body in _notes_from(src):
        out.append((name, len(body), name in existing))
    return out


def import_source(src, actor="import", dry_run=False):
    """{imported, skipped, too_long} - and NOTHING is overwritten.

    A colliding name is skipped and reported by name. Merging two prose notes
    about one topic is the problem neither Signal nor WhatsApp will solve for
    their users, and we are not better placed than they are."""
    from spine.storage import db, events
    existing = set(db.memory_all() or {})
    res = {"imported": [], "skipped": [], "too_long": []}
    for name, body in _notes_from(src):
        if name in existing:
            res["skipped"].append(name)
            continue
        if len(body) > MAX_NOTE:
            res["too_long"].append(name)
            continue
        if not dry_run:
            db.memory_put(name, body.strip(), actor=actor,
                          kind=src.get("kind") or "project",
                          source="import:%s" % src["id"])
        res["imported"].append(name)
        existing.add(name)
    if not dry_run and res["imported"]:
        try:
            events.emit("memory", "-", op="import", actor=actor,
                        src=src["id"], n=len(res["imported"]),
                        skipped=len(res["skipped"]))
        except Exception:                                        # noqa: BLE001
            pass
    return res

# ---------------------------------------------------------------------------
# THE AGENT LOOKS TOO. Owner 2026-09-22: "einfach Claude Code setup sagen, hey
# schaue welche harness gibt es noch auf diesen PC. Code ist anfaellig
# gegenueber bugs".
#
# He is right about the part that rots. Of the seven adapters above, three were
# checked against real files on this machine; four (Codex, Windsurf, Cursor,
# ai-memory) are read from someone else's documentation. Those will go stale
# SILENTLY - when a vendor renames a folder, the adapter reports "nothing found
# at the known locations" and nobody learns that the locations are no longer
# the known ones. That is this card's own failure mode, in slow motion.
#
# And it is not a new idea here: the onboarding control plane already says, in
# its own source, that rather than hand-rolling an installer per dependency it
# describes the goal and lets the agent do it. This is the same move for
# discovery.
#
# BUT THE AGENT ONLY LOOKS. It returns CANDIDATES; code verifies every one of
# them before anything is offered, because an LLM naming a path is a claim and
# a path that exists is a fact. Three bounds, all enforced here:
#   * time      - a hard timeout; onboarding must always terminate
#   * scope     - named roots, never "the whole disk"
#   * structure - JSON in, validated in code, discarded loudly when it is not
AGENT_TIMEOUT_S = 150
AGENT_MAX_HITS = 12

_AGENT_PROMPT = """Hier sind Konfigurationsordner im Heimatverzeichnis eines
Entwicklers:
%s

Welche davon gehoeren zu einem Coding-Assistenten, der Notizen, Regeln oder
Skills des Nutzers speichert (z.B. Claude Code, Cursor, Codex, Windsurf,
Cline, Amp, Gemini CLI, Continue)?

Antworte NUR mit einem JSON-Array, ohne Prosa, ohne Code-Fence:
[{"dir": "<genau der Ordnername aus der Liste>", "tool": "<Produktname>"}]
Leeres Array [], wenn keiner passt."""

# Directory names that mean "the user's notes live here", and names that mean
# the opposite. Measured, not guessed: the unfiltered version offered
# .cursor/extensions/<any-extension> and .gemini/antigravity-cli/cache.
_MEMORY_NAMES = frozenset((
    "memory", "memories", "rules", "notes", "knowledge", "skills", "wiki",
    "prompts", "instructions", "agents", "commands"))
_NOT_MEMORY = frozenset((
    "cache", "caches", "extensions", "logs", "log", "tmp", "temp", "bin",
    "backups", "history", "sessions", "projects", "statsig", "shell-snapshots"))


def _config_dirs():
    """The cheap half, done by CODE: every dotted config directory in the home
    dir. Instant, free, and it cannot name a path that is not there."""
    h = _home()
    out = []
    try:
        for e in sorted(os.listdir(h)):
            if e.startswith(".") and os.path.isdir(os.path.join(h, e)):
                out.append(e)
    except OSError:
        pass
    return out[:80]


def _memory_dirs_under(root, depth=2):
    """Markdown-bearing directories under a tool's config dir. A tool folder
    is not itself the memory; the notes sit in memory/, rules/, notes/ or
    similar, and which one it is differs per vendor - so we look rather than
    assume, but only two levels down and never into build output."""
    hits = []
    root = os.path.abspath(root)
    for base, dirs, files in os.walk(root):
        rel = os.path.relpath(base, root)
        if rel != "." and rel.count(os.sep) >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs
                   if d not in SKIP_DIRS and d.casefold() not in _NOT_MEMORY
                   and not d.startswith(".")][:40]
        n = len([f for f in files if f.endswith((".md", ".mdc"))])
        # A directory full of markdown is not automatically a memory: measured
        # on this machine, the greedy version returned VS Code extension
        # READMEs under .cursor/extensions and a .gemini cache as "memory".
        # The name is the cheap signal, and getting it wrong here means
        # offering someone his own editor's changelog as his notes.
        if n and (rel == "." or os.path.basename(base).casefold() in _MEMORY_NAMES):
            hits.append((base, n))
    hits.sort(key=lambda h: -h[1])
    return hits[:4]


def discover_with_agent(known_paths=(), timeout=AGENT_TIMEOUT_S):
    """([source], [problem]) - tools the ADAPTERS do not know about.

    Code lists the config dirs, the model says which are coding assistants,
    then code looks inside and verifies. Best-effort by contract: no CLI, a
    refusal, a timeout or unparsable output all return an empty list plus a
    problem line that says WHICH of those happened. Onboarding must never hang
    or fail here - the adapters already cover the common cases."""
    import json
    import subprocess
    entries = _config_dirs()
    if not entries:
        return [], ["keine Konfigurationsordner im Heimatverzeichnis"]
    try:
        from spine.agent import drivers
        from spine.agent.spawnenv import tool_path
    except Exception as e:                                       # noqa: BLE001
        return [], ["Agentensuche nicht moeglich: %s" % str(e)[:90]]
    prompt = _AGENT_PROMPT % "\n".join("- " + e for e in entries)
    argv = [drivers.CLAUDE, "-p", prompt, "--permission-mode", "plan"]
    try:
        r = subprocess.run(drivers._cmd_line(argv), cwd=_home(), env=tool_path(),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return [], ["Agentensuche nach %ds abgebrochen" % timeout]
    except Exception as e:                                       # noqa: BLE001
        return [], ["Agent nicht startbar: %s" % str(e)[:90]]
    raw = (r.stdout or "").strip()
    # A REFUSAL and a bad answer are different facts. The first framing of this
    # prompt read like host reconnaissance and was refused outright; reporting
    # that as "unreadable JSON" would have sent someone hunting the parser.
    if raw.startswith("API Error") or "safeguards flagged" in raw[:300]:
        return [], ["Das Modell hat die Anfrage abgelehnt: %s"
                    % raw.splitlines()[0][:150]]
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return [], ["Agent antwortete nicht mit JSON (%d Zeichen): %s"
                    % (len(raw), raw[:110])]
    try:
        picks = json.loads(raw[start:end + 1])
    except ValueError as e:
        return [], ["Agent-JSON unlesbar: %s" % str(e)[:80]]
    if not isinstance(picks, list):
        return [], ["Agent-JSON ist keine Liste"]

    known = {os.path.normcase(os.path.abspath(p)) for p in known_paths}
    out, problems, seen = [], [], set()
    allowed = set(entries)
    for p in picks[:30]:
        if not isinstance(p, dict):
            continue
        name = str(p.get("dir") or "")
        # The model may only pick FROM the list it was given. Anything else is
        # invented, and an invented path is the one thing this whole card is
        # about.
        if name not in allowed:
            problems.append("nicht aus der Liste, verworfen: %r" % name[:40])
            continue
        tool = str(p.get("tool") or name)[:40]
        for path, n in _memory_dirs_under(os.path.join(_home(), name)):
            key = os.path.normcase(os.path.abspath(path))
            if key in known or key in seen:
                continue
            low = path.casefold()
            if any(m in low for m in _THROWAWAY):
                continue
            seen.add(key)
            out.append({"id": "agent:" + _slug(path), "label": tool,
                        # An agent-found store is a CANDIDATE, never assumed to
                        # be the owner speaking - only adapters we verified
                        # ourselves claim owner-fact.
                        "kind": "project", "path": path, "count": n,
                        "note": "gefunden von Claude in %s" % name,
                        "via": "agent"})
            if len(out) >= AGENT_MAX_HITS:
                return out, problems
    return out, problems
