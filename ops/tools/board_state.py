# -*- coding: utf-8 -*-
"""Print the board as text - Henry's board context, ALL of it now on demand.

Why this exists (measured 2026-09-02, widened 2026-09-15). The full board
snapshot used to ride inside EVERY chat turn: 83,488 chars / ~23k tokens of
uncached input the model re-read before answering anything at all. Paseo -
the reference this harness is ported from - sends only the user's text and
keeps context in the cached system prompt plus TOOLS the agent calls when it
needs them (packages/server/src/server/agent/providers/claude/agent.ts, the
user message is one `content.push({type:"text", text: prompt})`).

2026-09-02 moved the expensive HISTORY (finished/archived cards, full debt
prose, 65% of the old payload) behind --full. Card chat-henry-kontext-pruning
("voller Umbau", 2026-09-15) finished the move: the LIVE board and the PM
plan are no longer wired into the turn either - Henry calls this himself,
on his own initiative, exactly like Paseo's agents call their own tools.

There is NO second implementation of the board/plan text here: this calls
cells.copilot.chat.copilot._snapshot / _pm_plan_digest, the same one owner a
chat turn would have used, so the two can never drift.

    py -3.12 ops/tools/board_state.py           # live board
    py -3.12 ops/tools/board_state.py --full    # + finished/archived + debt text
    py -3.12 ops/tools/board_state.py --plan    # the live PM plan (goal, risks, milestones)
    py -3.12 ops/tools/board_state.py --find play store   # cards matching ALL terms
    py -3.12 ops/tools/board_state.py --card <id-or-fragment>  # one card, in full

--find / --card are the FETCH-AS-NEEDED half for the PM planner (2026-09-12):
the planner never gets the 100k-char history inlined; it searches for the
cards behind a claim it is about to make ("no Play account") and reads the
few it needs in full - outcome AND the full last reply, because the outcome
snippet alone misled Henry once (memory playstore-produktionszugriff-
genehmigt). Read-only: nothing here writes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def _terms(argv, flag):
    """Everything after `flag`, casefolded - the search terms."""
    i = argv.index(flag)
    return [t.casefold() for t in argv[i + 1:] if t.strip()]


def _card_text(t):
    """The searchable text of ONE card: title, description, stored outcome
    and the full last reply. Titles alone mislead (pm-lean-advisor README
    finding 4), so the body counts too."""
    return " ".join(str(t.get(k) or "") for k in ("id", "task", "description", "outcome", "last_reply"))


def find_cards(terms, tracks=None):
    """Cards whose text carries EVERY term (casefold substring). Any lane,
    archived included - history is exactly what the caller is missing.
    Newest first. Pure function over the tracks list, so tests feed fixtures."""
    if tracks is None:
        from cells.engineer.cards import sessions
        tracks = sessions.list_tracks()
    hits = []
    for t in tracks:
        if t.get("example"):
            continue
        body = _card_text(t).casefold()
        if all(term in body for term in terms):
            hits.append(t)
    hits.sort(key=lambda t: t.get("updated") or t.get("created") or "", reverse=True)
    return hits


def format_hit(t, reply_chars=900):
    """One compact record per hit: enough to answer 'what happened here',
    small enough that ten hits stay under ~3k tokens."""
    arch = " ARCHIVED" if t.get("archived") else ""
    head = "- id=%s %s lane=%s status=%s%s updated=%s\n  task=%s" % (
        t.get("id"), (t.get("created") or "")[:10], t.get("lane"), t.get("status") or "-",
        arch, (t.get("updated") or "")[:16], (t.get("task") or "").strip()[:200])
    out = [head]
    if t.get("outcome"):
        out.append("  outcome=" + " ".join(str(t["outcome"]).split())[:400])
    lr = " ".join(str(t.get("last_reply") or "").split())
    if lr:
        out.append("  last_reply=" + lr[:reply_chars] + (" ..." if len(lr) > reply_chars else ""))
    return "\n".join(out)


def _worker_tail(t, n=10):
    """What the card's worker actually DID last - the same event-time feed the
    app renders in the card thread (claude_sessions.read_transcript_store), not
    a second reader. Without it a card that died read only as its status and
    "stream ended with no result"; 2026-09-26 the cause (the worker's own
    Stop-Process on a command-line match that hit its claude.exe) sat in this
    feed as the last tool call, and Henry could not see it."""
    try:
        from spine.agent import claude_sessions
        steps = claude_sessions.read_transcript_store(t, limit=200)
    except Exception as e:                                       # noqa: BLE001
        return "(feed unreadable: %s)" % e
    rows = []
    for s in steps:
        kind = s.get("kind")
        if kind == "tool":
            state = s.get("status") or ("ok" if s.get("ok") else "")
            rows.append("%s tool %s [%s]: %s" % (s.get("ts", ""), s.get("tool", ""), state,
                                                 " ".join(str(s.get("text") or "").split())[:240]))
        elif kind == "text" and s.get("role") == "assistant":
            rows.append("%s said: %s" % (s.get("ts", ""), " ".join(str(s.get("text") or "").split())[:240]))
    return "\n".join(rows[-n:])


def _idle_line(t):
    """Evidence, not a verdict: when the worker's last turn ended and what the
    card is waiting on. `updated` alone misleads - non-turn writes bump it (card
    20261005-054744-direct showed 16:38 while its last turn ended 12:06, so
    "ich warte auf den Monitor" read as fresh and Henry decided `ignore`)."""
    import time
    ended = t.get("turn_ended") or ""
    ago = ""
    try:
        s = time.time() - time.mktime(time.strptime(ended[:19], "%Y-%m-%d %H:%M:%S"))
        ago = " (%dh%02dm ago)" % (s // 3600, s % 3600 // 60)
    except ValueError:
        pass
    reg = t.get("bg_tasks") if isinstance(t.get("bg_tasks"), dict) else {}
    running = [v.get("title") or "task" for v in reg.values()
               if v.get("status", "running") == "running"]
    return "last turn ended=%s%s waiting_on=%s open background tasks=%d%s" % (
        ended or "?", ago, t.get("waiting_on") or "-", len(running),
        " (" + ", ".join(running[:3]) + ")" if running else "")


def format_card(t):
    """The whole card, nothing clipped except the description at 2k."""
    lines = ["id=%s" % t.get("id"), "task=%s" % (t.get("task") or "").strip(),
             "repo=%s lane=%s status=%s archived=%s created=%s updated=%s" % (
                 t.get("repo"), t.get("lane"), t.get("status"), bool(t.get("archived")),
                 t.get("created"), t.get("updated")),
             "turns=%s ai_cost=%s" % (t.get("turns"), t.get("ai_cost"))]
    lines.append(_idle_line(t))
    if t.get("description"):
        lines.append("DESCRIPTION:\n" + str(t["description"])[:2000])
    if t.get("outcome"):
        lines.append("OUTCOME:\n" + str(t["outcome"]))
    steps = _worker_tail(t)
    if steps:
        lines.append("WORKER'S LAST STEPS (oldest first):\n" + steps)
    if t.get("last_reply"):
        lines.append("LAST REPLY (full):\n" + str(t["last_reply"]))
    out = "\n".join(lines)
    # CAP (state-into-db phase B): a planner-facing answer must never be worth
    # dumping to a file - 8k chars is a whole card for any question a plan
    # asks; the tail is the least useful part of a long last reply.
    if len(out) > 8000:
        out = out[:8000] + "\n... [card output capped at 8000 chars]"
    return out


def main(argv):
    full = "--full" in argv or "-f" in argv
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--plans" in argv or "--stale" in argv:
        # ALL processes / the leftovers, uncapped, with what was checked: the
        # pull view that lets Henry look past whatever a wake pre-filtered.
        import time
        from cells.copilot.planning import process_drive as pd
        from cells.engineer.chains import processes
        from cells.engineer.cards import sessions
        from spine.turn import listing
        ps, ts = processes.list_processes(), sessions.list_tracks()
        if "--plans" in argv:
            sys.stdout.write(listing.found(pd.plans_overview(ps), "alle Prozesse",
                                           criteria="keiner",
                                           checked="%d Prozesse" % len(ps), cap=500, complete=True) + "\n")
            wp = pd.work_by_project(ts, time.time())
            sys.stdout.write("ARBEIT nach Projekt: %s\n" % (wp or "keine Karten"))
        else:
            sys.stdout.write(pd.stale_block(ps, ts, time.time()) + "\n")
        return 0
    if "--plan" in argv:
        from cells.copilot.chat.copilot import _pm_plan_digest
        out = _pm_plan_digest()
        sys.stdout.write((out or "kein Ziel geplant") + "\n")
        return 0
    if "--find" in argv:
        terms = _terms(argv, "--find")
        if not terms:
            print("usage: board_state.py --find <term> [term ...]", file=sys.stderr)
            return 2
        hits = find_cards(terms)
        if not hits:
            sys.stdout.write("no card matches ALL of: %s (gesucht in id, task, description, outcome, "
                             "last_reply; Beispiel-Karten und Worker-Schritte nicht durchsucht)\n"
                             % " ".join(terms))
            return 0
        sys.stdout.write("%d card(s) match %s (newest first, max 12 shown):\n" % (len(hits), " ".join(terms)))
        sys.stdout.write("\n".join(format_hit(t) for t in hits[:12]) + "\n")
        return 0
    if "--card" in argv:
        frag = " ".join(_terms(argv, "--card"))
        if not frag:
            print("usage: board_state.py --card <id-or-fragment>", file=sys.stderr)
            return 2
        from cells.engineer.cards import sessions
        ts = [t for t in sessions.list_tracks() if frag in (t.get("id") or "").casefold()]
        if len(ts) != 1:
            sys.stdout.write("%d cards match id fragment %r - be more specific\n" % (len(ts), frag))
            return 1
        sys.stdout.write(format_card(ts[0]) + "\n")
        return 0
    # UTF-8 or this tool is useless on Windows: card titles and outcomes carry
    # umlauts and arrows (U+2192), and a bare python.exe stdout is cp1252 - the
    # --full path died on UnicodeEncodeError the first time it was run, which is
    # exactly the trap copilot.py already documents for the driver's own pipes.
    # errors="replace" over a crash: a mangled glyph still answers the question.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from cells.copilot.chat.copilot import _snapshot
    out = _snapshot(full=full)
    # stdout is the product - print nothing else, this is read by an agent.
    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    import ctxout
    raise SystemExit(ctxout.run(main, sys.argv[1:], "board_state", cap=16_000))
