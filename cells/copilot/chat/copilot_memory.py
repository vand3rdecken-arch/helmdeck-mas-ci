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
import math
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
# `kind` is OPTIONAL and only a DECLARATION - resolve_kind() decides what is
# actually stored, because the turn knows things the sentence does not (whether
# this came from a card, whether it reports an inability).
_BLOCK_RE = re.compile(
    r'<memory-save\s+name="([^"<>]*)"(?:\s+kind="([^"<>]*)")?\s*>(.*?)</memory-save>'
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
            name, content = m.group(1).strip(), m.group(3).strip()
            declared = (m.group(2) or "").strip()
            if _NAME_RE.match(name) and content and len(content) <= MAX_CONTENT_LEN:
                muts.append({"op": "save", "name": name, "content": content,
                             "declared_kind": declared})
            else:
                rejects.append(name or "?")
        else:
            name = (m.group(4) or "").strip()
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


def apply(mutations, actor="henry", source=""):
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
                # A1: the harness decides provenance, not the sentence.
                kind = resolve_kind(m.get("declared_kind"), actor, m["content"])
                # A3: BEFORE writing, who already says something else and
                # outranks this? Computed against the store as it is now, so
                # the note being replaced is not compared against itself.
                clash = conflicts(m["name"], m["content"], kind)
                m["kind"] = kind
                m["clash"] = [c[0] for c in clash]
                db.memory_put(m["name"], m["content"], actor=actor, kind=kind,
                              source=source or "",
                              claim="reach-fail" if kind == "reach-fail" else "")
                # NB field name: events.emit(kind, track, **fields) owns the
                # word 'kind' as its first positional - passing it as a field
                # is a TypeError that apply() would swallow per-mutation.
                events.emit("memory", "-", op="save", actor=actor, name=m["name"],
                            note_kind=kind, clash=m["clash"])
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
                     # the CLI store is written by the OPERATOR's own sessions
                     # (card-shares-the-operators-auto-memory measured it and
                     # made it read-only for us), so it ranks as his word.
                     "kind": "owner-fact", "origin": "cli", "claim": "",
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
                     "updated_at": row.get("updated_at") or "",
                     # PROVENANCE MUST REACH THE READER. The first cut stored
                     # kind/source/claim and then dropped them here, so
                     # recall() rendered every note as "project" and
                     # conflicts() ranked against a default instead of the
                     # real value - it appeared to work only because the
                     # default happened to outrank reach-fail.
                     "kind": row.get("kind") or "project",
                     "origin": row.get("source") or "",
                     "claim": row.get("claim") or ""}
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


# ---------------------------------------------------------------------------
# A2 / A9: THE HARNESS LOOKS THINGS UP, AND SAYS WHAT IT HAS.
#
# Card memory-as-knowledge-system. The board turn stopped carrying the memory
# index when chat-henry-kontext-pruning moved four pushes to pulls; the brief
# asks Henry to fetch, and a turn that skips the fetch is indistinguishable
# from one that correctly decided not to (debt
# henry-context-pull-is-prompt-enforced). On 2026-09-20 that bet lost three
# times in a row on one word: "Jev".
#
# So the pull comes back as a PUSH, but a targeted one. Measured on the real
# 199-note corpus BEFORE it was built: IDF-weighted term scoring puts the
# right note first for all three owner messages that actually failed ("Was ist
# Jev", "Kannst du den key nicht lokal laden", "warum ist der relay nicht
# erreichbar"). Plain term frequency does NOT - without the rarity weight,
# "lokal laden rechner" drags in certificate and Expo notes. And scoring the
# description line alone fails outright: our descriptions are summaries, not
# retrieval triggers, so Devin-style trigger matching would first cost a
# rewrite of all 199. Hence: full note text, IDF-weighted, deterministic, no
# model call and no embeddings. 199 notes is not a scale problem.
RECALL_K = 3
RECALL_BUDGET = 9000      # chars of note bodies pushed into one turn
RECALL_MIN_IDF = 2.0      # below this a term is too common to be a signal
RECALL_MIN_SCORE = 2.0    # one rare-ish term alone is not a hit
# ...unless the note is really ABOUT that term. TUNED, not guessed: measured
# on the live 200-note corpus against 8 answerable and 10 unanswerable
# questions. tf>=1: 8 hits / 10 false positives (useless). tf>=2: 8 hits / 1
# false positive. tf>=3: 7 hits / 1 false positive. Two dominates three - same
# false positives, one more real answer - so two it is.
RECALL_MIN_TF = 2
_TOKEN_RE = re.compile(u"[a-z0-9äöüß-]{3,}")
_idf_cache = {"fp": None, "df": None, "tf": None, "n": 0}


def _tokens(text):
    return _TOKEN_RE.findall((text or "").casefold())


def _corpus_fp(rows):
    """Cheap fingerprint - count plus the newest timestamp. Recomputing the
    document frequencies on every turn over 199 notes is wasted work; doing it
    from a STALE cache is the bug this whole card is about, so the cache key
    has to move whenever a note does."""
    newest = max((r.get("updated_at") or "" for r in rows.values()), default="")
    return (len(rows), newest)


def _df(rows):
    """(document_frequencies, note_count). Also fills the per-note token
    counts in the same pass - scoring needs exact TOKEN counts, and computing
    them from the raw text per query is both slower and wrong (see _tf)."""
    fp = _corpus_fp(rows)
    if _idf_cache["fp"] != fp:
        df, tf = {}, {}
        for name, r in rows.items():
            counts = {}
            for w in _tokens(name + " " + (r.get("content") or "")):
                counts[w] = counts.get(w, 0) + 1
            tf[name] = counts
            for w in counts:
                df[w] = df.get(w, 0) + 1
        _idf_cache.update(fp=fp, df=df, tf=tf, n=len(rows))
    return _idf_cache["df"], max(_idf_cache["n"], 1)


def _tf(rows, name):
    """How often each TOKEN occurs in one note. Substring counting was the
    root cause of both retrieval defects measured on the live 200-note corpus
    on 2026-09-21: `"wer" in body` is true for "Werkzeug", "werden" and
    "schwer", so a question about the 1998 Tour de France retrieved three
    HelmDeck notes, while "wieso verliert henry den kontext" retrieved none."""
    _df(rows)
    return (_idf_cache.get("tf") or {}).get(name) or {}


def recall(text, rows=None, k=RECALL_K):
    """[(name, row, score)] for the notes this message is actually about,
    best first. Pure over `rows` so tests feed fixtures."""
    rows = all_notes() if rows is None else rows
    if not rows or not (text or "").strip():
        return []
    df, n = _df(rows)
    terms = set()
    for w in set(_tokens(text)):
        if df.get(w) and math.log(n / df[w]) >= RECALL_MIN_IDF:
            terms.add(w)
    if not terms:
        return []
    hits = []
    for name, r in rows.items():
        counts = _tf(rows, name)
        score, matched, best_tf = 0.0, 0, 0
        for w in terms:
            tf = counts.get(w, 0)
            if tf:
                # sublinear term frequency: a note ABOUT Jev beats one that
                # merely mentions it once. Presence-only scoring made every
                # note carrying the word tie, and the tie-break then decided
                # the answer - which is how the first build of this returned a
                # note about a test that once killed the Jev benchmark.
                score += math.log(n / df[w]) * (1.0 + math.log(tf))
                matched += 1
                best_tf = max(best_tf, tf)
        # COVERAGE GATE. Score alone let ONE accidental rare word through, and
        # the NoMIRACL-style check caught it: 4 of 5 questions the store
        # provably cannot answer still got a memory block. A block handed over
        # for a question with no answer is the same lie as an empty index -
        # it just points the other way. So a hit needs either two distinct
        # query terms, or one term the note is genuinely ABOUT.
        if score >= RECALL_MIN_SCORE and (matched >= 2 or best_tf >= RECALL_MIN_TF):  # noqa: E501
            hits.append((name, r, score))
    # NEWEST first on a tie. Ascending here would hand a tie to the stalest
    # note - the exact shape of the bug this card exists to kill.
    hits.sort(key=lambda h: (h[2], h[1].get("updated_at") or ""), reverse=True)
    return hits[:k]


def recall_block(text, rows=None):
    """The A2 push: the notes themselves, with provenance, in the turn -
    BEFORE Henry decides whether he knows something."""
    hits = recall(text, rows=rows)
    if not hits:
        return ""
    out, used = [], 0
    for name, r, _s in hits:
        body = (r.get("content") or "").strip()
        room = RECALL_BUDGET - used
        if room < 400:
            break
        cut = len(body) - room
        if cut > 0:
            body = body[:room] + (
                "\n[... %d Zeichen gekuerzt, ganze Notiz: "
                "`py -3.12 ../ops/tools/henry_memory_get.py get %s`]" % (cut, name))
        used += len(body)
        out.append("=== %s [%s | %s | %s]\n%s"
                   % (name, r.get("kind") or "project",
                      r.get("origin") or r.get("source") or "db",
                      (r.get("updated_at") or "")[:10], body))
    return ("\n\nDEIN GEDAECHTNIS ZU DIESER NACHRICHT (vom Harness gesucht, "
            "nicht von dir - lies es, BEVOR du sagst, du wuesstest etwas "
            "nicht; widersprich ihm begruendet, wenn du es besser weisst):\n"
            + "\n\n".join(out))


def overview(rows=None):
    """A9, taken from Letta's <memory_metadata>: what EXISTS, never content.

    letta/prompts/prompt_generator.py injects note counts and the available
    tags into every turn, so the model knows its own store is non-empty and
    what it spans. That is the cheapest possible antidote to this card's whole
    failure: with it, "ich weiss es nicht" stops being a plausible inference
    from an empty-looking index and becomes a claim the owner can check."""
    rows = all_notes() if rows is None else rows
    if not rows:
        return ""
    topics = {}
    for name in rows:
        head = name.split("-")[0]
        if len(head) > 2:
            topics[head] = topics.get(head, 0) + 1
    top = sorted(topics.items(), key=lambda kv: -kv[1])[:12]
    ndb = sum(1 for r in rows.values() if r.get("source") == "db")
    newest = max((r.get("updated_at") or "" for r in rows.values()), default="")
    return ("\n\nGEDAECHTNIS-STAND: %d Notizen (%d eigene, %d aus dem "
            "Auto-Memory), neueste vom %s. Themen: %s. Du siehst hier nur die "
            "ZAHLEN - Inhalt holst du mit `find <begriff>`. Dass eine Sache "
            "hier nicht steht, heisst NICHT, dass es dazu nichts gibt."
            % (len(rows), ndb, len(rows) - ndb, newest[:10],
               ", ".join("%s (%d)" % (k, v) for k, v in top)))


# ---------------------------------------------------------------------------
# A1 / A3: PROVENANCE, AND A WRITE THAT CANNOT SILENTLY OVERRULE A MEASUREMENT.
REACH_FAIL_MARKERS = (
    "kein api", "keine api", "no api", "keine text-api", "hat keine",
    "gibt es nicht", "nicht erreichbar", "not reachable", "not available",
    "kein zugriff", "no access", "kein key", "no key", "nicht installiert",
    "not installed", "existiert nicht", "does not exist", "kann nicht",
    "cannot reach", "nicht moeglich",
)


def looks_like_reach_fail(content):
    """A card that could not GET to something is evidence about the card.

    2026-09-20: card 20260920-133208-direct had no TYPESAFE_API_KEY, reported
    "Jev hat keine Text-API", and that sentence became a stored fact that beat
    a measurement taken the day before. A report of an INABILITY, written by a
    card, is demoted here so it can never outrank a measurement again. It is
    still stored - it is real information about what that sandbox could see,
    just not about what the world contains."""
    low = (content or "").casefold()
    for mrk in REACH_FAIL_MARKERS:
        if mrk in low:
            return True
    return False


def kinds():
    try:
        from spine.storage import db
        return db.MEMORY_KINDS
    except Exception:                                            # noqa: BLE001
        return ("reach-fail", "card-report", "project", "measured", "owner-fact")


def resolve_kind(declared, actor, content):
    """The stored `kind`, decided by the HARNESS from the turn it is folding.
    The model may DECLARE a kind; it cannot promote a card's report into an
    owner fact, and it cannot hide an inability behind a confident sentence."""
    kind = declared if declared in kinds() else None
    if (actor or "").startswith("card"):
        if looks_like_reach_fail(content):
            return "reach-fail"
        if kind in (None, "owner-fact", "measured"):
            return "card-report"
    return kind or "project"


def conflicts(name, content, kind, rows=None):
    """[(other_name, other_row)] - notes about the SAME thing that OUTRANK this
    write. A3: the store does not merge for Henry and it does not let the
    newest silently win; it puts the disagreement in front of him next turn.

    Deliberately NOT an LLM judgement. Graphiti (issue 1666) and mem0 both
    resolve contradictions with one model call over embedding-retrieved
    neighbours, and both have documented silent failures when that call is
    weak; arXiv 2606.09863 measures an LLM judge at near-chance as a guard
    against exactly this class of false confidence. A rank comparison over
    shared rare terms is cheap, inspectable, and cannot quietly decide wrong."""
    rows = all_notes() if rows is None else rows
    from spine.storage import db
    mine = db.memory_rank(kind)
    df, n = _df(rows)
    terms = set()
    for w in set(_tokens(name + " " + (content or ""))):
        if df.get(w) and math.log(n / df[w]) >= RECALL_MIN_IDF:
            terms.add(w)
    if not terms:
        return []
    out = []
    for other, r in rows.items():
        if other == name or db.memory_rank(r.get("kind")) <= mine:
            continue
        counts = _tf(rows, other)
        score = 0.0
        for w in terms:
            if counts.get(w):
                score += math.log(n / df[w])
        if score >= RECALL_MIN_SCORE * 2:
            out.append((other, r))
    return out[:3]


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
    cap = limit or DIGEST_MAX
    body = "\n".join(lines)
    if len(body) > cap:
        kept = body[:cap].rsplit("\n", 1)[0]
        cut = len(lines) - (kept.count("\n") + 1)
        # A TRUNCATION THAT DOES NOT SAY SO is the defect this whole change
        # is about: Henry read a short index, found nothing, and told the
        # owner he had never been told. A cut index must name its blind spot.
        body = kept + ("\n... und %d aeltere Notizen, die HIER NICHT STEHEN - "
                       "wenn du sie nicht siehst, heisst das NICHT, dass es "
                       "sie nicht gibt: `find <begriff>` sucht ueber alle %d."
                       % (cut, len(rows)))
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
    saved = ["%s [%s]" % (m["name"], m.get("kind") or "project")
             for m in (muts or []) if m.get("op") == "save"]
    gone = [m["name"] for m in (muts or []) if m.get("op") == "delete"]
    demoted = [m["name"] for m in (muts or [])
               if m.get("kind") == "reach-fail"]
    clashes = []
    for m in (muts or []):
        for other in (m.get("clash") or []):
            clashes.append("%s vs %s" % (m["name"], other))
    if saved:
        parts.append("gespeichert: " + ", ".join(saved[:8]))
    if demoted:
        parts.append("ALS ZUGRIFFSFEHLER abgelegt (eine Karte, die nicht "
                     "herankam, beweist nichts ueber die Sache selbst - "
                     "diese Notiz schlaegt KEINE Messung): "
                     + ", ".join(demoted[:5]))
    if clashes:
        parts.append("WIDERSPRUCH zu einer hoeher eingestuften Notiz, NICHT "
                     "stillschweigend ueberschrieben - lies sie und sag dem "
                     "Owner, welche gilt: " + "; ".join(clashes[:5]))
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
