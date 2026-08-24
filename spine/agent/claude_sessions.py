# -*- coding: utf-8 -*-
"""Read the user's EXISTING Claude Code sessions from ~/.claude/projects so
HelmDeck can list and continue them - the Paseo 'session import' idea. A real
Claude Code session is a <uuid>.jsonl transcript under
~/.claude/projects/<encoded-cwd>/; `claude --resume <uuid>` continues it. We
surface: id (uuid), cwd, project label, first user message, last activity.
Nothing here mutates the sessions - it only reads them."""
import json, os, re, threading, time

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
HEAD_LINES = 60          # enough to find cwd + the first user message
MAX = 40                 # most-recent sessions
# Per-step content caps. Author/agent messages and plans are bounded by the
# model's context, so cap them high enough to never clip a real message (the
# old 8000 chopped long answers). Tool results can be genuinely huge (file
# dumps, command output) and the whole transcript is refetched per tick, so
# keep a generous-but-finite cap - the tool card is scrollable/expandable.
MAX_TEXT = 200_000
MAX_THINK = 60_000
# tool results are re-sent on every live tick and sit behind an expander, so
# keep them moderate - the whole transcript is refetched while a turn runs.
MAX_RESULT = 8_000
# HelmDeck's own spawned sessions (Henry, process designer) - not the user's
# coding sessions, so hide them from the import list.
#
# BOTH the new and the OLD opening line are listed, and the old one must STAY.
# This matches the system prompt recorded INSIDE each transcript on disk, so it
# is effectively a historical file format: every session spawned before the
# 2026-08-17 rename still opens "You are the HelmDeck board copilot". Replacing
# instead of appending would have made all of those reappear in the owner's
# import list - a silent regression, no error, on a surface nobody would think
# to re-check after a rename.
_INTERNAL = ("You are Henry", "You are the HelmDeck board copilot",
             "You are a process designer")


def _first_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                return part.get("text") or ""
    return ""


def _peek(path):
    """Read the head of a transcript for cwd + first user message (cheap)."""
    cwd, first = None, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= HEAD_LINES and cwd and first:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                cwd = cwd or d.get("cwd")
                m = d.get("message")
                if first is None and isinstance(m, dict) and m.get("role") == "user":
                    t = _first_text(m.get("content")).strip()
                    if t and not t.startswith("<"):     # skip tool/system envelopes
                        first = t
    except OSError:
        pass
    return cwd, first


def list_sessions(limit=MAX):
    """All Claude Code sessions, most-recently-active first. Skips HelmDeck's
    own worktree sessions (those are already cards)."""
    out = []
    if not os.path.isdir(PROJECTS):
        return out
    for proj in os.listdir(PROJECTS):
        pdir = os.path.join(PROJECTS, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, fn)
            try:
                mtime = os.path.getmtime(path)
                size = os.path.getsize(path)
            except OSError:
                continue
            if size < 200:              # empty/aborted transcript
                continue
            cwd, first = _peek(path)
            if cwd and "helmdeck-worktrees" in cwd.replace("/", "\\"):
                continue                # HelmDeck-managed - already a card
            if first and first.startswith(_INTERNAL):
                continue                # HelmDeck's own copilot/process session
            out.append({
                "id": fn[:-6],          # strip .jsonl -> the session uuid
                "cwd": cwd or "",
                "project": os.path.basename(cwd) if cwd else proj,
                "first": (first or "")[:160],
                "last_active": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                "mtime": mtime,
            })
    out.sort(key=lambda s: s["mtime"], reverse=True)
    out = out[:limit]
    # Annotate sessions ALREADY BOUND to a card (derived from the track store -
    # the one owner of that binding - never guessed from paths). The worktree
    # filter above misses machine/adopted cards (their cwd is a real folder,
    # e.g. the home dir), so the picker offered them, the owner selected one,
    # and only the SUBMIT bounced with "session already on the board" - a
    # dead end. With `card` set, the app renders the row as a link to the
    # owning card instead of a selectable option.
    try:
        from cells.engineer import sessions as _s
        owner = {}
        for t in _s._load():
            for sid in [t.get("session_id")] + list(t.get("session_chain") or []):
                if sid:
                    owner[sid] = t["id"]
        for s in out:
            tid = owner.get(s["id"])
            if tid:
                s["card"] = tid
    except Exception:
        pass                       # annotation is best-effort, the guard still holds
    return out


# --- full turn-by-turn transcript of a session (the Paseo agent view) --------
# parsed steps of ROTATED-AWAY sessions (immutable once left) - see the
# session_chain rendering in read_transcript_live
_chain_cache = {}


def _find_transcript(session_id):
    if not session_id or not os.path.isdir(PROJECTS):
        return None
    for proj in os.listdir(PROJECTS):
        cand = os.path.join(PROJECTS, proj, session_id + ".jsonl")
        if os.path.exists(cand):
            return cand
    return None


def _tail_lines(path, max_bytes=1_200_000):
    """Read only the last ~max_bytes so a huge transcript doesn't blow up polls."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read()
    lines = data.decode("utf-8", "replace").split("\n")
    return lines[1:] if size > max_bytes else lines   # drop the partial first line


# Incremental per-session parse cache. A session .jsonl only ever APPENDS, so
# every already-parsed line is immutable - fold the NEW bytes in at event time
# (the Paseo principle: derive from the runtime's own signal, one owner, no
# re-scan). This replaces the 1.2MB tail cap for the CARD FEED: a screenshot-
# heavy Playwright turn grew its session to 6.4MB and the tail cap silently
# dropped the first ~80% of the conversation from the chat (2026-08-20,
# "full conversation not shown"). A shrunk file means rotation -> full reparse.
_OBJS_LOCK = threading.Lock()
_OBJS_CACHE = {}       # path -> {"read": consumed bytes, "buf": partial line, "objs": [dict]}
_OBJS_CACHE_MAX = 6    # sessions watched at once; each can hold a few MB of objects


def _session_objects(path):
    """All parsed json objects of a session .jsonl, reading only appended bytes."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    with _OBJS_LOCK:
        ent = _OBJS_CACHE.get(path)
        if ent is None or size < ent["read"]:
            ent = {"read": 0, "buf": b"", "objs": []}
            _OBJS_CACHE[path] = ent
            while len(_OBJS_CACHE) > _OBJS_CACHE_MAX:
                _OBJS_CACHE.pop(next(iter(k for k in _OBJS_CACHE if k != path)))
        if size > ent["read"]:
            with open(path, "rb") as f:
                f.seek(ent["read"])
                chunk = f.read()
            ent["read"] += len(chunk)
            buf = ent["buf"] + chunk
            nl = buf.rfind(b"\n")
            if nl < 0:
                ent["buf"] = buf          # still mid-line (agent mid-flush)
            else:
                complete, ent["buf"] = buf[:nl], buf[nl + 1:]
                for line in complete.decode("utf-8", "replace").split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ent["objs"].append(json.loads(line))
                    except ValueError:
                        continue
        return ent["objs"]


def live_session_id(track):
    """The session whose transcript is CURRENT for this card.

    While a turn RUNS, `claude --resume` has already rotated to a new session
    id (written to live_session.txt by the driver) - the recorded session_id
    still points at the previous file, which contains neither the user's new
    message nor any of the new steps. Reading the old file made a running
    steer look frozen. So: running turn -> live file first; otherwise the
    recorded id (with the live file as the turn-1 fallback)."""
    run_dir = (track or {}).get("run_dir") or ""
    live = None
    if run_dir:
        try:
            with open(os.path.join(run_dir, "live_session.txt"), encoding="utf-8") as f:
                live = f.read().strip() or None
        except OSError:
            pass
    if (track or {}).get("status") == "running" and live:
        return live
    return (track or {}).get("session_id") or live


def transcript_version(track):
    """A change token for the card's live FEED: bytes of the current session
    .jsonl + the driver's live_partial.txt + the flight recorder's
    actions.jsonl. It bumps whenever the agent flushes a block, streams a
    token, OR the harness records a lifecycle note. This is the long-poll key
    that lets the phone get PUSH latency over the sealed relay (which can't
    carry SSE): the /transcript/live endpoint blocks until this changes.

    actions.jsonl is in the token because the card feed WEAVES those notes in
    (see the client's feed memo). Keyed on agent output alone, a lane move -
    gate verdict, merge, bounce - changed nothing the poll could see, so the
    notes sat on disk until the screen was remounted. All three files only
    ever grow, so summing sizes stays monotonic."""
    run_dir = (track or {}).get("run_dir") or ""
    sid = live_session_id(track)
    jp = _find_transcript(sid) if sid else None
    js = os.path.getsize(jp) if jp and os.path.exists(jp) else 0
    lp = os.path.join(run_dir, "live_partial.txt") if run_dir else None
    ls = os.path.getsize(lp) if lp and os.path.exists(lp) else 0
    ap = os.path.join(run_dir, "actions.jsonl") if run_dir else None
    as_ = os.path.getsize(ap) if ap and os.path.exists(ap) else 0
    return js + ls + as_


def read_transcript_live(track, limit=400):
    """read_transcript + the in-flight streaming text (driver's live_partial.txt)
    appended as a streaming step, so a turn streams token-by-token before its
    block is flushed to the .jsonl."""
    sid = live_session_id(track)
    steps = read_transcript(sid, limit) if sid else []
    # FULL history across session ROTATIONS. A compaction (or a resume of a
    # session that hit the context limit) rotates to a FRESH .jsonl carrying
    # none of the prior conversation - reading only the live `sid` made the
    # whole chat look wiped ("alle Chats einer Karte gehoeren in die Karte").
    # steer records the sessions it leaves in session_chain; render THEM TOO,
    # oldest first, each break marked with one "Kontext verdichtet" divider.
    # Rotated-away sessions are IMMUTABLE, so their parsed steps are cached -
    # the per-tick cost stays that of the live session alone.
    chain = [s for s in ((track or {}).get("session_chain") or []) if s and s != sid]
    if chain:
        prior = []
        for old_sid in chain[-4:]:            # bounded: the last 4 prior sessions
            cached = _chain_cache.get(old_sid)
            if cached is None:
                try:
                    cached = read_transcript(old_sid, limit)
                except Exception:
                    cached = []
                _chain_cache[old_sid] = cached
                while len(_chain_cache) > 12:  # bounded cache across cards
                    _chain_cache.pop(next(iter(_chain_cache)))
            if cached:
                prior += cached + [{"role": "system", "kind": "compaction",
                                    "text": "", "prev": old_sid, "ts": ""}]
        steps = (prior + steps)[-limit:]
    # A tool_use with no matching tool_result is status=running. That is only
    # true while the TURN is live; once the card is at rest (needs_you, bounced,
    # done) a resultless trailing tool means the turn was KILLED mid-tool
    # (session teardown, a 1800s kill, a daemon restart). In the 4-state model
    # (Phase 3.1) that is CANCELED - the old ad-hoc `abandoned` flag is kept as
    # a legacy alias. Left as running it shows a forever-ticking clock and no
    # final reply ("Karte fertig aber keine Antwort").
    if (track or {}).get("status") != "running":
        for st in steps:
            if st.get("running") or st.get("status") == "running":
                st["running"] = False
                st["abandoned"] = True
                st["status"] = "canceled"
                st["error"] = None
    run_dir = (track or {}).get("run_dir") or ""
    if run_dir:
        try:
            with open(os.path.join(run_dir, "live_partial.txt"), encoding="utf-8") as f:
                partial = f.read()
            # strip the question block here too: while the worker streams it,
            # the owner would otherwise watch raw protocol JSON being typed out.
            from spine.ops import ask
            partial = ask.strip_stream(partial)
            if partial.strip():
                steps.append({"role": "assistant", "kind": "text",
                              "text": partial[:MAX_TEXT], "streaming": True, "ts": ""})
        except OSError:
            pass
    return steps


def read_transcript_store(track, limit=400):
    """Card 2 CUTOVER (ops/docs/multi-engine-build-plan.md): the event-time
    timeline_store is now the PRIMARY source for a card's feed - folded live
    by the driver's own pump (drivers.py's _fold_timeline) as each block
    completes, not re-parsed from Claude Code's private ~/.claude/projects/
    **.jsonl the way read_transcript_live is. Verified against
    read_transcript_live on real dispatched turns (text, tool 4-state, todos,
    usage, a harness question, a cancel) with ops/tools/compare_timeline.py before
    this landed - see spine/registry/debt.py's
    card-feed-is-claude-private-jsonl entry for the debt this pays.

    The store is keyed by run_dir (the CARD, for its whole life), not by a
    session id - so unlike read_transcript_live it needs no live_session_id
    reasoning for mid-turn session rotation; the fold already lands in the
    right place regardless of which session is momentarily active.

    What still legitimately comes from the OLD .jsonl-based reader, exactly
    per the build plan's own design ("the old reader stays for adopting
    foreign sessions and pre-cutover session_chain history"):
      - session_chain history: conversation from BEFORE this card's store
        started recording (a rotated-away or ADOPTED foreign session) lives
        only in Claude Code's own file, never folded live.
      - live_partial.txt: an in-progress, uncommitted streaming block - the
        store only ever holds COMPLETED blocks by design (see
        _fold_timeline's docstring), so the live-typing view is unchanged.

    The abandoned-tool relabel (a resultless "running" step on an AT-REST
    card means the turn was killed mid-tool, not that it is still running)
    is reapplied here, same as read_transcript_live - the store's tool steps
    only change on an explicit tool_result patch, which never arrives for a
    killed turn."""
    from spine.agent import timeline_store
    run_dir = (track or {}).get("run_dir") or ""
    steps = timeline_store.read(run_dir, limit)
    chain = [s for s in ((track or {}).get("session_chain") or []) if s]
    if chain:
        prior = []
        for old_sid in chain[-4:]:            # bounded: the last 4 prior sessions
            cached = _chain_cache.get(old_sid)
            if cached is None:
                try:
                    cached = read_transcript(old_sid, limit)
                except Exception:
                    cached = []
                _chain_cache[old_sid] = cached
                while len(_chain_cache) > 12:
                    _chain_cache.pop(next(iter(_chain_cache)))
            if cached:
                prior += cached + [{"role": "system", "kind": "compaction",
                                    "text": "", "prev": old_sid, "ts": ""}]
        steps = (prior + steps)[-limit:]
    if (track or {}).get("status") != "running":
        for st in steps:
            if st.get("running") or st.get("status") == "running":
                st["running"] = False
                st["abandoned"] = True
                st["status"] = "canceled"
                st["error"] = None
    if run_dir:
        try:
            with open(os.path.join(run_dir, "live_partial.txt"), encoding="utf-8") as f:
                partial = f.read()
            from spine.ops import ask
            partial = ask.strip_stream(partial)
            if partial.strip():
                steps.append({"role": "assistant", "kind": "text",
                              "text": partial[:MAX_TEXT], "streaming": True, "ts": ""})
        except OSError:
            pass
    return steps


def transcript_store_version(track):
    """The long-poll change token for read_transcript_store: bytes of
    timeline.jsonl + live_partial.txt + actionlog's actions.jsonl (same three-
    file composition as transcript_version, timeline.jsonl standing in for
    the session .jsonl - see that function's docstring for why actions.jsonl
    is in the token)."""
    from spine.agent import timeline_store
    run_dir = (track or {}).get("run_dir") or ""
    tp = timeline_store._path(run_dir)
    ts = os.path.getsize(tp) if tp and os.path.exists(tp) else 0
    lp = os.path.join(run_dir, "live_partial.txt") if run_dir else None
    ls = os.path.getsize(lp) if lp and os.path.exists(lp) else 0
    ap = os.path.join(run_dir, "actions.jsonl") if run_dir else None
    as_ = os.path.getsize(ap) if ap and os.path.exists(ap) else 0
    return ts + ls + as_


def _is_steer(d):
    """True for a record that is the OWNER's message opening a turn - not a
    tool_result, not one of the envelopes Claude Code injects as role=user."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return False
    m = d.get("message")
    if not isinstance(m, dict):
        return False
    c = m.get("content")
    if isinstance(c, list) and c and all(
            isinstance(p, dict) and p.get("type") == "tool_result" for p in c):
        return False                      # a tool result, not a human turn
    lead = _first_text(c).lstrip()
    return not lead.startswith(("<task-notification>", "<system-reminder>",
                                "<local-command", "<command-", "[SYSTEM NOTIFICATION"))


def background_wait(track):
    """The cue form of background_state(): {"n","names"} or None. A transcript
    we cannot read reports None (no cue) - only the auto-continue watcher needs
    to tell "nothing outstanding" from "cannot tell", and it uses
    background_state() for exactly that."""
    state, payload = background_state(track)
    return payload if state == "waiting" else None


def background_state(track):
    """(state, payload) where state is:
        "waiting" - background tasks launched in the LAST turn have not reported
        "clear"   - the transcript was read and nothing is outstanding
        "unknown" - the transcript could not be read at all

    A turn that ends while a `run_in_background` task is still running is not
    "waiting for you"; labelling it needs_you is what put those cards in limbo.
    Completion is read off the `<task-notification>` Claude Code injects for the
    finishing task (it carries the originating <tool-use-id>), so this is the
    runtime's own signal, not a guess.

    The "unknown" state exists because the auto-continue watcher STEERS on a
    clear result, and steering costs the owner a real turn: a missing or rotated
    transcript must never be mistaken for "the build finished"."""
    # PRIMARY source: the driver's FIRST-CLASS registry, maintained at event
    # time by the pump and persisted on the track (sessions.bg_upsert - Paseo's
    # ProviderSubagentStore principle). No transcript scan, no rotation
    # blindness by construction. The 6h age cap keeps a task that never reports
    # from parking the card forever.
    reg = (track or {}).get("bg_tasks")
    if isinstance(reg, dict):
        now0 = time.time()
        # ONLY status=='running' blocks the card. completed/failed/canceled
        # tasks stay in the registry (bounded) for the clickable history but do
        # NOT count as outstanding - the reconciliation (sessions.reconcile_bg)
        # is what flips a dead process's tasks to 'canceled', which is why the
        # phantom "waiting on N" no longer grows. Missing status = an old-format
        # entry from before P2 -> treated as running (safe, ages out at 6h).
        open_reg = [v for v in reg.values()
                    if v.get("status", "running") == "running"
                    and now0 - (v.get("since") or now0) < 6 * 3600]
        if open_reg:
            names = [v.get("title") or v.get("desc") or "task" for v in open_reg[:4]]
            return "waiting", {"n": len(open_reg), "names": names}
        return "clear", None
    # FALLBACK (repair only - cards from before the registry existed): scan the
    # session chain. A background task started in an earlier turn - or before a
    # session ROTATION (every --resume writes a new .jsonl) - was invisible to
    # the old last-turn scan: background_state lied "clear", the turn ended
    # waiting_on "you", the idle-eviction guard didn't hold, and the sweeper
    # tree-killed the very task the card was waiting for ("mittendrin
    # gestorben"). Starts older than the watcher's max wait are ignored.
    sid = live_session_id(track)
    chain = [s for s in ((track or {}).get("session_chain") or []) if s and s != sid]
    paths = [p for p in (_find_transcript(s) for s in (chain[-3:] + ([sid] if sid else [])))
             if p]
    if not paths:
        return "unknown", None
    recs = []
    readable = False
    for path in paths:
        try:
            lines = _tail_lines(path)
            readable = True
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except ValueError:
                continue
    if not readable:
        return "unknown", None
    max_age = 6 * 3600                 # matches sessions._BG_MAX_WAIT_S
    now = time.time()

    def _age(d):
        try:
            from datetime import datetime
            return now - datetime.fromisoformat(
                (d.get("timestamp") or "").replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    started, agent_uses, results, done = {}, {}, {}, set()
    for d in recs:
        m = d.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list):
            for p in c:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "tool_use":
                    inp = p.get("input") if isinstance(p.get("input"), dict) else {}
                    age = _age(d)
                    if age is not None and age > max_age:
                        continue       # long-dead start - never parks the card
                    if inp.get("run_in_background"):
                        started[p.get("id")] = str(
                            inp.get("description") or inp.get("command")
                            or p.get("name") or "task")[:80]
                    elif p.get("name") in ("Task", "Agent"):
                        # subagents launch ASYNC by default (no run_in_background
                        # flag) - whether one is a background task shows in its
                        # tool_result ("Async agent launched"), paired below
                        agent_uses[p.get("id")] = str(
                            inp.get("description") or "agent")[:80]
                elif p.get("type") == "tool_result":
                    txt = p.get("content")
                    txt = txt if isinstance(txt, str) else _first_text(txt)
                    results[p.get("tool_use_id")] = str(txt or "")[:120]
        lead = _first_text(c).lstrip()
        if lead.startswith("<task-notification>"):
            hit = re.search(r"<tool-use-id>(.*?)</tool-use-id>", lead, re.S)
            if hit:
                done.add(hit.group(1).strip())
    for uid, desc in agent_uses.items():
        if "Async agent launched" in results.get(uid, ""):
            started[uid] = desc        # a live background AGENT (the scam-check case)
    open_tasks = [v for k, v in started.items() if k not in done]
    if not open_tasks:
        return "clear", None
    return "waiting", {"n": len(open_tasks), "names": open_tasks[:4]}


# -- transcript-part formatting: extracted to claude_transcript_fmt.py
# (god-file breakup). Re-imported so read_transcript/read_transcript_live
# below keep working unchanged.
from spine.agent.claude_transcript_fmt import (
    _tool_summary, _base, _first_line, _tool_label, _tool_detail, _short_ts,
    _epoch, _cmd_label, _notif_label, _CTX_SEP, _strip_ctx, _clean_text,
    _result_text)




# Labels for HelmDeck's own harness-injected turns (ask.harness_msg tags), so
# the feed shows WHAT the harness did rather than the instruction it sent.
_HARNESS_NOTE = {
    "ask-repair": "⟲ Rückfrage als Auswahl angefordert",
    "background-done": "⚙ Hintergrund-Task fertig – automatisch fortgesetzt",
}


def read_transcript(session_id, limit=400):
    """Parse a session's jsonl into ordered steps for the card's agent view -
    the full Paseo-style turn view. Steps:
      {kind:text|thinking, role, text, ts}
      {kind:tool, tool, text(summary), result, status, error, ts}
          status: running|completed|failed|canceled (failed <=> error!=null);
          `ok`/`running`/`abandoned` kept as legacy aliases of the same facts
      {kind:turn, event:canceled, ts}                      (Stop mid-turn marker)
      {kind:todos, todos:[{content,status}], ts}           (from TodoWrite)
      {kind:plan, text, ts}                                (from ExitPlanMode)
      {kind:compaction, ts}                                (context compacted)
    """
    path = _find_transcript(session_id)
    if not path:
        return []
    # incremental cache, NOT the 1.2MB tail cap - see _session_objects. The
    # step passes below stay read-only on these shared objects.
    parsed = _session_objects(path)

    # pass 1: tool_use_id -> result, so each tool call carries its own output.
    # `interrupted` marks the runtime's own Stop sentinel: that result is not an
    # ERROR of the tool but the owner's hand - the 4-state model (Paseo
    # messages.ts ToolCall*Payload) renders it canceled, never failed.
    results = {}
    for d in parsed:
        m = d.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        if not isinstance(c, list):
            continue
        for part in c:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                rt = _result_text(part)
                results[part.get("tool_use_id")] = {
                    "text": rt[:MAX_RESULT], "ok": not part.get("is_error"),
                    "interrupted": rt.lstrip().startswith("[Request interrupted by user")}

    # pass 2: emit steps in order
    steps = []
    for d in parsed:
        if d.get("type") not in ("user", "assistant"):
            continue
        # Skip synthetic records that are NOT author/agent turns: Claude Code
        # injects meta messages (skill/system prompts, command wrappers) as
        # role=user and records sub-agent (Task) internals as sidechain.
        if d.get("isMeta") or d.get("isSidechain"):
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        role = m.get("role") or d.get("type")
        ts = _short_ts(d.get("timestamp"))
        ta = _epoch(d.get("timestamp"))
        content = m.get("content")
        _lead = content if isinstance(content, str) else (next(
            (p.get("text", "") for p in content
             if isinstance(p, dict) and p.get("type") == "text"), "")
            if isinstance(content, list) else "")
        # Slash-command plumbing: Claude Code records /model (and other local
        # commands) as role=user WITHOUT isMeta - only the caveat is meta. So the
        # <command-name>/<command-args>/<local-command-stdout> envelopes leaked
        # into the feed as the HUMAN's own messages ("Set model to ..."). Keep
        # them visible but RE-ATTRIBUTE as a neutral system note (sorted by time
        # like everything else) - they are plumbing, not the human talking.
        if role == "user" and _lead.lstrip().startswith((
                "<command-name>", "<command-message>", "<command-args>",
                "<local-command-stdout>", "<local-command-stderr>")):
            lbl = _cmd_label(_lead)
            if lbl:
                steps.append({"kind": "system", "text": lbl, "ts": ts, "ta": ta})
            continue
        # HelmDeck's OWN harness-injected turns (the question-repair prompt, the
        # auto-continue after a background task) are role=user as well - that is
        # the only way to feed a message in - so without this the owner reads
        # "STOP - do not continue the work" as his own message. Re-attribute to
        # a short neutral note, exactly like the envelopes above.
        if role == "user":
            from spine.ops import ask
            _tag = ask.harness_tag(_lead)
            if _tag:
                steps.append({"kind": "system", "text": _HARNESS_NOTE.get(
                    _tag, "⚙ Harness-Hinweis"), "ts": ts, "ta": ta})
                continue
        # Background-task + harness notifications are injected as role=user too, so
        # they read as the owner's own message ("<task-notification>..." shown as a
        # right-aligned bubble). Re-attribute: a task-notification -> a short system
        # note; a bare system-reminder is dropped as pure context noise.
        if role == "user" and _lead.lstrip().startswith((
                "<task-notification>", "[SYSTEM NOTIFICATION", "<system-reminder>")):
            lbl = _notif_label(_lead)
            if lbl:
                steps.append({"kind": "system", "text": lbl, "ts": ts, "ta": ta})
            continue
        # Compaction: a session that ran out of context writes a summary as a
        # role=user message (flagged isCompactSummary, or the plain continuation
        # summary on resume). Render it as ONE small marker (Paseo-style), never
        # the raw summary text; dedupe consecutive ones.
        if d.get("isCompactSummary") or (role == "user" and _lead.lstrip().startswith(
                "This session is being continued from a previous conversation")):
            if not (steps and steps[-1].get("kind") == "compaction"):
                steps.append({"kind": "compaction", "ts": ts, "ta": ta})
            continue
        # An interrupt (Stop mid-turn, esp. during a tool call) is recorded by
        # Claude Code as a role=user message '[Request interrupted by user...]'.
        # That is the harness speaking, not the owner - as a prose bubble it read
        # like the human typed it. It is the TURN's lifecycle, so it is a typed
        # turn_canceled item (Phase 3.2), not a prose/system step.
        if role == "user" and _lead.lstrip().startswith("[Request interrupted by user"):
            steps.append({"kind": "turn", "event": "canceled", "ts": ts, "ta": ta})
            continue
        if isinstance(content, str):
            body = _clean_text(content.strip())
            if body:
                steps.append({"role": role, "kind": "text", "text": body[:MAX_TEXT], "ts": ts, "ta": ta})
            continue
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            pt = part.get("type")
            if pt == "text" and _clean_text((part.get("text") or "").strip()):
                steps.append({"role": role, "kind": "text",
                              "text": _clean_text(part["text"].strip())[:MAX_TEXT], "ts": ts, "ta": ta})
            elif pt == "thinking" and (part.get("thinking") or "").strip():
                steps.append({"role": role, "kind": "thinking", "text": part["thinking"].strip()[:MAX_THINK], "ts": ts, "ta": ta})
            elif pt == "tool_use":
                name = part.get("name") or "tool"
                inp = part.get("input") if isinstance(part.get("input"), dict) else {}
                if name == "TodoWrite":
                    todos = [{"content": str(td.get("content", ""))[:220], "status": str(td.get("status", ""))}
                             for td in (inp.get("todos") or []) if isinstance(td, dict)]
                    if todos:
                        steps.append({"kind": "todos", "todos": todos, "ts": ts, "ta": ta})
                    continue
                if name == "ExitPlanMode":
                    steps.append({"kind": "plan", "text": str(inp.get("plan", ""))[:MAX_TEXT], "ts": ts, "ta": ta})
                    continue
                res = results.get(part.get("id"))
                # 4-state tool-call model (Phase 3.1, Paseo parity):
                # running | completed | failed | canceled, failed <=> error!=null.
                # An interrupt sentinel is canceled (the owner's hand, error null).
                if res is None:
                    status, err = "running", None
                elif res.get("interrupted"):
                    status, err = "canceled", None
                elif not res.get("ok", True):
                    status, err = "failed", (res.get("text") or "error")[:500]
                else:
                    status, err = "completed", None
                _lbl, _sub = _tool_label(name, inp)
                step = {"role": role, "kind": "tool", "tool": name,
                        "label": _lbl,
                        "text": _sub or _tool_summary(inp),
                        "result": (res or {}).get("text", ""),
                        "ok": (res or {}).get("ok", True),
                        "status": status, "error": err,
                        "running": res is None, "ts": ts, "ta": ta}
                detail = _tool_detail(name, inp)
                if detail:
                    step["detail"] = detail
                steps.append(step)
            # tool_result already folded into its tool step in pass 1
        # Per-turn token/context usage (DeepSeek / Claude-Code parity): each
        # assistant turn records message.usage. Surface it as one compact marker
        # so the transcript shows what THIS turn cost + the context it carried.
        if role == "assistant":
            u = m.get("usage") if isinstance(m, dict) else None
            if isinstance(u, dict):
                inp = int(u.get("input_tokens") or 0)
                out = int(u.get("output_tokens") or 0)
                cr = int(u.get("cache_read_input_tokens") or 0)
                cc = int(u.get("cache_creation_input_tokens") or 0)
                ctx = inp + cr + cc  # everything the model actually saw this turn
                if ctx or out:
                    steps.append({"kind": "usage", "tokIn": inp, "tokOut": out,
                                  "cacheRead": cr, "cacheWrite": cc, "ctx": ctx,
                                  "ts": ts, "ta": ta})
    return steps[-limit:]
