# -*- coding: utf-8 -*-
"""henry-memory-db-authority: the sentinel write path (phase 1), the
session-scoped digest gate (phase 2), and (2026-09-11 follow-up) the fact
that memory has NO filesystem surface at all anymore - db.memory_all/put/
delete is the only store, and ops/tools/henry_memory_get.py is the only
read path a full note travels, a plain db query with no cache in between.

Self-sandboxing: db.ROOT/db.DBPATH point at a temp dir (db.init() run
against it) - the README's own trap #4 ("tests that patch events.SET alone
write the LIVE db") means this must move or the test would touch the real
daemon.

Run: py -3.12 ops/tests/test_copilot_memory.py   (from the repo root)
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp(prefix="copilot_memory_test_")
from spine.storage import db, events                                  # noqa: E402
db.ROOT = _tmp
db.DBPATH = os.path.join(_tmp, "test.db")
db.init()
# events.emit() writes the sandboxed events table (state-into-db phase H).
from cells.copilot.chat import copilot_memory as m                    # noqa: E402
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "henry_memory_get", os.path.join(ROOT, "ops", "tools", "henry_memory_get.py"))
_hmg = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_hmg)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _reset_memory():
    for name in list(db.memory_all()):
        db.memory_delete(name)


# -- parse(): the strict sentinel grammar ------------------------------------
print("\n[parse - valid blocks]")
_reset_memory()
cleaned, muts = m.parse(
    'Klar, notiert.\n<memory-save name="repo-x-owner">\n'
    'Repo X gehoert dem Owner.\n</memory-save>\nGern geschehen.')
check(cleaned == "Klar, notiert.\n\nGern geschehen.",
      "save block stripped from the visible reply, prose kept - got %r" % cleaned)
check(len(muts) == 1 and muts[0]["op"] == "save"
      and muts[0]["name"] == "repo-x-owner"
      and muts[0]["content"] == "Repo X gehoert dem Owner.",
      "save block parsed with name + content - got %r" % muts)

cleaned, muts = m.parse('Erledigt.\n<memory-delete name="repo-x-owner"/>')
check(cleaned == "Erledigt.", "delete block stripped - got %r" % cleaned)
check(muts == [{"op": "delete", "name": "repo-x-owner"}],
      "delete block parsed - got %r" % muts)

print("\n[parse - multiple blocks, in order]")
cleaned, muts = m.parse(
    '<memory-save name="a">first</memory-save>'
    '<memory-delete name="b"/>'
    '<memory-save name="c">third</memory-save>')
check([mm["name"] for mm in muts] == ["a", "b", "c"],
      "blocks applied in document order - got %r" % [mm["name"] for mm in muts])
check(cleaned == "", "no prose left when the reply is only blocks - got %r" % cleaned)

print("\n[parse - malformed: rejected, never guessed, always stripped]")
cleaned, muts = m.parse('Notiz.\n<memory-save name="bad/name">x</memory-save>')
check(muts == [], "a name with a path separator is rejected, not sanitized")
check(cleaned == "Notiz.", "the raw tag is still stripped from the reply - got %r" % cleaned)

cleaned, muts = m.parse('<memory-save name="empty-note"></memory-save>')
check(muts == [], "empty content is rejected (delete exists for 'nothing here')")

cleaned, muts = m.parse('<memory-save name="huge">%s</memory-save>' % ("x" * (m.MAX_CONTENT_LEN + 1)))
check(muts == [], "content over MAX_CONTENT_LEN is rejected, never truncated")

cleaned, muts = m.parse('<memory-delete name=".."/>')
check(muts == [], "a delete with an unsafe name is rejected the same way as a save")

print("\n[parse - no sentinel present]")
cleaned, muts = m.parse("Ganz normale Antwort ohne Notiz.")
check(cleaned == "Ganz normale Antwort ohne Notiz." and muts == [],
      "plain prose passes through untouched")

# -- apply(): db writes + per-mutation events --------------------------------
print("\n[apply - db writes land, one event per mutation]")
_reset_memory()
from spine.storage import events                                      # noqa: E402
_before = len(events.read_events())
done = m.apply([{"op": "save", "name": "note-a", "content": "fact a"},
                {"op": "save", "name": "MEMORY", "content": "- [note-a](note-a.md) - fact a"}],
               actor="henry")
check(len(done) == 2, "both mutations reported as applied")
all_notes = db.memory_all()
check(all_notes.get("note-a", {}).get("content") == "fact a", "note-a landed in the db")
check(all_notes.get("note-a", {}).get("actor") == "henry", "actor recorded as henry")
check(all_notes.get("MEMORY", {}).get("content", "").startswith("- [note-a]"),
      "the index note landed too")
_after_save = len(events.read_events())
check(_after_save - _before == 2, "one 'memory' event per mutation (got %d)" % (_after_save - _before))

m.apply([{"op": "delete", "name": "note-a"}], actor="henry")
check("note-a" not in db.memory_all(), "delete actually removes the row")
_after_delete = len(events.read_events())
check(_after_delete - _after_save == 1, "delete emits its own event too")

# -- digest(): a DERIVED index, never the notes themselves ------------------
# REWRITTEN 2026-09-20. The old contract was "digest() returns whatever Henry
# last stored under the name MEMORY", and that contract IS the defect: the
# stored index froze on 2026-09-15 because every rewrite exceeded
# MAX_CONTENT_LEN and parse() drops a bad block silently, so for five days he
# read a 40-line index of 115 notes and concluded he had never been told
# things he had written down himself. An index is a VIEW over the notes and
# is now computed. The invariant the old tests reached for - the NEWEST entry
# must never be the one cut - is pinned harder here, because a derived index
# is sorted newest-first by construction.
print("\n[digest]")
_reset_memory()
check(m.digest() == "", "no digest when there are no notes at all")
db.memory_put("note-a", "fact a", actor="henry")
d = m.digest()
check("note-a" in d, "digest lists the note - got %r" % d)
check("fact a" in d, "digest carries each note own description line")
db.memory_put("MEMORY", "- [hand-written](x.md) - stale, never rewritten", actor="henry")
check("stale" not in m.digest(),
      "a stored MEMORY note can no longer BE the index - it is ignored")
_reset_memory()
for i in range(60):
    db.memory_put("note-%03d" % i, "x" * 80, actor="henry")
db.memory_put("newest-note", "IOS APPROVED", actor="henry")
d = m.digest()
check(len(d) > 5000, "a 61-note index is big - %d chars" % len(d))
check(all(("note-%03d" % i) in d for i in range(60)) and "newest-note" in d,
      "every note is listed - an index cannot go stale on a note it never saw")

# -- henry_memory_get.py: the only read path for a full note, no cache -------
print("\n[henry_memory_get - read-only, no filesystem surface]")
_reset_memory()
db.memory_put("real-note", "the actual fact", actor="henry")
db.memory_put("MEMORY", "- [real-note](real-note.md) - the actual fact", actor="henry")

import io, contextlib

def _run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = _hmg.main(["henry_memory_get.py"] + list(argv))
    return rc, out.getvalue()

rc, out = _run("list")
check(rc == 0 and "real-note" in out, "list surfaces the note name - got %r" % out)
check("MEMORY" not in out.splitlines(), "list hides the index note itself")

rc, out = _run("get", "real-note")
check(rc == 0 and "the actual fact" in out, "get returns the exact db content - got %r" % out)
check(rc == 0 and out.splitlines()[0].startswith("[db |"),
      "get labels WHICH store the note came from - got %r" % out.splitlines()[:1])

rc, out = _run("get", "no-such-note")
check(rc == 1, "get on a missing note exits non-zero, not a guess")

check(not any("henry_memory" in p for p in os.listdir(_tmp) if os.path.isdir(os.path.join(_tmp, p))),
      "no henry_memory directory exists anywhere - the read path never touches disk")

# marker()/digest_due() (the session-establishment gate for Henry's own
# auto-pushed digest) were REMOVED with the push itself (card
# chat-henry-kontext-pruning, "voller Umbau", 2026-09-15): digest() now has
# exactly one caller (cells/copilot/planning/pm.py's planner context), which
# reads it fresh every time it plans - no gate needed, nothing to test here.

# ---------------------------------------------------------------------------
# 2026-09-20, owner: "alle Infos zu Claude und db sollten zugaenglich sein".
# Henry told the owner three times that Jev has no text API while the
# correction sat in the CLI's own auto-memory directory and the wrong card
# report sat in his db. Two stores, no reconciliation, and an index that had
# been frozen since 2026-09-15 because every rewrite was silently rejected.
# Each check below FAILS on the pre-fix code.
print("\n-- derived index + the second store --")

_reset_memory()
for i in range(120):
    db.memory_put("note-%03d" % i, "fact %d" % i)
db.memory_put("MEMORY", "- [stale](old.md) - written by hand on 2026-09-15")
_idx = m.digest()
check(all(("note-%03d" % i) in _idx for i in range(120)),
      "the index is DERIVED: all 120 notes appear, not the 1-line stored MEMORY note")
check("stale" not in _idx, "the hand-written MEMORY note is no longer the index")
rc, out = _run("get", "MEMORY")
check(rc == 0 and "note-119" in out, "get MEMORY serves the derived index too - got %r" % out[:120])

# the CLI's auto-memory: read ONLY from a path the CLI itself reported
_auto = os.path.join(_tmp, "cli_memory")
os.makedirs(_auto, exist_ok=True)
with io.open(os.path.join(_auto, "jev-browser-verdict.md"), "w", encoding="utf-8") as f:
    f.write("---\nname: jev-browser-verdict\ndescription: Jev has a score API\n---\n\nbody here\n")
check(m.auto_dir() is None,
      "an UNOBSERVED directory is invisible - the path is never derived from cwd")
check(m.auto_notes() == {}, "no observation, no notes - an honest empty, not a guess")

m.observe_auto_dir({"type": "system", "subtype": "init", "session_id": "s1",
                    "memory_paths": {"auto": _auto}})
check(m.auto_dir() == _auto, "the path is taken from the CLI's OWN init event")
_all = m.all_notes()
check("jev-browser-verdict" in _all, "a CLI note is now readable alongside the db")
check(_all["jev-browser-verdict"].get("source") == "cli", "a CLI note is labelled as such")
check("Jev has a score API" in m.digest(), "the CLI note shows up in the index")
# ORDER IS THE WHOLE POINT OF THE OLD BUG: the stored index was APPENDED
# to, so a length cut removed the newest entries - the ones just saved.
# Derived, it is sorted newest-first, so a cut can only ever lose the
# stalest. Pinned with real, distinct mtimes rather than same-second ties.
import time as _t
_reset_memory()   # only the CLI store in play, so the ordering is the thing tested
for _fn, _age in (("ancient-note.md", 200000), ("fresh-note.md", 10)):
    _fp = os.path.join(_auto, _fn)
    with io.open(_fp, "w", encoding="utf-8") as f:
        f.write("body of " + _fn)
    os.utime(_fp, (_t.time() - _age, _t.time() - _age))
_short = m.digest(limit=120)
check("fresh-note" in _short and "ancient-note" not in _short,
      "a truncated index keeps the NEWEST and drops the stalest - got %r" % _short[-160:])
check("HIER NICHT STEHEN" in _short,
      "a CUT index says so - the silent short list is the whole bug")
rc, out = _run("find", "score")
check(rc == 0 and "jev-browser-verdict" in out, "find searches BOTH stores - got %r" % out[:160])

db.memory_put("jev-browser-verdict", "db version wins")
_all = m.all_notes()
check(_all["jev-browser-verdict"].get("source") == "db",
      "on a name clash the store of record wins")
check(_all["jev-browser-verdict"].get("also_in") == "cli",
      "the losing twin is FLAGGED, not silently dropped")

m.observe_auto_dir({"type": "system", "subtype": "init",
                    "memory_paths": {"auto": os.path.join(_tmp, "gone")}})
check(m.auto_dir() is None, "an observed path that no longer exists reads as absent")
m.observe_auto_dir({"type": "system", "memory_paths": {"auto": _auto}})

print("\n-- the write path reports back --")
_cleaned, _muts = m.parse('<memory-save name="huge">%s</memory-save>' % ("x" * (m.MAX_CONTENT_LEN + 1)))
check(m.last_rejects() == ["huge"], "a rejected block is readable by the caller, not only an event")
_line = m.feedback(_muts, m.last_rejects())
check("VERWORFEN" in _line and "huge" in _line,
      "the next turn is TOLD the save was dropped - got %r" % _line)
_cleaned, _muts = m.parse('<memory-save name="kept">fact</memory-save>')
check(m.last_rejects() == [], "a clean turn reports no rejects")
check("gespeichert: kept" in m.feedback(_muts, m.last_rejects()),
      "a successful save is reported too")
check(m.feedback([], []) == "", "a turn that saved nothing adds no line")


# ---------------------------------------------------------------------------
# Card memory-as-knowledge-system, A1/A2/A3/A9. Every check below fails on the
# pre-2026-09-21 code, which had no retrieval, no provenance and no conflict
# detection at all.
print("\n-- A2: the harness looks it up --")
_reset_memory()
db.memory_put("jev-direct-api", "Jev ist ueber die API erreichbar, 761 ms je "
              "Urteil, Score-Modell mit choice-Frage.", actor="henry",
              kind="measured")
db.memory_put("jev-thesis-test", "Karte ohne Key meldete, Jev habe keine "
              "Text-API.", actor="card:x", kind="reach-fail")
db.memory_put("relay-unreachable", "Relay nicht erreichbar hiess in Wahrheit "
              "Daemon-Last durch events_all.", actor="henry", kind="measured")
for i in range(40):
    db.memory_put("filler-%03d" % i, "Ein ganz normaler Vermerk ueber "
                  "Alltagskram Nummer %d." % i, actor="henry")

_hits = [n for n, _r, _s in m.recall("Was ist Jev")]
check(_hits and _hits[0].startswith("jev"),
      "recall puts a Jev note first for 'Was ist Jev' - got %r" % _hits)
check("jev-direct-api" in _hits,
      "the MEASUREMENT is among the hits, not only the card report - %r" % _hits)
_blk = m.recall_block("Was ist Jev")
check("jev-direct-api" in _blk and "measured" in _blk,
      "the recall block carries the note WITH its provenance")
check("761 ms" in _blk, "the recall block carries the note BODY, not just names")
check(m.recall_block("") == "", "an empty message retrieves nothing")
check(m.recall_block("bitte") == "",
      "a message with only common words retrieves nothing rather than noise")

# the rarity weight is what makes this work - pinned, because dropping it
# silently degrades retrieval into 'whatever shares a stopword'
_common = [n for n, _r, _s in m.recall("ein ganz normaler Vermerk")]
check(all(x.startswith("filler") for x in _common) or not _common,
      "common-word query does not drag in the Jev notes - got %r" % _common)

print("\n-- A9: the harness says what exists --")
_ov = m.overview()
check(("%d Notizen" % len(m.all_notes())) in _ov,
      "the overview counts every note - got %r" % _ov[:120])
check("jev" in _ov or "relay" in _ov or "filler" in _ov,
      "the overview names the topics present")
check("NICHT" in _ov,
      "the overview says absence from it is not evidence of absence")
check("ALLE NOTIZ-NAMEN" in _ov and all(n in _ov for n in list(m.all_notes())[:5] if n != "MEMORY"),
      "the overview lists every note NAME (the model picks, like `view /memories`)")
_names = m._name_index({"n%03d-%s" % (i, "x" * 60): {"updated_at": "2026-09-%02d" % (i % 28 + 1)}
                        for i in range(400)})
check("HIER NICHT STEHEN" in _names and len(_names) < m.NAME_INDEX_MAX + 200,
      "a cut name list is capped AND names its blind spot")
check("MOEGLICHE TREFFER" in m.recall_block("Was ist Jev")
      and "vom Harness gesucht, nicht" not in m.recall_block("Was ist Jev"),
      "the keyword block calls itself possible hits, not the answer")

print("\n-- A1: provenance is decided by the harness --")
check(m.resolve_kind("owner-fact", "card:20260920", "Jev hat keine Text-API")
      == "reach-fail",
      "a card reporting an INABILITY cannot store it as an owner fact")
check(m.resolve_kind("owner-fact", "card:x", "761 ms gemessen") == "card-report",
      "a card cannot promote its own report to an owner fact")
check(m.resolve_kind("owner-fact", "henry", "Owner will iOS zuerst") == "owner-fact",
      "Henry's own board turn may record an owner fact")
check(db.memory_rank("measured") > db.memory_rank("card-report")
      > db.memory_rank("reach-fail"),
      "the rank order is measurement > card report > reach failure")

_cleaned, _muts = m.parse('<memory-save name="probe-1" kind="measured">'
                          'Ein Messwert.</memory-save>')
m.apply(_muts, actor="card:20260921", source="card:20260921")
check(db.memory_all()["probe-1"]["kind"] == "card-report",
      "a card's save lands as card-report even when it declares measured")
check(db.memory_all()["probe-1"]["source"] == "card:20260921",
      "the source is stamped by the harness")

print("\n-- A3: a write cannot silently overrule a measurement --")
_cleaned, _muts = m.parse('<memory-save name="jev-note-neu">Jev hat keine '
                          'Text-API und ist nicht erreichbar.</memory-save>')
_done = m.apply(_muts, actor="card:20260920", source="card:20260920")
check(_done and _done[0]["kind"] == "reach-fail",
      "the inability report is demoted to reach-fail - got %r"
      % (_done[0].get("kind") if _done else None))
check(_done[0].get("clash"),
      "the higher-ranked Jev measurement is reported as a clash - got %r"
      % (_done[0].get("clash"),))
_line = m.feedback(_done, [])
check("WIDERSPRUCH" in _line and "ZUGRIFFSFEHLER" in _line,
      "the next turn is told BOTH that it was demoted and what it contradicts")
check(db.memory_all()["jev-direct-api"]["content"].startswith("Jev ist ueber"),
      "the outranked write did NOT overwrite the measurement")

print("\n-- T-Leer-ist-nicht-nichts (NoMIRACL recipe) --")
# Questions with provably no note. The harness must retrieve NOTHING and say
# so, rather than hand over a plausible-looking near-miss that reads as an
# answer. FP here = a block returned for a question the store cannot answer.
_absent = ["wie hoch ist der Dachfirst", "welche Farbe hat das Segelboot",
           "wann faehrt die Faehre nach Helgoland", "was kostet ein Zentner Hafer",
           "wer gewann die Tour 1998"]
_fp = [q for q in _absent if m.recall_block(q).strip()]
check(not _fp, "no block is fabricated for a question the store cannot answer "
      "- false positives: %r" % _fp)
_present = ["Was ist Jev", "warum ist das relay nicht erreichbar"]
_tp = [q for q in _present if m.recall_block(q).strip()]
check(len(_tp) == len(_present),
      "and the questions it CAN answer still retrieve - got %r" % _tp)

print("\n-- T-Vokabellücke: 'Immobilien' findet den 'immo-deal-scanner' (2026-10-05) --")
# Henry told the owner "ich kannte den Scanner nicht" with
# immo-deal-scanner-owner in his db: the owner's word was 'Immobilien', the
# note says 'Immo-Deal-Scanner' - one hyphenated token, no shared word. And the
# common word 'neue' (tf 2 in unrelated notes) pushed three wrong notes.
_fill = {"filler-%02d" % i: {"content": "Notiz %d ueber Karten, Relay und Build Nummer%d. Neue "
                                        "Karte, neue Version." % (i, i), "updated_at": "2026-09-%02d" % (i % 28 + 1)}
         for i in range(40)}
_fill["immo-deal-scanner-owner"] = {"content": "Kaufobjekt-Scanner Frankfurt. Repo Downloads/"
                                    "immo-deal-scanner, Dashboard und ImmoScout-Daten.",
                                    "updated_at": "2026-09-28"}
for _q in ("Und irgendwelche neue Immobilien?", "Immobilien Scanner"):
    _h = [n for n, _r, _s in m.recall(_q, rows=_fill)]
    check(_h[:1] == ["immo-deal-scanner-owner"], "recall(%r) puts the scanner note first - got %r" % (_q, _h))
_h = [n for n, _r, _s in m.recall("Und irgendwelche neue Immobilien?", rows=_fill)]
check(not any(n.startswith("filler-") for n in _h),
      "a common word like 'neue' no longer drags unrelated notes in - got %r" % _h)
check(m.recall("wer gewann die Tour 1998", rows=_fill) == [], "an unanswerable question still retrieves nothing")
check(m.recall("wer", rows={"a": {"content": "werkzeug werkzeug kasten", "updated_at": "2026-09-01"}, **_fill}) == [],
      "a 3-letter word never prefix-matches a longer one ('wer' vs 'werkzeug')")

# --- closed-world / silent-truncation disclosure (agent-facing text) ---
_many = "".join('<memory-save name="n-%02d">inhalt %d</memory-save>' % (i, i)
                for i in range(m.MAX_BLOCKS + 3))
_c, _mu = m.parse("x " + _many)
check(len(_mu) == m.MAX_BLOCKS, "parse still applies at most MAX_BLOCKS")
_fb = m.feedback(_mu, m.last_rejects())
check("3 Notiz-Bloecke ueber dem Limit von %d verworfen" % m.MAX_BLOCKS in _fb and "n-30" in _fb,
      "blocks over the limit are named in the next-turn feedback, not dropped silently")
check("(+" in _fb and "weitere)" in _fb, "the capped 'gespeichert' list carries (+N weitere)")
m.parse("<memory-save name=\"one\">a</memory-save>")
check("ueber dem Limit" not in m.feedback([{"op": "save", "name": "one"}], []),
      "a clean parse leaves no stale overflow notice")

_rows = {"n%d" % i: {"content": ("wort%d " % i) * 3 + "kolibri " * 40, "updated_at": "2026-09-%02d" % (i + 1),
                     "kind": "project", "source": "db"} for i in range(4)}
for _i in range(30):
    _rows["fl%d" % _i] = {"content": "belanglos text %d" % _i, "updated_at": "2026-08-01",
                          "kind": "project", "source": "db"}
_old = m.RECALL_BUDGET
m.RECALL_BUDGET = 700
try:
    _rb = m.recall_block("kolibri kolibri wort0 wort1 wort2 wort3", rows=_rows)
finally:
    m.RECALL_BUDGET = _old
check("weitere Treffer nicht ausgegeben" in _rb and "henry_memory_get.py get" in _rb,
      "hits dropped by the recall budget are named with the get command")

_old_skip = m.auto_skipped
m.auto_skipped = lambda: 7
try:
    _ov = m.overview({"a-b": {"content": "x", "updated_at": "2026-09-01", "source": "db"}})
finally:
    m.auto_skipped = _old_skip
check("7 Dateien ueber dem Limit von %d nicht geladen" % m.AUTO_MAX_FILES in _ov,
      "the overview names auto-memory files beyond AUTO_MAX_FILES")

import io as _io, contextlib as _cl
_fx = {"n%d" % i: {"content": "alpha " + "z" * 3000, "updated_at": "2026-09-%02d" % (i + 1), "source": "db"}
       for i in range(10)}
_buf = _io.StringIO()
_hits = _hmg.find_notes(_fx, ["alpha"])
check(len(_hits) == 10, "find_notes logic unchanged (all 10 match)")
_old_all = m.all_notes
m.all_notes = lambda *a, **k: _fx
try:
    with _cl.redirect_stdout(_buf):
        _hmg.main(["x", "find", "alpha"])
finally:
    m.all_notes = _old_all
_out = _buf.getvalue()
check("2 weitere Treffer nicht gezeigt" in _out and "Zeichen gekuerzt, ganze Notiz: get" in _out
      and "Teilstring-Suche" in _out, "find says what it cut and by which criteria")

from cells.copilot.chat import private_henry as _ph, room_henry as _rh   # noqa: E402
_cards = _ph._Cards([{"id": "c1", "task": "t", "lane": "l", "status": "s", "result": "", "mine": True}])
_cards.total = 20
_pp = _ph.build_prompt({"name": "Ann"}, _cards, [], "hi", {})
check("1 von 20 Karten gezeigt" in _pp and "letzten %d Eintraege" % _ph.HISTORY_ENTRIES in _pp,
      "private prompt says N of M cards shown and names the history window")
_big = {"r/n%d" % i: {"content": "x" * 3000, "updated_at": "2026-09-%02d" % (i + 1)} for i in range(4)}
_mb = _rh.memory_block(_big)
check("Notizen nicht gezeigt" in _mb, "room memory_block names the notes the budget cut")
_rp = _rh.build_prompt({"name": "R", "members": ["a"]}, [{"text": "m"}] * 40, "a", "q", {})
check("nur die letzten %d von 40 Nachrichten" % _rh.HISTORY_LINES in _rp,
      "room prompt names its history window")

print("")
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("copilot-memory: all pinned - PASS")
