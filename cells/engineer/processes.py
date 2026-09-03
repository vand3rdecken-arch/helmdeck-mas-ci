# -*- coding: utf-8 -*-
"""Processes - the n8n half. A client request ("get this document approved")
is not one card: an agent PROPOSES a step sequence, the human adjusts it, and
each accepted step becomes a normal board card with an execution mode:

  do      - agent executes it fully (claude / claude-desktop driver)
  prepare - agent drafts, human finishes & sends (email, proposal, sketch)
  cowork  - interactive: dispatched, human steers alongside
  teach   - human records the sequence once on the machine (teach-mode),
            the playbook executes it after
  human   - a person does it; the card only tracks it

Dates: the proposer estimates days per step; due dates are laid end-to-end
from today (capped by the process due date when set). Store: db.py's
processes table (migrated from the old processes.json flat file - db.init()
imports it once and renames it *.imported, same safeguard as tracks/events).
Steps link to their card (track id) once accepted; the timeline groups cards
by process so one client engagement reads as a swimlane."""
import json, os, re, shutil, subprocess, threading, time

from daemon.paths import DAEMON_ROOT as ROOT
from spine.agent.agentcli import CLAUDE  # single source - see its module docstring
MODES = ("do", "prepare", "cowork", "teach", "human")
_lock = threading.Lock()

def _load():
    from spine.storage import db
    return db.processes_all()

def _save(ps):
    from spine.storage import db
    db.processes_replace(ps)

def list_processes(client=None):
    ps = _load()
    if client:
        ps = [p for p in ps if p.get("client") == client]
    return ps

def get(pid):
    for p in _load():
        if p["id"] == pid:
            return p
    return None

PROPOSE_PROMPT = """You are a process designer for an agent-execution board.
A client request follows. Break it into 3-8 concrete, orderable steps.

For each step decide the best execution mode:
  do      = an AI agent can complete it alone (code, research, documents, browser/desktop work)
  prepare = an AI agent should DRAFT it but a human must review/send it (emails to people, proposals, designs)
  cowork  = human and agent should work it together interactively
  teach   = a repetitive machine sequence a human should demonstrate once so it becomes a playbook
  human   = only a human can do it (signatures, phone calls, physical actions, approvals by named people)

Reply with ONLY a JSON array, no prose:
[{"title": "...", "desc": "one sentence of what done looks like", "mode": "do|prepare|cowork|teach|human", "days": <estimated working days, 1-5>}]

REQUEST:
%s"""

def _propose_steps(request_text):
    from spine.agent import drivers
    # drivers._cmd_line, not ["cmd","/c",...] - the cmd.exe route mangles quoted
    # args on a .cmd shim (see drivers._real_claude_exe).
    r = subprocess.run(drivers._cmd_line([CLAUDE, "-p", "--output-format", "json",
                                          "--permission-mode", "plan"]),
                       input=PROPOSE_PROMPT % request_text,
                       capture_output=True, text=True, timeout=300)
    d = json.loads(r.stdout)
    txt = d.get("result", "")
    m = re.search(r"\[.*\]", txt, re.S)
    steps = json.loads(m.group(0)) if m else []
    out = []
    for s in steps[:8]:
        out.append({"title": str(s.get("title", ""))[:120],
                    "desc": str(s.get("desc", ""))[:300],
                    "mode": s.get("mode") if s.get("mode") in MODES else "do",
                    "days": min(5, max(1, int(s.get("days", 1)))),
                    "status": "proposed", "track": None, "due": ""})
    return out, d.get("total_cost_usd")

def _lay_dates(p):
    """End-to-end schedule from today; compress into the process due if set."""
    total = sum(s.get("days", 1) for s in p["steps"]) or 1
    start = time.time()
    horizon = total * 86400
    if p.get("due"):
        try:
            end = time.mktime(time.strptime(p["due"], "%Y-%m-%d")) + 86399
            horizon = max(86400, end - start)
        except ValueError:
            pass
    acc = 0
    for s in p["steps"]:
        acc += s.get("days", 1)
        s["due"] = time.strftime("%Y-%m-%d", time.localtime(start + horizon * acc / total))

def create(request_text, client="", due="", actor="owner", steps=None):
    """File a process. With `steps` (a pre-built list, e.g. from the PM's vetted plan
    milestones) we ADOPT them directly and skip the generic proposer - the steps are
    already intelligent + gated. Without steps, the background proposer runs as before."""
    # Millisecond disambiguator (mirrors checkpoints.py): a bare per-SECOND id
    # collides when two processes are filed in the same wall-clock second - the
    # second INSERT then hits `UNIQUE constraint failed: processes.id` and the
    # new process is lost with a 500. The zero-padded ms keeps ids lexically
    # sortable within a second, so `ORDER BY id DESC` stays chronological.
    pid = time.strftime("%Y%m%d-%H%M%S") + "-%03d-proc" % (int(time.time() * 1000) % 1000)
    p = {"id": pid, "request": request_text, "client": client, "due": due,
         "status": "proposing", "steps": [], "cost": 0.0,
         "created": time.strftime("%Y-%m-%d %H:%M:%S"), "actor": actor}
    if steps:
        p["steps"] = steps
        p["status"] = "ready"
        _lay_dates(p)
    with _lock:
        ps = _load(); ps.insert(0, p); _save(ps)
    from spine.storage import events
    events.emit("process", pid, action="filed", actor=actor)
    if steps:
        return p                       # adopted the plan's steps; no proposer needed
    def go():
        try:
            steps, cost = _propose_steps(request_text)
            err = "" if steps else "proposer returned no steps - add them manually"
        except Exception as e:
            steps, cost, err = [], 0, str(e)[:200]
        with _lock:
            ps = _load()
            for q in ps:
                if q["id"] == pid:
                    q["steps"] = steps
                    q["cost"] = cost or 0.0
                    q["status"] = "ready" if steps else "failed"
                    q["error"] = err
                    _lay_dates(q)
            _save(ps)
    threading.Thread(target=go, daemon=True).start()
    return p

def update_step(pid, idx, patch):
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid and 0 <= idx < len(p["steps"]):
                s = p["steps"][idx]
                for k in ("title", "desc", "mode", "due", "days"):
                    if k in patch:
                        s[k] = patch[k]
                _save(ps)
                return s
    raise RuntimeError("no such step")

def add_step(pid, title, mode="do"):
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid:
                p["steps"].append({"title": title[:120], "desc": "", "mode": mode,
                                   "days": 1, "status": "proposed", "track": None,
                                   "due": p.get("due", "")})
                _save(ps)
                return p
    raise RuntimeError("no such process")

def remove_step(pid, idx):
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid and 0 <= idx < len(p["steps"]):
                if p["steps"][idx].get("track"):
                    raise RuntimeError("step already has a card")
                p["steps"].pop(idx)
                _save(ps)
                return p
    raise RuntimeError("no such step")

# -- the chain: a process is a LOOP its work travels through -------------
# Step N+1 becomes READY when step N's card reaches done. Ready agent steps
# (do/prepare) auto-dispatch; ready cowork/teach/human steps surface as
# "up next" for the human. This is what links human and automatic work:
# a human finishing their step is the trigger that starts the next agent.

def sync():
    """Reconcile step states with the board; auto-advance the chain.
    Behavior is driven by settings POLICY: which modes auto-dispatch, and
    whether a green gate auto-accepts (autonomy) or waits for a human
    (control)."""
    from cells.engineer import sessions
    from spine.storage import events
    from spine.ops import projects
    # PER REPO, not hoisted out of the loop any more. These two knobs are set by
    # a repo's TEMPLATE (a document repo may prepare a draft on its own; a code
    # repo may not), and reading them once up here was what forced them to be
    # workspace-global - the value had to be the same for every card in the
    # sweep. Resolved at the decision point instead, where the card (and so its
    # repo) is in hand. projects.policy_for falls back to the workspace value, so
    # a repo with no template behaves exactly as before.
    with _lock:
        ps = _load()
    tracks = sessions._load()
    tmap = {t["id"]: t for t in tracks}
    tracks_changed = False
    for p in ps:
        prev_done = True
        for s in p["steps"]:
            t = tmap.get(s.get("track"))
            done = bool(t and t.get("lane") == "done")
            s["done"] = done
            s["ready"] = prev_done and not done and bool(t)
            s["lane"] = t.get("lane") if t else None
            s["state"] = ("done" if done else
                          "working" if t and t.get("lane") in ("working", "review") else
                          "ready" if s["ready"] else
                          "waiting" if t else "proposed")
            if t:
                _repo = t.get("repo") or ""
                auto_modes = projects.policy_for(_repo, "auto_dispatch_modes",
                                                 ["do", "prepare"])
                auto_accept = bool(projects.policy_for(_repo, "auto_accept_green",
                                                       False))
                want = s["ready"] and t.get("lane") == "backlog"
                if t.get("up_next") != bool(want):
                    t["up_next"] = bool(want)
                    tracks_changed = True
                # policy: green gate on a finished chain step -> auto-accept.
                # is_delivered, not status alone: a card parked on an unanswered
                # question or a running background task is NOT finished work, and
                # accepting it would merge the branch and discard the question.
                if auto_accept and s["ready"] and sessions.is_delivered(t) \
                   and s.get("mode") in auto_modes and not s.get("auto_accepted"):
                    ok, _problems = _probe_gate(t)
                    if ok:
                        s["auto_accepted"] = True
                        events.emit("process", p["id"], action="auto_accept",
                                    step=s["title"][:80], card=t["id"])
                        threading.Thread(target=_auto_accept, args=(t["id"],),
                                         daemon=True).start()
                # auto-run agent steps the moment the chain reaches them
                if s["ready"] and s.get("mode") in auto_modes \
                   and t.get("lane") == "backlog" and not s.get("auto_dispatched") \
                   and not t.get("example"):
                    s["auto_dispatched"] = True
                    events.emit("process", p["id"], action="auto_advance",
                                step=s["title"][:80], card=t["id"])
                    threading.Thread(target=_auto_dispatch, args=(t["id"],),
                                     daemon=True).start()
            prev_done = done
        if p["steps"] and all(x.get("done") for x in p["steps"]):
            if p.get("status") != "done":
                p["status"] = "done"
                from spine.storage import events as _e
                _e.emit("process", p["id"], action="completed")
        elif p.get("status") == "done":
            p["status"] = "running"
    with _lock:
        _save(ps)
    if tracks_changed:
        sessions._save(tracks)
    return ps

def clear_step_stamps(tid):
    """A card re-queued to Backlog must be able to run its chain step AGAIN.

    The step's one-shot stamps live HERE (processes.json, keyed by the step's
    track), so sessions.move_lane structurally cannot reach them the way it
    clears the card-level ones - the card came back clean while the step still
    said "already dispatched", and the chain silently never restarted it.

    Deliberately driven by the board MOVE, not by sync() noticing the card in
    backlog: a FAILED dispatch also leaves the card in backlog
    (_dispatch_failed marks it bounced without moving the lane), so clearing on
    "is in backlog" would re-dispatch a broken step on every 20s poll - the
    same trap _priority_dispatch just had. move_lane fires once, per move."""
    from spine.registry import cells
    # "engineer", NOT "process" - merged cell id (2026-09-03); enabled_id
    # fails OPEN on unknown ids, so the stale name would disable this guard.
    if not cells.enabled_id("engineer"):
        return
    with _lock:
        ps = _load()
        hit = False
        for p in ps:
            for s in p.get("steps", []):
                if s.get("track") != tid:
                    continue
                for k in ("auto_dispatched", "auto_accepted"):
                    if s.pop(k, None) is not None:
                        hit = True
        if hit:
            _save(ps)
    return hit


def _auto_dispatch(tid):
    from cells.engineer import sessions
    try:
        sessions.move_lane(tid, "working", actor="chain")
    except Exception as e:
        print("chain auto-dispatch failed:", tid, e)

def _auto_accept(tid):
    from cells.engineer import sessions
    try:
        sessions.move_lane(tid, "done", actor="policy")
    except Exception as e:
        print("policy auto-accept failed:", tid, e)


def _probe_gate(t):
    """The auto-accept PRE-CHECK, kept aligned with what move_lane('done') will
    actually do: sync the card's base in first (lanemachine._sync_base), THEN
    gate. Probing the stale tree re-opened debt gate-base-lag for exactly the
    autonomous paths: a delivered card whose base drifted probed red on code it
    never touched and was never auto-accepted - forever, silently, on every
    poll tick - even though the real submit would sync and gate it green.
    Same entry as move_lane uses (one owner for the worktree mutation, one
    definition of 'the gate'), reached via the sessions module so the tests'
    _gate stubs keep working. A sync conflict is NOT green: the markers stay
    in the worktree as the resolution medium (dispatch_conflict_resolution
    reuses them), and an auto-accept must never land a half-merge."""
    from cells.engineer import sessions
    if sessions._sync_base(t).startswith("conflict"):
        return False, ["base-sync conflict - resolve the markers first"]
    return sessions._gate(t)

def _priority_dispatch():
    """Policy: backlog cards at/above auto_dispatch_priority start themselves
    while WIP headroom exists.

    ONE dispatch per card, stamped like the autopilot's: this runs on the chain
    poller (every 20s) and a FAILED dispatch leaves the card in backlog
    (_dispatch_failed marks status=bounced but never moves the lane), so an
    unguarded pass re-dispatched the same broken card three times a minute
    forever - flooding the append-only log and re-running git each time. It
    also closed a race: the lane only flips to working partway into _start,
    so a slow worktree checkout could be dispatched twice and the duplicate's
    failure would mark a perfectly healthy card bounced. Re-queueing to Backlog
    clears the stamp (sessions.move_lane) - that is the retry handle."""
    from cells.engineer import sessions
    from spine.storage import events
    s = events.settings()
    floor = (s.get("policy") or {}).get("auto_dispatch_priority") or ""
    if floor not in ("urgent", "high", "medium", "low"):
        return
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    tracks = sessions.list_tracks()
    wip = sum(1 for t in tracks if t.get("lane") == "working")
    headroom = s["capacity"]["wip_limit"] - wip
    todo = sorted((t for t in tracks if t.get("lane") == "backlog"
                   and not t.get("mode") in ("human", "teach", "cowork")
                   and not t.get("priority_dispatched")
                   and not t.get("example")
                   and order.get(t.get("priority", "medium"), 2) <= order[floor]),
                  key=lambda t: (order.get(t.get("priority", "medium"), 2), t.get("due") or "9999"))
    for t in todo[:max(0, headroom)]:
        _stamp(t["id"], priority_dispatched=True)
        events.emit("process", "-", action="priority_dispatch", card=t["id"])
        threading.Thread(target=_auto_dispatch, args=(t["id"],), daemon=True).start()

AUTOPILOT_RETRY_SECONDS = 600  # min gap between autopilot gate re-checks on one card


def _stamp(tid, **fields):
    """Persist autopilot bookkeeping fields on a card (fresh load, no clobber -
    through sessions._mutate so a whole-dict save can never resurrect a stale
    status snapshot)."""
    from cells.engineer import sessions
    return sessions._mutate(tid, lambda t: t.update(fields))


def _auto_resolve(t):
    """Bounced autopilot card: run the PM's resilience ladder on it NOW
    (pm.resolve_card_now) instead of waiting for the PM's idle window - the
    ladder classifies the bounce (dispatch/dirty/conflict/gate), delegates the
    matching fix, and RE-SUBMITS so the gate decides. One ladder, one attempt
    budget: the autopilot only supplies the always-on trigger. When the ladder
    is exhausted, alert ONCE - with the ladder's own unblock proposal, so the
    escalation is a decision you can act on, never a bare 'it is stuck'."""
    from spine.storage import events
    from cells.copilot import pm
    tid = t["id"]
    state = pm.resolve_card_now(tid)
    if state != "exhausted" or t.get("autopilot_alerted"):
        return
    _stamp(tid, autopilot_alerted=True)
    pm.mark_notified(tid)      # exactly ONE ping: don't let the PM push it again
    events.emit("process", "-", action="autopilot_escalate", card=tid)
    try:
        from spine.comms import notify
        from spine.registry import i18n as _i18n  # `t` is the track dict here, so alias the translator
        notify.push_fcm(_i18n.t("push.autopilotStuck"),
                        _i18n.t("push.autopilotStuckBody",
                                task=(t.get("task") or "")[:50],
                                proposal=pm._unblock_proposal(t)), tid)
    except Exception:
        pass


def _autopilot():
    """Per-card autopilot: a card flagged autopilot=true keeps MOVING on its
    own, so launch cards never sit for weeks waiting on a human:
      backlog  -> dispatch itself (WIP headroom respected)
      bounced  -> run the PM's resilience ladder immediately, ignoring the PM's
                  presence/idle window; escalate once when it's exhausted
      needs_you + policy.auto_accept_green -> accept on a re-verified green gate

    What autopilot does NOT do: merge or deploy on its own authority. The
    harness rule stands - nothing merges itself unless the OWNER turned on
    policy.auto_accept_green (default off), and the gate is never bypassed:
    red still bounces, green is still required. Autopilot removes the WAITING,
    not the checks and not your accept."""
    from cells.engineer import sessions
    from spine.storage import events
    tracks = sessions.list_tracks()
    auto = [t for t in tracks if t.get("autopilot") and not t.get("archived") and not t.get("example")]
    if not auto:
        return
    from spine.ops import projects
    s = events.settings()
    # wip_limit stays global on purpose: it is a property of this MACHINE (how
    # much load the box takes), not of a repo type - the same call the templates
    # make (spine/registry/templates.py docstring). auto_accept_green is the
    # opposite: whose work merges itself is a property of the REPO, so it moves
    # inside the loop where the card's repo is known.
    headroom = (s["capacity"]["wip_limit"]
                - sum(1 for t in tracks if t.get("lane") == "working"))
    for t in auto:
        auto_accept = bool(projects.policy_for(t.get("repo") or "",
                                               "auto_accept_green", False))
        if t.get("status") == "bounced":
            _auto_resolve(t)
        elif sessions.is_delivered(t) and auto_accept:
            # delivered; gate was green at submit - re-check before accepting
            # (backed off so a red result doesn't re-run the gate every tick)
            if t.get("autopilot_accepted") \
               or time.time() - (t.get("autopilot_ts") or 0) < AUTOPILOT_RETRY_SECONDS:
                continue
            _stamp(t["id"], autopilot_ts=time.time())
            ok, _problems = _probe_gate(t)
            if ok:
                _stamp(t["id"], autopilot_accepted=True)
                events.emit("process", "-", action="autopilot_accept", card=t["id"])
                threading.Thread(target=_auto_accept, args=(t["id"],),
                                 daemon=True).start()
        elif t.get("lane") == "backlog" and headroom > 0 \
                and not t.get("autopilot_dispatched"):
            headroom -= 1
            _stamp(t["id"], autopilot_dispatched=True)
            events.emit("process", "-", action="autopilot_dispatch", card=t["id"])
            threading.Thread(target=_auto_dispatch, args=(t["id"],),
                             daemon=True).start()


def start_chain_poller(interval=20):
    def loop():
        while True:
            try:
                sync()
                _priority_dispatch()
                _autopilot()
            except Exception as e:
                print("chain sync error:", e)
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True).start()

MODE_DRIVER = {"do": "claude", "prepare": "claude", "cowork": "claude", "teach": None, "human": None}

def accept_step(pid, idx, repo, actor="owner"):
    """Proposed step -> real card. Mode decides driver + task framing; teach
    and human steps become tracked-only cards (no agent session)."""
    from cells.engineer import sessions
    p = get(pid)
    if not p or not (0 <= idx < len(p["steps"])):
        raise RuntimeError("no such step")
    s = p["steps"][idx]
    if s.get("track"):
        return p
    mode = s.get("mode", "do")
    task = s["title"]
    if s.get("desc"):
        task += "\n\n" + s["desc"]
    if mode == "prepare":
        task = "PREPARE (draft only - a human reviews and sends/finishes): " + task
    elif mode == "cowork":
        task = "COWORK (start, then wait for the human's steers): " + task
    elif mode == "teach":
        task = "TEACH: human demonstrates this once (swarm.py teach), playbook runs it after: " + task
    elif mode == "human":
        task = "HUMAN STEP (tracked only): " + task
    branch = "proc-" + pid.split("-")[0] + "-s%d" % (idx + 1)
    t = sessions.new_track(repo, branch, task, lane="backlog", client=p.get("client", ""),
                           driver=MODE_DRIVER.get(mode) or "claude", actor=actor,
                           priority="high" if idx == 0 else "medium", due=s.get("due", ""))
    t_id = t["id"]
    # human/teach steps never auto-dispatch; agent modes wait in backlog for the drag
    with _lock:
        ps = _load()
        for q in ps:
            if q["id"] == pid:
                q["steps"][idx]["status"] = "accepted"
                q["steps"][idx]["track"] = t_id
                if all(x.get("track") for x in q["steps"]):
                    q["status"] = "running"
        _save(ps)
    # tag the track with its process for the timeline swimlane
    tracks = sessions._load()
    tt = sessions._find(tracks, t_id)
    if tt:
        tt["process"] = pid
        tt["process_title"] = p["request"][:60]
        # The step NUMBER as a field. The board used to recover it by matching
        # /-s(\d+)$/ against the branch name - a data channel smuggled through a
        # git ref, which broke the moment branches gained their card-id tail
        # (trackstore._card_branch). Store the fact instead of encoding it.
        tt["process_step"] = idx + 1
        tt["mode"] = mode
        sessions._save(tracks)
    return get(pid)
