# -*- coding: utf-8 -*-
"""Henry's memory - DB-authoritative (henry-memory-db-authority card).

Owner review 2026-09-11: memory is GOVERNANCE CONFIG, not runtime litter - a
saved note rides in every board turn via digest() and shapes Henry's behaviour
like the brief does. The db table (spine.storage.db memory_all/put/delete) is
therefore the store of record, exactly like policy_doc.

Owner follow-up 2026-09-11: the first cut of this kept a disposable READ
CACHE directory (daemon/content/henry_memory/) so Henry's own Read tool
could open a full note on demand. Owner decree: no folder at all, even a
disposable one - a directory that looks identical before and after a
"the db is now authoritative" refactor is a skeleton in the closet, not a
fix someone can SEE landed. ops/tools/henry_memory_get.py replaces it: a
read-only script Henry calls through the same Bash-allowlist pattern as his
existing board_state.py/loop_state.py tools, querying the db directly. No
filesystem surface for memory exists at all now, so nothing can plant a file
that becomes a standing instruction - the old _fold_memory_to_db() defect
this card started from (dir -> db, deleting db rows with no matching file)
is structurally impossible, not just guarded against.

WRITE PATH: a sentinel protocol, not a file write. Henry ends a turn (any
board turn, not just the pre-compaction save turn) with

    <memory-save name="short-kebab-title">
    the fact, and why it matters
    </memory-save>
    <memory-delete name="short-kebab-title"/>

parse() is STRICT (same discipline as spine/ops/ask.py, the ASK sentinel this
is modelled on): a block whose name or content fails validation is REJECTED
and stripped from the visible reply, NEVER guessed at or best-effort-repaired.
Provenance is structural - a note exists in the db only because Henry's own
authenticated turn said so, and every accepted mutation gets its own event."""
import datetime
import io
import os
import re

MAX_NAME_LEN = 60
MAX_CONTENT_LEN = 8000
MAX_BLOCKS = 30           # a turn cannot mutate an unbounded number of notes
# The index rides whole. It was cut at 4000 chars while the live index had
# grown to 5767 (2026-09-16): the newest ~10 entries - the ones Henry appends
# at the END - were the ones that never reached him, so a note he had just
# saved was invisible the next turn. ~4k tokens is the ceiling for an INDEX;
# past it the fix is a shorter index (Henry's own SAVE turn tidies it), not a
# silent tail-cut.
DIGEST_MAX = 16000

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,%d}$" % (MAX_NAME_LEN - 1))

# ONE regex, both tags, so blocks are handled in the order they actually
# appear in the reply - a save immediately followed by a delete of the SAME
# name is a real (if odd) sequence and must apply in that order, not be
# reordered by parsing saves first.
_BLOCK_RE = re.compile(
    r'<memory-save\s+name="([^"<>]*)"\s*>(.*?)</memory-save>'
    r'|<memory-delete\s+name="([^"<>]*)"\s*/?>',
    re.S | re.I)


# The rejects of the MOST RECENT parse, read back by the caller that is about
# to apply() them so the next turn can SAY what was dropped (feedback()). One
# writer, one reader, same call chain - not a cache anything else may consult.
_last_rejects = []


def last_rejects():
    return list(_last_rejects)


def parse(text):
    """(cleaned_text, mutations). `mutations` is a list of
    {"op": "save", "name", "content"} / {"op": "delete", "name"} dicts, in the
    order the blocks appeared. Every recognized block is stripped from
    `cleaned_text` regardless of validity - the owner must never see raw
    sentinel markup in the chat. A block whose name or content fails
    validation is dropped (not applied) and reported as one reject event;
    it is NEVER salvaged with a guessed name or truncated content."""
    if not isinstance(text, str) or "<memory-" not in text.lower():
        return text, []
    muts, rejects = [], []

    def _sub(m):
        if len(muts) + len(rejects) >= MAX_BLOCKS:
            return ""                    # bounded - extra blocks are dropped silently
        if m.group(1) is not None:
            name, content = m.group(1).strip(), m.group(2).strip()
            if _NAME_RE.match(name) and content and len(content) <= MAX_CONTENT_LEN:
                muts.append({"op": "save", "name": name, "content": content})
            else:
                rejects.append(name or "?")
        else:
            name = (m.group(3) or "").strip()
            if _NAME_RE.match(name):
                muts.append({"op": "delete", "name": name})
            else:
                rejects.append(name or "?")
        return ""

    cleaned = _BLOCK_RE.sub(_sub, text).strip()
    _last_rejects[:] = rejects[:MAX_BLOCKS]
    if rejects:
        try:
            from spine.storage import events
            events.emit("memory", "-", op="reject", actor="henry", names=rejects[:MAX_BLOCKS])
        except Exception:                                        # noqa: BLE001
            pass
    return cleaned, muts


def apply(mutations, actor="henry"):
    """Execute parsed mutations against the db - ONE event per mutation
    (README phase 1: an audit trail for config that changes Henry's own
    behaviour, the same discipline settings.save_settings already has).
    Best-effort per mutation: one bad row must not lose the rest of the
    batch. Returns the mutations that actually landed."""
    from spine.storage import db, events
    done = []
    for m in mutations[:MAX_BLOCKS]:
        try:
            if m["op"] == "save":
                db.memory_put(m["name"], m["content"], actor=actor)
                events.emit("memory", "-", op="save", actor=actor, name=m["name"])
            else:
                db.memory_delete(m["name"])
                events.emit("memory", "-", op="delete", actor=actor, name=m["name"])
            done.append(m)
        except Exception as e:                                    # noqa: BLE001
            print("copilot: memory mutation failed -", m.get("name"), str(e)[:200])
    return done


# ---------------------------------------------------------------------------
# THE SECOND STORE: the claude CLI's own auto-memory directory.
#
# Owner decree 2026-09-20 ("alle Infos zu Claude und db sollten zugaenglich
# sein"), after Henry told the owner three times that Jev has no text API: the
# correction sat in the CLI's auto-memory (jev-browser-verdict.md) while his
# own db held the wrong card report, and NOTHING read both. Two stores with
# overlapping facts and no reconciliation is the split brain debt
# henry-memory-parallel-to-cli-automemory was opened for.
#
# THE PATH IS OBSERVED, NEVER DERIVED. That debt stayed open on purpose
# because guessing how the CLI turns a cwd into a project slug is exactly the
# unverified reconstruction CLAUDE.md forbids - and the guess would have been
# WRONG: measured, every surface resolves memory_paths.auto to the MAIN repo
# slug, not the spawn's own cwd (Henry's cwd is <repo>/daemon and his notes
# are not under a -daemon slug). So we take the CLI's own word for it: the
# init event of every turn carries memory_paths.auto, folded here at EVENT
# TIME by observe_auto_dir() (drivers.turn_active / sessions.record_bg
# precedent). Never observed yet = the store is simply absent, said out loud
# in the digest rather than papered over with a plausible path.
#
# READ-ONLY, deliberately. card-shares-the-operators-auto-memory measured that
# this directory is the OPERATOR'S personal one, shared by every surface and
# not git-backed; the paid fix made it unwritable for spawned agents and that
# stands. Henry reads it and may DISAGREE with it in his own note; he cannot
# silently rewrite the owner's memory.
AUTO_DOC = "memory_auto_dir"
AUTO_MAX_FILES = 400
_FM_RE = re.compile("^---[ \t]*\n(.*?)\n---[ \t]*\n", re.S)


def observe_auto_dir(ev):
    """Fold ONE stream event: if it is the CLI's init frame and it reports a
    memory_paths.auto, record it. Idempotent and cheap (a write only when the
    value actually changes), best-effort by contract - the memory store must
    never be able to break a turn."""
    try:
        if not isinstance(ev, dict) or ev.get("type") != "system":
            return
        path = ((ev.get("memory_paths") or {}) or {}).get("auto")
        if not isinstance(path, str) or not path.strip():
            return
        path = path.strip()
        from spine.storage import db
        cur = db.doc_get(AUTO_DOC) or {}
        if cur.get("path") == path:
            return
        db.doc_put(AUTO_DOC, {"path": path, "observed_at": _now_iso(),
                              "session": ev.get("session_id")})
    except Exception:                                            # noqa: BLE001
        pass


def _now_iso():
    import datetime
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def auto_dir():
    """The observed auto-memory directory, or None if the CLI has not told us
    one yet (or the directory has since gone). No fallback, no guess."""
    try:
        from spine.storage import db
        path = (db.doc_get(AUTO_DOC) or {}).get("path")
    except Exception:                                            # noqa: BLE001
        return None
    if path and os.path.isdir(path):
        return path
    return None


def _auto_meta(text, fallback_name):
    """(name, description) from a note's frontmatter, falling back to the file
    name and the first non-empty body line. Tolerant on purpose: this is a
    foreign format we read, not one we enforce."""
    name, desc = fallback_name, ""
    m = _FM_RE.match(text or "")
    body = (text or "")[m.end():] if m else (text or "")
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("name:") and line[5:].strip():
                name = line[5:].strip()
            elif line.startswith("description:") and not desc:
                desc = line[12:].strip().strip('"')
    if not desc:
        desc = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    return name, desc


def auto_notes():
    """{name: row} read from the observed directory, same row shape as the db
    (content / updated_at) plus source="cli". Empty dict when no directory has
    been observed - an honest empty, never a fabricated one."""
    d = auto_dir()
    if not d:
        return {}
    out = {}
    try:
        names = sorted(os.listdir(d))[:AUTO_MAX_FILES]
    except OSError:
        return {}
    for fn in names:
        if not fn.endswith(".md") or fn == "MEMORY.md":
            continue
        full = os.path.join(d, fn)
        try:
            with io.open(full, encoding="utf-8", errors="replace") as f:
                text = f.read(MAX_CONTENT_LEN * 2)
            ts = datetime.datetime.fromtimestamp(os.path.getmtime(full))
        except OSError:
            continue
        name, desc = _auto_meta(text, fn[:-3])
        out[name] = {"content": text, "description": desc, "source": "cli",
                     "updated_at": ts.replace(microsecond=0).isoformat(),
                     "path": full}
    return out


def db_notes():
    """{name: row} from the store of record, tagged with its source and with
    the description line lifted out of the note's own frontmatter when it has
    one (Henry writes both shapes)."""
    try:
        from spine.storage import db
        raw = db.memory_all()
    except Exception:                                            # noqa: BLE001
        return {}
    out = {}
    for name, row in raw.items():
        if name == "MEMORY":
            continue          # the hand-written index is superseded by digest()
        content = row.get("content") or ""
        _n, desc = _auto_meta(content, name)
        out[name] = {"content": content, "description": desc, "source": "db",
                     "updated_at": row.get("updated_at") or ""}
    return out


def all_notes():
    """BOTH stores in one dict, db first so Henry's own note wins a name
    collision - but the loser is not dropped silently: the surviving row
    carries also_in="cli" so a disagreement is visible instead of implicit."""
    merged = dict(auto_notes())
    for name, row in db_notes().items():
        if name in merged:
            row = dict(row, also_in="cli", cli_updated_at=merged[name].get("updated_at"))
        merged[name] = row
    return merged


def digest(limit=None):
    """The memory INDEX for the turn - DERIVED from both stores, never the
    notes themselves (progressive disclosure: a full note is fetched only when
    it turns out to matter).

    It used to be a NOTE Henry hand-maintained under the name "MEMORY", and
    that froze on 2026-09-15: the index grew past MAX_CONTENT_LEN, every
    rewrite was rejected, parse() drops a bad block SILENTLY, and so for five
    days he read a 40-line index of 115 notes and concluded he had never been
    told things he had written down himself. An index is a VIEW over the
    notes; computing it is the only shape that cannot rot (CLAUDE.md: derived
    and verified, mutated at exactly one owner). Henry no longer writes it and
    structurally cannot break it again.

    One line per note: name, its own description/first line, the date, and -
    only when it is not the db - where it lives. Sorted newest first, because
    a truncation must drop the stalest entry, not the one he just saved."""
    rows = all_notes()
    if not rows:
        return ""
    lines = []
    for name, row in sorted(rows.items(),
                            key=lambda nr: nr[1].get("updated_at") or "",
                            reverse=True):
        mark = "" if row.get("source") == "db" else " [cli]"
        if row.get("also_in"):
            mark = " [auch cli]"
        desc = " ".join((row.get("description") or "").split())[:180]
        lines.append("- %s (%s)%s%s" % (name, (row.get("updated_at") or "")[:10],
                                        mark, (" - " + desc) if desc else ""))
    body = "\n".join(lines)[:(limit or DIGEST_MAX)]
    return ("\n\nDEIN GEDAECHTNIS (%d Notizen, Index automatisch aus beiden "
            "Speichern abgeleitet - db und dem Auto-Memory der CLI [cli]. "
            "Volle Notiz mit `py -3.12 ops/tools/henry_memory_get.py get "
            "<name>`, Suche ueber ALLE Notizen mit `... find <begriff>` - "
            "benutze find, BEVOR du sagst, dass du etwas nicht weisst):\n%s"
            % (len(rows), body))


def feedback(muts, rejects):
    """ONE line for the NEXT turn saying what the last one actually stored.

    A write path whose only failure signal is an event nobody reads is not a
    write path (owner, 2026-09-20: "warum war er confidently wrong"). Henry
    could not tell a rejected save from a successful one, so he kept believing
    he had recorded something he had not. Now every save, delete and reject
    comes back in prose."""
    if not muts and not rejects:
        return ""
    parts = []
    saved = [m["name"] for m in (muts or []) if m.get("op") == "save"]
    gone = [m["name"] for m in (muts or []) if m.get("op") == "delete"]
    if saved:
        parts.append("gespeichert: " + ", ".join(saved[:8]))
    if gone:
        parts.append("geloescht: " + ", ".join(gone[:8]))
    if rejects:
        parts.append("VERWORFEN (Name oder Laenge ungueltig, NICHT gespeichert - "
                     "kuerzer neu schreiben): " + ", ".join(rejects[:8]))
    return "\n\nLETZTER SPEICHERVORGANG - " + "; ".join(parts)


# The dedicated pre-compaction save turn (copilot._save_memory): ONE turn to
# persist what matters before the verdichtung, resumed on the SAME session so
# it is informed by the full, not-yet-compacted history. The sentinel format
# itself is taught once, in board-copilot.md, so Henry already knows it from
# turn one - this just tells him to use it NOW, comprehensively.
SAVE_PROMPT = (
    "SYSTEM-WARTUNG, keine Owner-Nachricht - antworte NICHT im Chat-Ton und "
    "stelle keine Rueckfrage.\n\n"
    "Dein Verlauf wird gleich verdichtet. Was jetzt nicht gespeichert ist, "
    "steht dir danach nur noch als Zusammenfassung zur Verfuegung.\n\n"
    "Schreib JETZT die dauerhaften Fakten aus diesem Gespraech als "
    "<memory-save>/<memory-delete> Bloecke (Format: deine eigene Anweisung "
    "zum Gedaechtnis) - eine Notiz pro Sache, danach den Index 'MEMORY' "
    "nachziehen. Dauerhaft = Owner-Entscheidungen, Vorlieben, laufende "
    "Vorhaben, Zusagen, offene Fragen, harte Fakten ueber Repos und Geraete. "
    "NICHT speichern, was Code, Karten oder Git-Historie ohnehin festhalten, "
    "und nichts, was nur fuer den letzten Turn galt. Gibt es die Notiz "
    "schon, aktualisiere sie (gleicher Name) statt eine zweite anzulegen. "
    "Geheimnisse (Token, Passwoerter) gehoeren NICHT hinein.\n\n"
    "Antworte NUR mit den Bloecken - keine Prosa davor oder danach."
)
