# -*- coding: utf-8 -*-
"""HENRY'S HANDS - a one-shot sub-agent with the machine tools, spawned by the
daemon on Henry's request (owner decree 2026-09-13: "Henry kann auch machen,
aber dann neuer Subagent-Spawn als schnelle Alternative zur Karte").

The three tiers, and why this one exists:
  chat   = Henry's persistent port, LEAN: no MCP servers (harness.cli_args
           gives it --setting-sources '' so the user's ~/.claude.json servers
           never load), warm, seconds.
  hands  = THIS: a fresh claude -p with the machine-card MCP bridge
           (windows-mcp, helmdeck-browser via agentcli._mcp_config_arg), a
           scratch cwd, the card guard hook, one bounded job, no card.
  card   = worktree / lane / gate / accept for real work.

Henry's own Agent tool cannot do this: a CLI sub-agent inherits the parent's
MCP configuration, and the parent is lean on purpose.

INVARIANTS (CLAUDE.md laws): the process is registered in driver_pids.json
(proctable) so a restart waits for it; every spawn and every end is an
append-only event (kind "hands"); the result lands in the owner's transcript
as an act row and in Henry's next turn (_pending_actions) - never invisible.
State here is an in-memory descriptor table mutated at exactly one owner
(this module) from the child's own stream; the UI reads it through
copilot.history()["followups"] as the same BgTask shape a card uses."""
import json
import os
import subprocess
import threading
import time
import uuid

from daemon.paths import DATA_ROOT as DAEMON_ROOT

_lock = threading.Lock()
_tasks = {}          # id -> {title, status, since, updated, detail, result, pid, user, skey, card}
_procs = {}          # id -> the live Popen (set in _run, dropped when _pump ends) - cancel()'s handle
_cancelled = {}      # id -> actor who stopped it (read by _pump to name the end "canceled")
_queue = []          # hids waiting for the desktop, FIFO
_active = None       # the ONE hands run that owns the desktop right now (mutated only in _kick/_run)
SILENCE_S = 600      # no stream output for this long = hung -> tree-kill (turn idle-watchdog parity)
MCP_GRANTS = ["mcp__windows-mcp__*", "mcp__helmdeck-browser__*"]
# ONE AT A TIME (measured 2026-09-15 18:44: Henry fanned round 2 out as three
# hands at once "in Zehner-Paketen"; all three drove the same persistent Chrome
# and the same mouse, tabs stepped on each other, the first run's end took the
# browser down and the other two died with "no close frame received or sent").
# There is one desktop and one browser, so a second hands WAITS in this
# module's own queue (the shared HelmDeck Chrome is the real reason: it is
# one profile, one tab set). The cursor itself is the DESKTOP LEASE
# (spine/git/desktop_lease.py): the guard hook takes it per windows-mcp
# control call under HELMDECK_CARD=<hid>, and _run's finally releases whatever
# this hands still holds when it ends - a hands run holds no lock for its
# life, so a card's click and a hands' HTTP fetch no longer wait on each other
# (2026-09-19: an IONOS price check sat 47 minutes behind a script card).


STEPS_KEPT = 30     # the tile's step list: the tail of the run, not its archive


def tasks(user=None, closed_within_s=3600):
    """BgTask-shaped descriptors for the chat's background line AND its live
    run tiles (owner 2026-09-25: "als Subagent-Prozess, damit man es sehen
    kann"): kind, the card it belongs to, and the tail of its tool steps.
    `user` filters to that user's runs (the line showed everyone's)."""
    now = time.time()
    out = {}
    with _lock:
        for hid, t in _tasks.items():
            if user is not None and t.get("user") not in (None, user):
                continue
            if t["status"] != "running" and now - t["updated"] > closed_within_s:
                continue
            out[hid] = _desc(t)
    return out


def _desc(t):
    """The BgTask descriptor the chat renders (tasks() and the db row)."""
    return {"title": t["title"], "status": t["status"], "since": t["since"],
            "updated": t["updated"], "detail": t["detail"], "result": t["result"],
            "kind": t.get("kind") or "hands", "card": t.get("card"),
            "steps": [dict(s) for s in t.get("steps", [])]}


def _persist(hid):
    """Write the run's descriptor to helmdeck.db (db.chat_runs) at spawn and
    at its end - the chat tile outlives the hour window and a daemon restart
    (owner 2026-09-25). Best-effort: a db hiccup never fails the run."""
    with _lock:
        t = _tasks.get(hid)
        doc, user = (_desc(t), t.get("user")) if t else (None, None)
    if doc is None:
        return
    try:
        from spine.storage import db
        db.chat_run_put(hid, user, doc)
    except Exception as e:                               # noqa: BLE001
        print("hands: run persist failed - %s" % str(e)[:160], flush=True)


def _step(hid, tool_use=None, tool_result=None):
    """Fold one tool call of the hands' OWN stream into its step list - the
    same label/subject a card's tool rows use (claude_transcript_fmt)."""
    with _lock:
        t = _tasks.get(hid)
        if t is None:
            return
        steps = t.setdefault("steps", [])
        if tool_use is not None:
            try:
                from spine.agent import claude_transcript_fmt as _fmt
                lbl, sub = _fmt._tool_label(tool_use.get("name"), tool_use.get("input") or {})
            except Exception:                                # noqa: BLE001
                lbl, sub = tool_use.get("name") or "tool", ""
            steps.append({"id": tool_use.get("id") or "", "label": lbl or tool_use.get("name") or "tool",
                          "text": (sub or "")[:140], "status": "running", "ta": time.time()})
            del steps[:-STEPS_KEPT]
        if tool_result is not None:
            for s in steps:
                if s["id"] and s["id"] == tool_result.get("tool_use_id"):
                    s["status"] = "failed" if tool_result.get("is_error") else "completed"


def _room_steps(hid, room_id):
    """Mirror an owner run's tool steps into its room's live feed."""
    if not room_id:
        return
    with _lock:
        steps = [dict(s) for s in (_tasks.get(hid) or {}).get("steps", [])]
    from cells.copilot.chat import room_henry
    room_henry.live_steps(room_id, steps)


def running_ids():
    with _lock:
        return [k for k, t in _tasks.items() if t["status"] == "running"]


def spawn(user, task, skey, card=None, why="", kind="hands", brief_text=None, room=None,
          model=None, resume=""):
    """Start the hands process for `task` and return its id immediately.

    kind="agent" (owner 2026-09-25 "wie Paseo - Thread oder Subprocess"): the
    same one-shot child for READING / research / checks, without the machine
    tools and without the desktop queue - it starts at once and runs beside
    other agents. `room` (+ `brief_text`, the system brief used instead of
    delegate.md): the OWNER's @henry in a team room - the same one-shot child,
    but its end lands as Henry's message IN THAT ROOM (see _land_room) and never
    in the owner's chat transcript, so it runs beside his main chat. Why a daemon process and not Henry's CLI Agent tool
    (MEASURED 2026-09-25 against the real CLI, stream-json): a soft interrupt
    of Henry's turn - which is how a new owner message now takes over - STOPS
    every CLI background agent of his process ("task_notification stopped").
    Paseo's children are separate agents for exactly that reason; so are
    these."""
    agent = kind == "agent"
    from cells.copilot.chat import copilot
    from spine.agent import drivers, proctable
    from spine.agent.agentcli import _mcp_config_arg
    from spine.agent.spawnenv import tool_path
    from spine.registry import harness
    from spine.storage import events

    hid = time.strftime("%Y%m%d-%H%M%S") + ("-agent-" if agent else "-hands-") + uuid.uuid4().hex[:6]
    scratch = os.path.join(DAEMON_ROOT, "state", "hands", hid)
    os.makedirs(scratch, exist_ok=True)
    title = (task or "").strip().splitlines()[0][:90] if (task or "").strip() else hid
    # a ROOM run is a turn of the room's resumable conversation: the question
    # travels as the user message (so the session keeps it), the system brief
    # stays the same every turn. Any other run carries its task in the brief.
    brief = (brief_text if brief_text is not None else harness.brief("delegate" if agent else "hands"))
    if not room:
        brief += "\n\nTASK (from Henry" + (", because: " + why if why else "") + "):\n" + task.strip() + "\n"
    argv = [copilot.CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
            "--permission-mode", copilot.henry_pmode(),
            "--append-system-prompt-file", copilot._brief_file(brief)]
    if room:                      # the room watches this run type (room_henry.live)
        argv.insert(argv.index("--verbose") + 1, "--include-partial-messages")
    argv += harness.cli_args("machine-worker")
    if model:
        argv += ["--model", model]
    if resume:
        argv += ["--resume", resume]
    # an agent needs no PC/browser: lean like Henry (no MCP servers, fast start)
    argv += copilot._lean_mcp_args() if agent else _mcp_config_arg({"allowed_tools": MCP_GRANTS}, capper=True)
    env = tool_path()
    env["HELMDECK_TOOL_SCOPE"] = "hands"
    env["HELMDECK_CARD"] = hid                 # desktop-lease owner (card_tool_guard)
    # the card guard confines file edits to HELMDECK_WORKTREE - for hands that
    # is the scratch folder (the brief says the same in prose; this is code)
    env["HELMDECK_WORKTREE"] = scratch
    env["MCP_TIMEOUT"] = env.get("MCP_TIMEOUT") or "60000"
    with _lock:
        ahead = 0 if agent else len(_queue) + (1 if _active else 0)
        _tasks[hid] = {"title": title, "status": "running", "since": time.time(), "updated": time.time(),
                       "detail": task.strip()[:600], "pid": None, "user": user, "skey": skey, "card": card,
                       "kind": kind, "room": room, "resume": resume,
                       "stdin": task.strip() if room else "", "argv": drivers._cmd_line(argv), "cwd": scratch, "env": env,
                       "result": ("wartet: %d Hände-Lauf(e) davor (ein Desktop, ein Browser)" % ahead) if ahead else ""}
        if not agent:
            _queue.append(hid)
    events.emit("hands", card or "-", action="spawned", id=hid, actor=user, task=title, why=why[:200],
                queued_behind=ahead, run_kind=kind)
    _persist(hid)
    if agent:
        # no desktop, no queue: it starts now, beside any other run
        threading.Thread(target=_run, args=(hid, False), daemon=True, name="agent-" + hid).start()
    else:
        _kick()
    return hid


def cancel(hid, actor="owner"):
    """Stop ONE hands/agent run - the daemon owns the process, so the daemon
    stops it (Paseo cancel_agent/kill_agent; owner 2026-09-25 21:44: "Stop"
    reached Henry, no verb reached the run, the X post went out anyway).
    Returns {ok, status, detail}. A queued run never starts; a running one
    has its whole tree killed and ends as "canceled" through _pump/_land -
    the same one end path every run takes."""
    from spine.agent import proctable
    from spine.storage import events
    with _lock:
        t = _tasks.get(hid)
        if t is None:
            return {"ok": False, "status": None, "detail": "kein Lauf mit id %s" % hid}
        if t["status"] != "running":
            return {"ok": False, "status": t["status"], "detail": "%s ist schon zu Ende (%s)" % (hid, t["status"])}
        queued = hid in _queue
        if queued:
            _queue.remove(hid)
            t.update(status="canceled", result="CANCELLED by %s before it started." % actor, updated=time.time())
        else:
            _cancelled[hid] = actor
        p = _procs.get(hid)
    events.emit("hands", t.get("card") or "-", action="cancel", id=hid, actor=actor, queued=queued)
    if queued:
        _land(hid, "canceled", "CANCELLED by %s before it started." % actor, 0)
        return {"ok": True, "status": "canceled", "detail": "%s gestoppt, bevor er lief" % hid}
    if p is not None:
        proctable._tree_kill(p)
    return {"ok": True, "status": "canceled", "detail": "%s gestoppt (Prozessbaum beendet)" % hid}


def find(frag):
    """The run id `frag` names - exact id first, then a unique substring of
    id or title - or a list of candidates / None (same shape as _find_card)."""
    frag = (frag or "").strip().lower()
    if not frag:
        return None
    with _lock:
        ids = list(_tasks)
        if frag in (i.lower() for i in ids):
            return next(i for i in ids if i.lower() == frag)
        hits = [i for i in ids if frag in i.lower() or frag in (_tasks[i]["title"] or "").lower()]
    return hits[0] if len(hits) == 1 else (hits or None)


def _popen(argv, cwd, env):
    """The process itself - CREATE_NO_WINDOW because the daemon is DETACHED
    (no console), so every console child it starts got a console WINDOW of
    its own; orphaned MCP children kept those alive after the run ("about 8
    empty terminal windows stacked on the desktop", 2026-09-15 = the day's 8
    hands runs). Kept separate so a test can stand in a fake process."""
    return subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8",
                            errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _kick():
    """Start the next waiting hands if none owns the desktop. The ONE place
    _active is set; _run is the one place it is cleared."""
    global _active
    with _lock:
        if _active is not None or not _queue:
            return
        hid = _queue.pop(0)
        _active = hid
    threading.Thread(target=_run, args=(hid,), daemon=True, name="hands-" + hid).start()


def _run(hid, desktop=True):
    global _active
    from spine.agent import proctable
    from spine.git import desktop_lease
    with _lock:
        t = dict(_tasks.get(hid) or {})
    try:
        p = _popen(t["argv"], t["cwd"], t["env"])
        with _lock:
            _procs[hid] = p
            if hid in _tasks:
                _tasks[hid].update(pid=p.pid, result="", updated=time.time())
            stop_now = hid in _cancelled        # stopped between spawn and Popen
        if stop_now:
            proctable._tree_kill(p)
        proctable._record_pid(p.pid, time.time())
        _pump(hid, p)
    except Exception as e:                               # noqa: BLE001
        with _lock:
            if hid in _tasks:
                _tasks[hid].update(status="failed", result="FAILED - spawn: %s" % str(e)[:300], updated=time.time())
        _land(hid, "failed", "FAILED - spawn: %s" % str(e)[:300], 0)
    finally:
        with _lock:
            _procs.pop(hid, None)
        desktop_lease.release(hid)         # event-time: a finished hands never leaves a stale lease
        if desktop:                        # an agent run never held the desktop slot
            with _lock:
                _active = None
            _kick()


def _pump(hid, p):
    from spine.agent import proctable
    try:
        with _lock:
            _stdin = (_tasks.get(hid) or {}).get("stdin")
        p.stdin.write(_stdin or "Do the TASK in your system prompt now."); p.stdin.close()
    except Exception:                                    # noqa: BLE001
        pass
    last = time.time()
    result, is_error, steps = "", False, 0
    last_usage = None              # the LAST call's usage = the room session's context fill
    watchdog = {"stop": False}
    with _lock:
        room_id = ((_tasks.get(hid) or {}).get("room") or {}).get("id")
    parts, think = [], []          # an owner run in a room streams into room_henry.live

    def _watch():
        while not watchdog["stop"]:
            if time.time() - last > SILENCE_S:
                try:
                    proctable._tree_kill(p)
                except Exception:                        # noqa: BLE001
                    pass
                return
            time.sleep(10)
    threading.Thread(target=_watch, daemon=True).start()
    for line in p.stdout:
        last = time.time()
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            _u = (ev.get("message") or {}).get("usage")
            if isinstance(_u, dict) and _u:
                last_usage = _u
            for b in ((ev.get("message") or {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    steps += 1
                    _step(hid, tool_use=b)
                    with _lock:
                        if hid in _tasks:
                            _tasks[hid]["result"] = "%d Schritte, zuletzt %s" % (steps, b.get("name"))
                            _tasks[hid]["updated"] = time.time()
                    _room_steps(hid, room_id)
        elif ev.get("type") == "user":
            for b in ((ev.get("message") or {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    _step(hid, tool_result=b)
                    _room_steps(hid, room_id)
                    # a browser screenshot the hands took is shown in the owner's chat, not lost
                    try:
                        from cells.copilot.chat import copilot as _cp
                        _owner = (_tasks.get(hid) or {}).get("user") or _cp.owner_name()
                        if _owner:
                            _cp._henry_images(_owner, b.get("content"))
                    except Exception:                    # noqa: BLE001
                        pass
        elif ev.get("type") == "stream_event" and room_id:
            from cells.copilot.chat import room_henry
            room_henry.live_event(room_id, ev, parts, think)
        elif ev.get("type") == "result":
            result = str(ev.get("result") or "")
            is_error = bool(ev.get("is_error"))
            try:
                if room_id and not is_error:      # a room turn: session pointer + meter + spend
                    from cells.copilot.chat import room_henry
                    room_henry.on_result(room_id, ev, last_usage, room_henry.OWNER)
                else:                             # the plan calibration's share of it
                    from spine.turn import econ
                    econ.record_spend("hands", list((ev.get("modelUsage") or {}).keys()),
                                      ev.get("usage"), ev.get("total_cost_usd"))
            except Exception:                            # noqa: BLE001
                pass
    watchdog["stop"] = True
    err = ""
    try:
        err = (p.stderr.read() or "")[:400]
    except Exception:                                    # noqa: BLE001
        pass
    rc = p.wait()
    proctable._forget_pid(p.pid)
    with _lock:
        stopped_by = _cancelled.pop(hid, None)
    if stopped_by:
        # the kill is the cause of this end - say so, whatever the stream held
        result = ("CANCELLED by %s after %d steps.%s" % (
            stopped_by, steps, ("\n" + result.strip()) if result.strip() else "")).strip()
        status = "canceled"
        with _lock:
            t = _tasks.get(hid)
            if t:
                t["status"], t["result"], t["updated"] = status, _clip_tile(result), time.time()
        _land(hid, status, result, steps)
        return
    if not result:
        result = ("FAILED - no report (rc=%s) %s" % (rc, err.strip())).strip()
        is_error = True
    head = result.strip().splitlines()[0].upper() if result.strip() else ""
    status = "failed" if (is_error or head.startswith("FAILED")) else "completed"
    with _lock:
        t = _tasks.get(hid)
        if t:
            t["status"], t["result"], t["updated"] = status, _clip_tile(result.strip()), time.time()
    _land(hid, status, result, steps)


def _summary(result):
    """The report's head above the first `---` line: the watch-sized message
    for the owner - chat row and push (owner 2026-09-25: Henry gets the
    detail, the owner the short version). Henry and the tile keep the whole
    report.
    No separator = the old single-block report, cut as before."""
    lines = result.strip().splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            return "\n".join(lines[:i]).strip()
    return result.strip()


TILE_RESULT_MAX = 8000


def _land_room(t, hid, status, result, steps):
    """An owner @henry run in a room ends HERE: the answer is Henry's message in
    that room (rooms.post, the one writer), addressed to whoever asked. Nothing
    reaches the owner's chat transcript, his pending actions or a push of the
    main chat - the room's own message path does the notifying."""
    from cells.copilot.chat import rooms
    from spine.storage import events
    room, asker = t["room"]["id"], t["room"]["to"]
    events.emit("hands", "-", action=status, id=hid, actor=t.get("user"), steps=steps,
                result=result.strip()[:300], room=room)
    if status == "completed":
        text = result.strip() or "(keine Antwort)"
        extra = {"to": asker}
    elif status == "canceled":
        text, extra = "Henry wurde gestoppt, bevor er antworten konnte.", {"to": asker, "error": True}
    else:
        text = "Ich konnte gerade nicht antworten (%s)." % (result.strip().splitlines() or ["?"])[0][:140]
        extra = {"to": asker, "error": True}
        if t.get("resume"):             # the resumed session may be what failed: rebuild from the record
            from cells.copilot.chat import room_henry as _rh
            _rh.drop_session(room, "resumed run failed", _rh.OWNER)
    try:
        rooms.post(room, "Henry", text[:rooms.TEXT_MAX], by_kind="henry", extra=extra)
    except Exception as e:                               # noqa: BLE001
        print("hands: room post failed - %s" % str(e)[:160], flush=True)
    from cells.copilot.chat import room_henry
    room_henry.live_end(room)          # after the post: the answer is in the record first


def _clip_tile(text):
    """The run tile's copy of the result: cut at TILE_RESULT_MAX, and SAY so
    (the tile is what the owner and Henry reread later)."""
    if len(text) <= TILE_RESULT_MAX:
        return text
    return text[:TILE_RESULT_MAX] + "\n[... %d Zeichen gekuerzt]" % (len(text) - TILE_RESULT_MAX)


def _land(hid, status, result, steps):
    """The report reaches the owner (transcript row) AND Henry (next turn)."""
    from cells.copilot.chat import copilot
    from spine.storage import events
    with _lock:
        t = dict(_tasks.get(hid) or {})
    if not t:
        return
    _persist(hid)                      # the tile's final state, before anyone reads it
    user, skey, card, title = t.get("user"), t.get("skey"), t.get("card"), t.get("title")
    if t.get("room"):
        return _land_room(t, hid, status, result, steps)
    # Henry gets the WHOLE report (owner 2026-09-15: the 700-char cut fed him
    # a DM-failure report ending mid-sentence at "The TASK block didn'", so
    # he never saw the passcode/permission lines and invented a still-open
    # browser window); the owner's chat row and push get only the summary.
    full = result.strip()
    if len(full) > 8000:
        full = full[:8000] + "\n[... %d Zeichen gekuerzt]" % (len(full) - 8000)
    short = _summary(result)[:1500]
    events.emit("hands", card or "-", action=status, id=hid, actor=user, steps=steps,
                result=short[:300])
    try:
        with copilot._pending_lock:
            copilot._pending_actions.setdefault(skey, []).append(
                "%s %s (%s): %s\n%s" % ("AGENT" if t.get("kind") == "agent" else "HANDS",
                                        status.upper(), hid, title, full))
    except Exception:                                    # noqa: BLE001
        pass
    word = {"completed": "fertig", "canceled": "gestoppt"}.get(status, "fehlgeschlagen")
    if t.get("kind") == "agent" and not card:
        # AN AGENT RUN REPORTS THROUGH ITS TILE AND THROUGH HENRY (Paseo: the
        # child's result sits in its track, the parent picks it up). The tile
        # already shows status + report (db.chat_runs, persisted above); a
        # second "Hände" box would say it twice. Henry is woken for ONE
        # harness turn - the full report rides in via _pending_actions - so
        # the owner gets the answer to what he asked, not a raw report.
        try:
            copilot._schedule_bg_continue(user, [dict(_desc(t), uid=hid, status=status,
                                                      result=full)])
        except Exception:                                # noqa: BLE001
            pass
        return
    line = "Hände %s: %s\n%s" % (word, title, short)
    try:
        if card:
            from spine.agent import timeline_store
            from cells.engineer.cards import sessions
            tr = sessions.get_track(card) or {}
            if tr.get("run_dir"):
                timeline_store.append(tr["run_dir"], "s:" + uuid.uuid4().hex,
                                      {"kind": "note", "text": line, "byKind": "henry",
                                       "ts": time.strftime("%H:%M:%S"), "ta": time.time()})
        else:
            # Owner ask 2026-09-16: render like the worker-card mirror box
            # (cls "card"/byKind "worker" in chat.tsx toStep), not the plain
            # plumbing "note" line generic action results get - a hands report
            # is a full sub-agent turn, worth reading like one. cls "hands" is
            # its own value (not "card": that one is bound to a real card id
            # and routes replies through routes_copilot._route_to_card, which
            # a bare hands run has no target for) so chat.tsx can box it under
            # sender "Hände" without wiring an inline-reply route to nowhere.
            copilot._append_log(user, [{"cls": "hands", "hands": hid, "text": "%s: %s\n%s" % (word, title, short),
                                        "ts": time.strftime("%H:%M")}])
            # Owner report 2026-09-16: a hands result landed in the transcript
            # but never pinged the phone/watch - he only saw it because Henry
            # happened to quote it back in a later reply. copilot.py's own
            # bot-reply path fires notify.chat_reply right after its
            # _append_log (see the "REVERSE MIRROR" comment there); this is
            # the same push, for the ONE case that path doesn't cover: a
            # hands result landing async, outside any live chat turn.
            def _announce_hands():
                try:
                    from spine.comms import notify
                    notify.chat_reply(line)
                except Exception as _ne:                        # noqa: BLE001
                    print("hands: reply notification failed -", str(_ne)[:200])
            from spine.http import server as _srv
            _srv._bg("hands:notify:" + hid, _announce_hands)
    except Exception:                                    # noqa: BLE001
        pass
