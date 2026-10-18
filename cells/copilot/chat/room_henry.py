# -*- coding: utf-8 -*-
"""Henry inside a team room (backlog/team-rooms-member, stage 4).

WHY THIS IS NOT copilot.chat(). chat() is the OWNER's Henry: one resumable
session per person, the board brief (owner facts, cards, prices), hands,
actions. A room is read by several people, so Henry here is a different, much
smaller thing, by construction rather than by instruction:

  - ONE-SHOT and stateless: no --resume, no session pointer. Everything he
    knows is rebuilt from the RECORD each turn - the room's history (every line
    carries its author's name) and the room's memory. Nothing is remembered in a
    hidden per-person transcript another member could not see.
  - NO TOOLS (`--tools ""`), permission mode plan, no MCP, no ambient settings
    layer. He cannot touch the machine even if a message asks him to; the
    refusal is the CLI's, not a sentence in a prompt (owner decree: "invariants
    -> code").
  - HIS OWN BRIEF (harness/agents/room-henry.md), not board-copilot - that one
    carries the owner's machine and money.
  - memory: only the room's notes are read (copilot_memory.room_viewer) and any
    save lands in the room scope. The asker's private notes never ride in -
    everyone in the room reads the answer.
  - he answers ONLY on @henry, to the author of THAT message, by name.

ORDER. One lock per room: two asks at once are answered one after the other,
each turn rebuilding its context from the record at the moment it runs, so the
second answer already includes the first. A new message NEVER interrupts a turn
in progress (the owner chat's last-wins steer would let one member's message
cancel another's answer); a bounded queue stops a flood from burning the plan.
"""
import json
import os
import subprocess
import tempfile
import threading
import time

from cells.copilot.chat import rooms, copilot_memory
from spine.agent import proctable

HISTORY_LINES = 30
MEMORY_BUDGET = 6000            # chars of room notes handed over in full
TIMEOUT = 180
MAX_QUEUED = 3                  # asks waiting behind the running one
MODEL = "sonnet"                # whitelist alias, same family the cards route to

_HERE = os.path.dirname(os.path.abspath(__file__))
BRIEF = os.path.join(os.path.dirname(_HERE), "harness", "agents", "room-henry.md")
_FALLBACK_BRIEF = ("Du bist Henry in einem Team-Raum. Antworte nur der Person, die dich "
                   "mit @henry gefragt hat, kurz, mit Namen, nur beratend und ohne "
                   "Werkzeuge. Erfinde nichts.")

_locks = {}
_waiting = {}
_live_n = {}                    # rid -> Henry turns accepted and not yet ended
_live_since = {}                # rid -> epoch the room's busy spell began
_guard = threading.Lock()


def _render(txt, surface="room"):
    """Splice the owner's behaviour rules (Notizen anlegen) into the brief. Total:
    a broken rule table costs the setting, never the answer."""
    try:
        from spine.registry import behavior
        return behavior.render(txt, surface)
    except Exception:                                        # noqa: BLE001
        return txt


def brief():
    """Read at CALL time, so an edit applies on the next turn with no restart.
    A missing/unreadable file costs the customisation, never the answer."""
    try:
        with open(BRIEF, encoding="utf-8") as f:
            txt = f.read().strip()
        return _render(txt) if txt else _FALLBACK_BRIEF
    except OSError:
        return _FALLBACK_BRIEF


def memory_block(rows):
    """The room's notes IN FULL, newest first, within MEMORY_BUDGET. A room
    holds a handful of notes, so they ride whole: the owner chat's recall (IDF
    over a big corpus) finds nothing in a store this small, and its overview
    points at a `find` tool a room turn does not have."""
    out, used, cut = [], 0, False
    ordered = sorted(rows.items(), key=lambda kv: kv[1].get("updated_at") or "",
                     reverse=True)
    for name, r in ordered:
        body = (r.get("content") or "").strip()
        if used + len(body) > MEMORY_BUDGET:
            cut = True
            break
        used += len(body)
        out.append("=== %s [%s]\n%s" % (name.split("/", 1)[-1],
                                        (r.get("updated_at") or "")[:10], body))
    if not out and not cut:
        return ""
    if cut:
        rest = [n.split("/", 1)[-1] for n, _r in ordered[len(out):]]
        out.append("(+%d Notizen nicht gezeigt, Budget von %d Zeichen erschoepft: %s)"
                   % (len(rest), MEMORY_BUDGET,
                      ", ".join(rest[:8]) + (" ..." if len(rest) > 8 else "")))
    return "\n\nNOTIZEN DIESES RAUMS (alle im Raum lesen sie):\n" + "\n\n".join(out)


def build_prompt(room, history, author, text, rows):
    """The turn, assembled ONLY from the record: members, the room's notes, the
    last HISTORY_LINES messages with their authors, and the question."""
    lines = []
    for m in history[-HISTORY_LINES:]:
        lines.append(_line(m))
    win = ("nur die letzten %d von %d Nachrichten, aelteste zuerst; Aelteres steht hier nicht"
           % (HISTORY_LINES, len(history)) if len(history) > HISTORY_LINES
           else "aelteste zuerst; alle %d Nachrichten" % len(history))
    others = [m for m in room["members"] if m != author]
    return ("RAUM: %s\nMITGLIEDER: %s%s\n\nVERLAUF (%s):\n%s\n\n"
            "NEUE NACHRICHT von %s, die dich mit @henry anspricht:\n%s\n\n"
            "Der Fragende heisst genau \"%s\" (ein Kontoname, keine Rolle)%s. "
            "Antworte %s direkt."
            % (room["name"], ", ".join(room["members"]), memory_block(rows), win,
               "\n".join(lines) or "(noch leer)", author, text, author,
               "; die anderen Mitglieder (%s) haben NICHT gefragt" % ", ".join(others) if others else "",
               author))


# ---------------------------------------------------------------- the room's session
# ONE resumable Henry conversation per room (owner 2026-10-12: "jeder Raum hat eine
# id und kann resumt werden"). Same homes the board chat and a card chat already
# use, keyed by the room instead of the user - no new table:
#   session pointer  copilot._sessions()      {skey: sid}
#   model pick       copilot._model_prefs()   {skey: cli model}
#   economics/meter  copilot_stats._stats()   {skey: ctx_tokens, ctx_window, ...}
# The room RECORD stays the source of truth: the session is a cache of it. A lost
# or rotated session is rebuilt from the record (build_prompt), never lost.


def skey(rid):
    """The identity of one room conversation. NUL-prefixed like a card key, so it
    can never equal an account name (a bare user key is the board chat)."""
    return "\x00room:" + rid


def session_id(rid):
    from cells.copilot.chat import copilot
    return copilot._sessions().get(skey(rid)) or ""


def drop_session(rid, why=""):
    """Forget the room's session (resume failed, or the context hit the mark): the
    next turn rebuilds from the record. The meter reads 0 until that turn reports
    a real figure - never the old session's."""
    from cells.copilot.chat import copilot, copilot_stats
    sess = copilot._sessions()
    if sess.pop(skey(rid), None) is not None:
        copilot._save_sessions(sess)
    st = copilot_stats._stats()
    m = st.get(skey(rid))
    if m:
        m.pop("ctx_tokens", None)
        m["rotated_at_turn"] = int(m.get("turns") or 0)
        copilot_stats._save_stats(st)
    try:
        from spine.storage import events
        events.emit("room", rid, action="session_dropped", why=why[:120])
    except Exception:                                            # noqa: BLE001
        pass


def forget(rid):
    """The room is gone: its session pointer, model pick and stats go with it."""
    from cells.copilot.chat import copilot, copilot_stats
    k = skey(rid)
    sess = copilot._sessions()
    if sess.pop(k, None) is not None:
        copilot._save_sessions(sess)
    prefs = copilot._model_prefs()
    if prefs.pop(k, None) is not None:
        from spine.storage import db
        db.doc_put(copilot._MODELS_KEY, prefs)
    st = copilot_stats._stats()
    if st.pop(k, None) is not None:
        copilot_stats._save_stats(st)


def stats(rid):
    """What the room's meter and picker read (served with GET /rooms/messages)."""
    from cells.copilot.chat import copilot, copilot_stats
    m = copilot_stats._stats().get(skey(rid)) or {}
    return {"turns": int(m.get("turns") or 0), "ctx_tokens": m.get("ctx_tokens"),
            "ctx_window": m.get("ctx_window"), "cost": m.get("cost") or 0,
            "model": copilot._model_prefs().get(skey(rid)) or ""}


def pick_model(rid, author, pick, text):
    """The CLI model of this turn. The OWNER's explicit pick wins and becomes the
    room's sticky model (copilot.chat's order: pick > recorded > default); a
    member's pick is ignored - everyone's turns spend the owner's plan. The
    window law of turnopts still applies to whatever wins."""
    from cells.copilot.chat import copilot
    from spine.agent import turnopts
    k = skey(rid)
    owner = _is_owner(author)
    explicit = (pick or "").strip() if owner else ""
    pick = explicit if explicit and explicit != "auto" else (copilot._model_prefs().get(k) or MODEL)
    ctx = stats(rid).get("ctx_tokens")
    cli, _ = turnopts.resolve_model(pick, text, False, signals={"ctx_tokens": ctx}, account=author)
    cli = cli or MODEL
    if explicit:
        copilot._save_model_pref(k, cli)
    return cli


def maybe_rotate(rid):
    """Compaction for a room: at the board chat's own mark (copilot._compact_mark)
    the session is dropped and rebuilt from the record. The record already IS the
    durable truth of a shared conversation, so this is cheap and safe; a true
    /compact for rooms is registered debt (spine/registry/debt.py)."""
    from cells.copilot.chat import copilot, copilot_stats
    m = copilot_stats._stats().get(skey(rid)) or {}
    mark, why = copilot._compact_mark(m)
    if session_id(rid) and int(m.get("ctx_tokens") or 0) >= mark:
        drop_session(rid, "context %dk >= %s mark" % (int(m["ctx_tokens"]) // 1000, why))
        return True
    return False


def on_result(rid, raw, ctx_usage):
    """A room turn finished (guest path AND the owner's hands run): the session
    pointer advances only on the runtime's own result event, and the economics
    fold at event time into the room's stats (copilot_stats._fold_stats, the one
    owner - it also records the spend)."""
    from cells.copilot.chat import copilot, copilot_stats
    if not isinstance(raw, dict) or raw.get("is_error"):
        return
    sid = raw.get("session_id")
    if sid:
        sess = copilot._sessions()
        if sess.get(skey(rid)) != sid:
            sess[skey(rid)] = sid
            copilot._save_sessions(sess)
    copilot_stats._fold_stats(skey(rid), raw, ctx_usage)


def _line(m):
    who = "Henry" if m.get("byKind") == "henry" else (m.get("by") or "?")
    q = m.get("reply_to") or {}
    quote = ('(Antwort auf %s: "%s") ' % (q.get("by") or "eine Nachricht", q.get("text", "")[:200])
             if q.get("text") else "")
    return "[%s %s] %s: %s%s" % (m.get("date", ""), m.get("ts", ""), who, quote,
                                  (m.get("text") or "").replace("\r", ""))


def delta_prompt(room, history, author, text):
    """A RESUMED turn: the session already holds everything up to Henry's last
    answer, so only what the room said since (incl. the question) rides in -
    derived from the record, no stored cursor. An errored Henry row never
    advanced the session, so it does not count as his last answer."""
    last = -1
    for i, m in enumerate(history):
        if m.get("byKind") == "henry" and not m.get("error"):
            last = i
    new = history[last + 1:][-HISTORY_LINES:]
    return ("NEU IM RAUM %s seit deiner letzten Antwort (aelteste zuerst):\n%s\n\n"
            "Die Nachricht von %s, die dich mit @henry anspricht, ist die letzte. "
            "Antworte %s direkt." % (room["name"], "\n".join(_line(m) for m in new) or "(nichts)",
                                    author, author))


def turn_prompt(room, history, author, text, rows, thinking=""):
    """(prompt, resumed): the delta on a live session, else the whole record."""
    from spine.agent import turnopts
    if session_id(room["id"]):
        body, resumed = delta_prompt(room, history, author, text), True
    else:
        body, resumed = build_prompt(room, history, author, text, rows), False
    return turnopts.augment_prompt(body, thinking, []), resumed


def _argv(model=None, resume=""):
    from cells.copilot.chat import copilot
    return ([copilot.CLAUDE, "-p", "--output-format", "json", "--permission-mode", "plan",
             "--tools", "", "--model", model or MODEL, "--setting-sources", ""]
            + (["--resume", resume] if resume else []) + copilot._lean_mcp_args())


def _empty_cwd():
    """An EMPTY directory outside the repo: the CLI auto-loads CLAUDE.md and its
    per-project auto-memory from the cwd, and the repo's own (HelmDeck's laws,
    the owner's notes) must never reach a room turn."""
    d = os.path.join(tempfile.gettempdir(), "helmdeck-room-henry")
    os.makedirs(d, exist_ok=True)
    return d


def live_key(rid):
    """livebuf key for a room's in-flight Henry turn (same shape as the board
    chat's copilot._live_key: partial / thinking / status / steps)."""
    return "room:" + rid


def live_begin(rid):
    """A Henry turn for this room is accepted (queued or running). The count is
    the room's `running` signal, observed - never a stored flag."""
    with _guard:
        _live_n[rid] = _live_n.get(rid, 0) + 1
        _live_since.setdefault(rid, time.time())


def live_turn(rid):
    """A queued turn gets the lock: its fields start empty, not on the last
    answer's text."""
    from spine.agent import livebuf
    livebuf.clear(live_key(rid))


def live_end(rid):
    from spine.agent import livebuf
    with _guard:
        n = max(0, _live_n.get(rid, 0) - 1)
        _live_n[rid] = n
        if n:
            return
        _live_since.pop(rid, None)
    livebuf.clear(live_key(rid))


def live_prose(text):
    """What the room may watch typing: the reply without a half-typed
    <memory-save> block (that is bookkeeping, never prose)."""
    i = (text or "").lower().find("<memory-")
    return (text if i < 0 else text[:i]).strip()


def live_text(rid, parts):
    from spine.agent import livebuf
    livebuf.set_partial(live_key(rid), live_prose("".join(parts)))


def live_event(rid, ev, parts, think):
    """Fold one stream-json event of a room turn into the live buffer. The
    same events copilot.chat() folds for the board chat, minus the tools (a
    room turn has none unless it is the owner's run - see live_steps)."""
    from spine.agent import livebuf
    key = live_key(rid)
    if ev.get("type") != "stream_event":
        return
    e = ev.get("event") or {}
    t = e.get("type")
    if t == "message_start":
        livebuf.set_field(key, "status", "")
    elif t == "content_block_start":
        bt = (e.get("content_block") or {}).get("type") or ""
        livebuf.set_field(key, "status", "" if bt in ("thinking", "text") else
                          livebuf.get_field(key, "status", ""))
    elif t == "content_block_delta":
        dl = e.get("delta") or {}
        if dl.get("type") == "text_delta":
            parts.append(dl.get("text", ""))
            live_text(rid, parts)
        elif dl.get("type") == "thinking_delta":
            think.append(dl.get("thinking", ""))
            livebuf.set_field(key, "thinking", "".join(think)[-600:])


def live_steps(rid, steps):
    """The owner's run in a room: its tool steps, in the chat's live-step shape."""
    from spine.agent import livebuf
    livebuf.set_field(live_key(rid), "steps", json.dumps([
        {"id": s.get("id", ""), "tool": s.get("tool") or s.get("label") or "tool",
         "label": s.get("label") or "tool", "text": s.get("text") or "",
         "status": s.get("status") or "running", "ta": s.get("ta")} for s in steps[-12:]]))


def live(rid):
    """GET /rooms/live: what Henry is doing in this room right now."""
    from spine.agent import livebuf
    key = live_key(rid)
    try:
        steps = json.loads(livebuf.get_field(key, "steps", "[]") or "[]")
    except ValueError:
        steps = []
    with _guard:
        running = _live_n.get(rid, 0) > 0
        since = _live_since.get(rid) if running else None
    return {"text": livebuf.get_field(key, "partial", ""),
            "thinking": livebuf.get_field(key, "thinking", ""),
            "status": livebuf.get_field(key, "status", ""),
            "steps": steps if isinstance(steps, list) else [],
            "running": running, "since": since}


def run_claude(system, prompt, timeout=TIMEOUT, live=None, model=None, resume="", rid=None):
    """The ONE place this module spawns the CLI: (reply text, raw result event).
    stdin carries the turn; the brief goes as a FILE (Windows' command-line cap,
    see copilot._brief_file). stream-json, so room `live` (a room id) can watch
    the reply and the reasoning arrive; the result event is the same dict the
    old one-shot json output was. `resume` = the room's session id; `rid` = the
    room whose session/meter this turn feeds (on_result) - absent for the private
    Henry, which stays one-shot."""
    from cells.copilot.chat import copilot
    from spine.agent import drivers
    from spine.agent.spawnenv import tool_path
    argv = _argv(model, resume) + ["--system-prompt-file", copilot._brief_file(system)]
    i = argv.index("json")                       # _argv's "--output-format json"
    argv[i:i + 1] = ["stream-json", "--verbose", "--include-partial-messages"]
    p = subprocess.Popen(drivers._cmd_line(argv), cwd=_empty_cwd(), stdin=subprocess.PIPE,
                         env=tool_path(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    proctable.own(p)
    errbuf = []
    threading.Thread(target=lambda: errbuf.append(p.stderr.read() or ""), daemon=True).start()
    timed_out = []

    def _kill():
        timed_out.append(1)
        proctable.kill_owned(p)
    timer = threading.Timer(timeout, _kill)
    timer.start()
    raw, parts, think, last_usage = None, [], [], None
    try:
        try:
            p.stdin.write(prompt)
            p.stdin.close()
        except OSError:
            pass
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result":
                raw = ev
            elif ev.get("type") == "assistant":     # the LAST call's usage = the context fill
                u = (ev.get("message") or {}).get("usage")
                if isinstance(u, dict) and u:
                    last_usage = u
            elif live:
                live_event(live, ev, parts, think)
        p.wait()
    finally:
        timer.cancel()
        if p.poll() is None:
            proctable.kill_owned(p)
    if timed_out:
        raise subprocess.TimeoutExpired(argv, timeout)
    if raw is None:
        time.sleep(0.05)                          # let the stderr reader land
        raise RuntimeError("no model output: " + ("".join(errbuf) or "").strip()[:200])
    try:
        if rid and not raw.get("is_error"):
            on_result(rid, raw, last_usage)            # session pointer + meter + spend
        else:                              # the plan calibration's share of it
            from spine.turn import econ
            econ.record_spend("room", list((raw.get("modelUsage") or {}).keys()),
                              raw.get("usage"), raw.get("total_cost_usd"))
    except Exception:                                            # noqa: BLE001
        pass
    if resume and raw.get("is_error"):
        raise RuntimeError("resume failed: " + str(raw.get("result") or "")[:160])
    return (raw.get("result") or "").strip(), raw


def _is_owner(author):
    """The role is read from the account record at the moment of the turn - the
    one fact that decides which Henry answers (never a flag on the message)."""
    from spine.auth import auth
    return any(u["name"] == author and u["role"] == "owner" for u in auth.list_users())


OWNER_BRIEF = os.path.join(os.path.dirname(_HERE), "harness", "agents", "room-henry-owner.md")


def owner_brief():
    try:
        with open(OWNER_BRIEF, encoding="utf-8") as f:
            return f.read().strip() or _FALLBACK_BRIEF
    except OSError:
        return _FALLBACK_BRIEF


def _shared_projects_block(room, author):
    """The project folders shared with this room's other members - the work the
    owner wants to show them. Derived from the project records at the moment of
    the turn; the owner's agent may read these folders."""
    from spine.ops import projects
    others = {m for m in room["members"] if m != author}
    rows = [p for p in projects.list_projects()
            if p.get("repo") and others & set(p.get("geteilt_mit") or [])]
    if not rows:
        return ""
    return ("\n\nMIT DEM RAUM GETEILTE PROJEKTE (du darfst diese Ordner lesen):\n"
            + "\n".join("- %s: %s" % (p["name"], p["repo"]) for p in rows))


def _owner_turn(room, author, text, opts=None):
    """The OWNER asks in a room. His own Henry answers, as ITS OWN RUN beside his
    main chat (hands.spawn kind="agent": a one-shot child with his tools, no
    session, no shared per-user chat state), so a room question neither waits for
    nor interrupts what he is doing in the chat. The answer is posted into the
    room when the run ends (hands._land_room). He is read-only here: no cards,
    no files, no settings - a request for action comes back as a sentence.
    A non-owner never gets here (this runs on the owner's tools)."""
    from cells.copilot.chat import hands
    viewer = copilot_memory.room_viewer(room["id"])
    rows = copilot_memory.all_notes(viewer)
    opts = opts or {}
    maybe_rotate(room["id"])
    prompt, resumed = turn_prompt(room, rooms.history(room["id"], author), author, text, rows,
                                  opts.get("thinking", ""))
    task = prompt + _shared_projects_block(room, author)
    try:
        hands.spawn(author, task, skey=author, kind="agent", brief_text=owner_brief(),
                    room={"id": room["id"], "to": author},
                    why="@henry im Raum %s" % room["name"],
                    model=pick_model(room["id"], author, opts.get("model"), text),
                    resume=session_id(room["id"]) if resumed else "")
    except Exception as e:                                       # noqa: BLE001
        return rooms.post(room["id"], "Henry", "Ich konnte gerade nicht antworten (%s)."
                          % str(e)[:120], by_kind="henry", extra={"to": author, "error": True})
    return None


def _lock_for(rid):
    with _guard:
        return _locks.setdefault(rid, threading.Lock())


def answer(rid, author, text, runner=None, opts=None):
    """One Henry turn in room `rid`, in answer to `author`'s message. Blocks on
    the room's lock (the queue), reads the record at THAT moment, stores the
    reply (or an honest failure note) and returns the stored message, or None
    when the queue is full. `runner(system, prompt) -> (text, raw)` is the seam
    the tests use; production uses run_claude. `opts` = {model, thinking} of the
    asking message (only the owner's pick counts, see pick_model)."""
    opts = opts or {}
    owner_turn = runner is None and _is_owner(author)   # a test seam runner always wins
    seam = runner
    with _guard:
        if _waiting.get(rid, 0) >= MAX_QUEUED:
            return None
        _waiting[rid] = _waiting.get(rid, 0) + 1
    live_begin(rid)
    handed_off = False         # the owner's run ends the live spell itself (hands._land_room)
    try:
        with _lock_for(rid):
            room = rooms.get(rid)
            if not room:
                return None
            live_turn(rid)
            if owner_turn:
                posted = _owner_turn(room, author, text, opts)
                handed_off = posted is None
                return posted
            viewer = copilot_memory.room_viewer(rid)
            rows = copilot_memory.all_notes(viewer)
            hist = rooms.history(rid, author)
            try:
                if seam:
                    reply, _raw = seam(brief(), build_prompt(room, hist, author, text, rows))
                else:
                    maybe_rotate(rid)
                    model = pick_model(rid, author, opts.get("model"), text)
                    prompt, resumed = turn_prompt(room, hist, author, text, rows, opts.get("thinking", ""))
                    try:
                        reply, _raw = run_claude(brief(), prompt, live=rid, model=model, rid=rid,
                                                 resume=session_id(rid) if resumed else "")
                    except Exception:                            # noqa: BLE001
                        if not resumed:
                            raise
                        # the session is gone / refused: the record rebuilds it, once
                        drop_session(rid, "resume failed")
                        prompt, _ = turn_prompt(room, hist, author, text, rows, opts.get("thinking", ""))
                        reply, _raw = run_claude(brief(), prompt, live=rid, model=model, rid=rid)
            except Exception as e:                               # noqa: BLE001
                return rooms.post(rid, "Henry", "Ich konnte gerade nicht antworten (%s)."
                                  % str(e)[:120], by_kind="henry", extra={"to": author, "error": True})
            reply, muts = copilot_memory.parse(reply)
            if muts:
                copilot_memory.apply(muts, actor="henry", source="room:%s" % rid,
                                     scope=copilot_memory.scope_for(viewer, room=rid),
                                     viewer=viewer)
            if not reply:
                reply = "(keine Antwort)"
            return rooms.post(rid, "Henry", reply, by_kind="henry", extra={"to": author})
    finally:
        with _guard:
            _waiting[rid] = max(0, _waiting.get(rid, 1) - 1)
        if not handed_off:
            live_end(rid)


def maybe_answer(msg, background=True, runner=None, opts=None):
    """Called by the route after a HUMAN message landed. Starts Henry only when
    the message mentions him AND the room allows it; Henry's own messages never
    reach here, so he can never trigger himself."""
    if msg.get("byKind") != "human" or not msg.get("henry"):
        return False
    room = rooms.get(msg["room_id"]) if msg.get("room_id") else None
    if not room or not room.get("henry_on_mention", True):
        return False
    args = (msg["room_id"], msg["by"], msg["text"], runner, opts)
    if background:
        threading.Thread(target=answer, args=args, daemon=True,
                         name="room-henry:%s" % msg["room_id"]).start()
    else:
        answer(*args)
    return True
