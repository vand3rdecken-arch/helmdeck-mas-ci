# -*- coding: utf-8 -*-
"""Henry's memory - DB-authoritative (henry-memory-db-authority card).

Owner review 2026-09-11: memory is GOVERNANCE CONFIG, not runtime litter - a
saved note rides in every board turn via digest() and shapes Henry's behaviour
like the brief does. The db table (spine.storage.db memory_all/put/delete) is
therefore the store of record, exactly like policy_doc. MEMORY_DIR is a
DISPOSABLE READ CACHE only: Henry's own Read tool opens a note there on demand
(progressive disclosure - the index rides in every turn, a note is read only
when it turns out to matter), regenerate_cache() clobbers it from the db at
session establishment, and NOTHING ever folds it back. A planted file on disk
survives at most until the next regen and never reaches the db - the old
_fold_memory_to_db() direction (dir -> db, deleting db rows with no matching
file) is gone precisely because it let an unauthenticated write to that
directory become a standing instruction in Henry's own turns.

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
import os, re

from daemon.paths import DAEMON_ROOT as ROOT

MEMORY_DIR = os.path.join(ROOT, "content", "henry_memory")

MAX_NAME_LEN = 60
MAX_CONTENT_LEN = 8000
MAX_BLOCKS = 30           # a turn cannot mutate an unbounded number of notes

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,%d}$" % (MAX_NAME_LEN - 1))

# ONE regex, both tags, so blocks are handled in the order they actually
# appear in the reply - a save immediately followed by a delete of the SAME
# name is a real (if odd) sequence and must apply in that order, not be
# reordered by parsing saves first.
_BLOCK_RE = re.compile(
    r'<memory-save\s+name="([^"<>]*)"\s*>(.*?)</memory-save>'
    r'|<memory-delete\s+name="([^"<>]*)"\s*/?>',
    re.S | re.I)


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


def marker(sid, compacted_at_turn):
    """The (sid, compacted_at_turn) pair identifying 'this session, as of its
    last compaction' - the session-establishment key the digest gate in
    copilot.chat() compares turn to turn. It changes on exactly the three
    events README calls "session establishment": a fresh spawn (sid falsy), a
    rotated/detached resume (sid itself changes), and an IN-PLACE compaction
    that keeps the same sid but bumps compacted_at_turn - the one case a
    sid-only key would silently miss (a real /compact commonly does NOT
    rotate the session id, see ops/tests/test_copilot_compact.py case 3)."""
    return (sid or "", compacted_at_turn)


def digest_due(sid, marker_now, last_marker):
    """True when the memory digest must ride THIS turn. No session yet, or
    the session-establishment marker moved since it was last delivered - a
    resumed turn whose marker is UNCHANGED already carries the digest in its
    own transcript (README finding #3: "resumede Turns bekommen NICHTS, das
    Transkript hat es schon"), so re-sending it there would be the exact
    token waste this phase exists to cut."""
    return (not sid) or (last_marker != marker_now)


def digest():
    """The memory INDEX for the turn - never the notes themselves (see the
    module docstring's progressive-disclosure note). Reads the db - the store
    of record - not the cache directory."""
    try:
        from spine.storage import db
        body = (db.memory_all().get("MEMORY") or {}).get("content", "").strip()
    except Exception:                                            # noqa: BLE001
        return ""
    if not body:
        return ""
    return ("\n\nDEIN GEDAECHTNIS (Index; die Dateien liegen in %s - lies eine, "
            "wenn sie zur Frage passt):\n%s" % (MEMORY_DIR, body[:4000]))


def regenerate_cache():
    """Clobber MEMORY_DIR from the db (Phase 3: db is authority, the dir is a
    disposable read cache). Called lazily at session establishment, only when
    a digest is actually about to be injected - a resumed turn that carries no
    fresh digest has no reason to touch disk. A file the db does not know
    about is removed; nothing on disk is ever read back into the db."""
    try:
        from spine.storage import db
        notes = db.memory_all()
        os.makedirs(MEMORY_DIR, exist_ok=True)
        keep = set()
        for name, row in notes.items():
            if not _NAME_RE.match(name):
                continue                 # a hand-corrupted row is not a safe filename
            fname = name + ".md"
            keep.add(fname)
            with open(os.path.join(MEMORY_DIR, fname), "w", encoding="utf-8") as f:
                f.write(row.get("content") or "")
        for fname in os.listdir(MEMORY_DIR):
            if fname.endswith(".md") and fname not in keep:
                try:
                    os.remove(os.path.join(MEMORY_DIR, fname))
                except OSError:
                    pass
    except Exception as e:                                        # noqa: BLE001
        print("copilot: memory cache regen failed -", str(e)[:200])


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
