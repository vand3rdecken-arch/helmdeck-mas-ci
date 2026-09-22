# -*- coding: utf-8 -*-
"""SHARED knowledge: the half of Henry's memory that belongs to the team.

Owner decision 2026-09-21: "das Ziel ist, dass ein Team gemeinsame Infos hat
aber nicht persoenliche", shared knowledge lives in the USER'S PROJECT REPO.

WHY A REPO, AND WHY ONLY FOR THIS HALF. Researched before building
(ops/docs/backlog/memory-as-knowledge-system/field-survey.md): two vendors
converged on it independently - Claude Code makes a subagent's `project`
memory the RECOMMENDED default and commits it to version control, and Devin is
deprecating its hosted Knowledge DB in favour of SKILL.md files inside the
repo. The reviewability is the point: diff, blame, review, rollback.

And the same research is why the PERSONAL half stays exactly where it is.
Anthropic keeps agent-written auto-memory out of git on purpose, machine-local,
"not shared across machines". Every failure in Letta's tracker is the same
class - git as an external, stateful, credentialed, lock-holding process
inside an automated loop: a credential dialog blocking an automated push
(letta-code#4249), ten concurrent subagents racing on .git/config.lock and all
ten desyncing (#3705), a stray temp file making `git status --porcelain`
non-empty so eight days of reflection were force-discarded (#4266), and a
headless process that exit(1)s on a conflict (#808). We are a Windows daemon
that spawns concurrent worktrees. Those are our exact conditions.

So: ONE OWNER PER NOTE, and the owner is a place. A note is either personal
(db, machine-local) or shared (a file in the project repo) - never both, so a
merge between two copies of the same fact cannot arise. Crossing the line is
an EVENT with an author (promote()), not a sync. That is Notion's shape:
private is a location, and moving between locations is the publish act.

PRECEDENCE, copied verbatim from Claude Code: "All discovered files are
concatenated into context rather than overriding each other", and the personal
file is read LAST so personal notes win. A shared note and a personal note
about the same topic never need a merge; they need an order.
"""
import io
import os
import re

SHARED_DIR = os.path.join(".helmdeck", "knowledge")
MAX_FILE_CHARS = 20000        # Letta's measured default (maxFileCharacters)
MAX_FILES = 400
INDEX_NAME = "MEMORY.md"

# A conflict marker inside a memory file is the failure mode nobody handles
# well. Letta SHIPS a skill to clean them up after the fact; Obsidian's git
# plugin loses data silently on mobile because it cannot even show them
# (obsidian-git#558). The cheap move is to never let such a file reach the
# model: if every turn folds the index, one conflicted file poisons a whole
# day of turns, silently. So we refuse it, loudly, and say which file.
_CONFLICT_RE = re.compile(r"^(<{7}|={7}|>{7})", re.M)

# Secrets must never enter this half - it is git-tracked and leaves the
# machine. Letta states the law in its own root prompt with the reason
# attached ("Memory is git-tracked and may be synced off this machine"), and
# solves it by never letting the data in rather than by scrubbing later.
_SECRET_RE = re.compile(
    r"(?:api[_-]?key|secret|password|passwd|token|bearer|private[_-]?key)"
    r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+.]{16,}", re.I)


def repo_dirs():
    """[(project_id, repo_path)] for every known project. Read fresh - a
    project added while the daemon runs must not need a restart to be seen."""
    try:
        from spine.storage import db
        out = []
        # projects_all() returns a LIST of project docs, not a mapping -
        # measured, not assumed. The first cut iterated .items() and found
        # no repos at all, which would have made the shared half look EMPTY
        # rather than broken - the exact silence this card exists to end.
        for doc in (db.projects_all() or []):
            pid = (doc or {}).get("id") or "?"
            repo = (doc or {}).get("repo")
            if repo and os.path.isdir(repo):
                out.append((pid, repo))
        return out
    except Exception:                                            # noqa: BLE001
        return []


def main_repo(path):
    """The MAIN checkout for `path`, even when `path` is a worktree.

    Borrowed from ai-memory's project_strategy="repo-root"
    (github.com/akitaonrails/ai-memory): `git rev-parse --git-common-dir`
    points at the MAIN repo's .git from inside a linked worktree, while
    --show-toplevel points at the worktree. Measured here 2026-09-21 on a real
    worktree, both readings.

    This is not cosmetic. We spawn worktrees constantly and reclaim them
    (spine reclaim_worktree / sweep_worktrees). A card that promoted a note
    while working in a worktree would have written .helmdeck/knowledge/x.md
    INTO that worktree, and the reclaim would have deleted the team's
    knowledge with it - silently, since nothing reads a directory that is
    gone. Everything here resolves through this first."""
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=path,
                           capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return path
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        return path
    if not os.path.isabs(out):
        out = os.path.join(path, out)
    root = os.path.dirname(os.path.abspath(out))
    return root if os.path.isdir(root) else path


def shared_dir(repo):
    return os.path.join(main_repo(repo), SHARED_DIR)


def _read(path):
    with io.open(path, encoding="utf-8", errors="replace") as f:
        return f.read(MAX_FILE_CHARS * 2)


def scan(repo):
    """({name: row}, [problem, ...]) for ONE repo's knowledge directory.

    Problems are returned, never raised and never swallowed: a knowledge file
    the harness refuses to load is exactly the kind of silence this whole card
    exists to end."""
    d = shared_dir(repo)
    notes, problems = {}, []
    if not os.path.isdir(d):
        return notes, problems
    try:
        names = sorted(os.listdir(d))[:MAX_FILES]
    except OSError as e:
        return notes, ["%s: nicht lesbar (%s)" % (d, e)]
    for fn in names:
        if not fn.endswith(".md") or fn == INDEX_NAME:
            continue
        full = os.path.join(d, fn)
        try:
            text = _read(full)
        except OSError as e:
            problems.append("%s: nicht lesbar (%s)" % (fn, e))
            continue
        if _CONFLICT_RE.search(text):
            problems.append("%s: MERGE-KONFLIKT im Text - nicht geladen, erst "
                            "aufloesen" % fn)
            continue
        if len(text) > MAX_FILE_CHARS:
            problems.append("%s: %d Zeichen, Grenze %d - nicht geladen"
                            % (fn, len(text), MAX_FILE_CHARS))
            continue
        notes[fn[:-3]] = {"content": text, "source": "shared", "path": full,
                          "repo": repo}
    return notes, problems


def all_shared():
    """({name: row}, [problem]) across every project. The project is carried on
    the row and rendered with the note: cross-project contamination is a
    measured failure (claude-code#91738 - facts from a legal project applied to
    an unrelated personal one), and the cheapest guard is to never show a
    shared fact without saying which project it came from."""
    notes, problems = {}, []
    for pid, repo in repo_dirs():
        got, probs = scan(repo)
        for name, row in got.items():
            row["project"] = pid
            notes[name] = row
        problems.extend(probs)
    return notes, problems


def lint(repo):
    """[problem] for a repo's knowledge dir - the gate's view. Adds the checks
    that only matter at WRITE time: the index must exist once there are notes,
    and nothing may look like a credential."""
    notes, problems = scan(repo)
    d = shared_dir(repo)
    if not os.path.isdir(d):
        return problems
    if notes and not os.path.isfile(os.path.join(d, INDEX_NAME)):
        problems.append("%s fehlt - der Index ist Pflicht, sobald es Notizen "
                        "gibt" % INDEX_NAME)
    for name, row in notes.items():
        m = _SECRET_RE.search(row.get("content") or "")
        if m:
            problems.append("%s.md: sieht aus wie ein Geheimnis (%s...) - "
                            "geteiltes Wissen verlaesst den Rechner"
                            % (name, m.group(0)[:24]))
    return problems


def _summary(text):
    """The one-line hook for the index: the note's own first real line, with
    the frontmatter block skipped WHOLE. Taking "the first line that is not
    ---" picks up `name:` out of the header, which is how the first index
    described every note by repeating its own filename."""
    body = (text or "").lstrip()
    if body.startswith("---"):
        end = body.find(chr(10) + "---", 3)
        if end != -1:
            body = body[end + 4:]
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line
    return ""


def write_index(repo):
    """Rebuild MEMORY.md from the files. DERIVED, like the personal index -
    the whole reason the personal one froze for five days was that a model
    maintained it by hand."""
    notes, _ = scan(repo)
    d = shared_dir(repo)
    os.makedirs(d, exist_ok=True)
    lines = ["# Geteiltes Wissen", "",
             "Automatisch erzeugt. Nicht von Hand pflegen.", ""]
    for name in sorted(notes):
        first = _summary(notes[name].get("content") or "")
        lines.append("- [%s](%s.md) - %s" % (name, name, first[:160]))
    with io.open(os.path.join(d, INDEX_NAME), "w", encoding="utf-8",
                 newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return len(notes)


def promote(name, repo, actor="henry"):
    """Move ONE personal note into a project's shared knowledge.

    MOVE, not copy: the db row is deleted. Two copies of one fact in two
    stores is the split brain this card started from, and "one owner per note"
    is the only conflict strategy that actually works - it makes a merge
    impossible rather than resolvable. Returns the written path.

    It does NOT commit. A promotion is a normal working-tree change that goes
    through the repo's own review path like any other edit; a memory store
    that commits on its own behalf is the automated-git failure class we
    deliberately stayed out of."""
    from spine.storage import db, events
    row = (db.memory_all() or {}).get(name)
    if not row:
        raise KeyError("keine persoenliche Notiz mit dem Namen %r" % name)
    content = row.get("content") or ""
    if _SECRET_RE.search(content):
        raise ValueError("enthaelt etwas, das wie ein Geheimnis aussieht - "
                         "geteiltes Wissen verlaesst den Rechner")
    if _CONFLICT_RE.search(content):
        raise ValueError("enthaelt Merge-Konfliktmarkierungen")
    if len(content) > MAX_FILE_CHARS:
        raise ValueError("%d Zeichen, Grenze %d" % (len(content), MAX_FILE_CHARS))
    d = shared_dir(repo)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.md" % name)
    header = ("---\nname: %s\nkind: %s\nfrom: %s\nshared_at: %s\n---\n\n"
              % (name, row.get("kind") or "project", row.get("source") or "-",
                 (row.get("updated_at") or "")[:10]))
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + content.strip() + "\n")
    db.memory_delete(name)
    write_index(repo)
    events.emit("memory", "-", op="promote", actor=actor, name=name, repo=repo)
    return path
