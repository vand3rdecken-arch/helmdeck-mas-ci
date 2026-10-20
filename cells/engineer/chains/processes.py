# -*- coding: utf-8 -*-
"""Processes - longer work as ONE record: the goal is a process, a theme is a
process, and every step is a card. Since 2026-09-30 (owner: "alles zusammen
legen", "Prozesse die Browser oder windows-mcp benoetigen direkt starten -
nur User holen bei letzter Entscheidung oder Login") there is no separate
proposer and no sign-off: Henry files the steps (as cards, or as a template)
and they start. Two kinds of step:

  do     - an agent does it; `desktop: true` makes its card a MACHINE card
           (windows-mcp + browser on the owner's PC), otherwise a repo card
           (browser included). The agent asks the owner only for a login or
           the final go (its ASK protocol) - the step does not wait for him.
  human  - only a person can do it (sign, call, meet); the card tracks it.
The older modes prepare/cowork/teach still read from stored steps and map
to do / do / human.

Dates: a step's `days` lays due dates end-to-end
from today (capped by the process due date when set). `due` is a DEADLINE.
A step may also carry `not_before` (YYYY-MM-DD): the chain will not mark it
ready before that day even when its predecessor is long done. That is what
makes a calendar of independent, date-scheduled items expressible as a
chain at all - without it the whole calendar fires the moment step 0 ends. Store: db.py's
processes table (migrated from the old processes.json flat file - db.init()
imports it once and renames it *.imported, same safeguard as tracks/events).
Steps link to their card (track id) once accepted; the timeline groups cards
by process so one client engagement reads as a swimlane."""
import os, re, threading, time

MODES = ("do", "prepare", "cowork", "teach", "human")   # stored values; see step_mode()
_MODE_MAP = {"do": "do", "prepare": "do", "cowork": "do", "teach": "human", "human": "human"}


def step_mode(mode):
    """The effective kind of a step: 'do' (an agent) or 'human'."""
    return _MODE_MAP.get(mode or "do", "do")
_lock = threading.Lock()

# -- process TEMPLATES: the config half of this module ----------------------
# A process ROW (above/below) is a RUN: request/client/due/status/cost, and
# each step carries RUNTIME fields (done/lane/track/state/ready/
# auto_dispatched/auto_accepted) - arbitrary agent output, not something an
# owner configures. A TEMPLATE is the reusable step SHAPE underneath it
# (title/desc/mode/days) - that IS config (owner decree 2026-09-03: "das ist
# auch config, wie trennen" - a run and its shape were one JSON blob and the
# shape never accumulated anywhere an owner could export it). Kept in this
# module, not a separate one: it owns MODES and the step shape already.
TEMPLATE_STEP_FIELDS = ("title", "desc", "mode", "days", "desktop")


def _clean_template_step(s):
    """The closed step shape - strips every RUNTIME field a live process
    step carries (done/lane/track/state/ready/auto_dispatched/...). Same
    validation any fresh step gets, so a template can never smuggle a
    runtime field back in."""
    out = {"title": str(s.get("title", ""))[:120],
           "desc": str(s.get("desc", ""))[:300],
           "mode": step_mode(s.get("mode")),
           "days": min(5, max(1, int(s.get("days", 1) or 1)))}
    if s.get("desktop"):
        out["desktop"] = True
    return out


MAX_STEPS = 12      # one chain's size bound (a ten-step app chain was silently cut to 8)


def proposed_steps(raw):
    """Raw step dicts (title/desc/mode/days/desktop) -> the shape create() takes:
    the closed template shape plus the not-yet-a-card fields. The ONE
    conversion, shared by the chat verb and template-born processes."""
    raw = [s for s in (raw or []) if isinstance(s, dict) and str(s.get("title", "")).strip()]
    if len(raw) > MAX_STEPS:
        raise ValueError("at most %d steps per process (got %d)" % (MAX_STEPS, len(raw)))
    return [dict(_clean_template_step(s), status="proposed", track=None, due="") for s in raw]


def _slugify(name, existing):
    base = re.sub(r"[^a-z0-9]+", "-", (name or "template").lower()).strip("-") or "template"
    tid, n = base, 2
    while tid in existing:
        tid = "%s-%d" % (base, n)
        n += 1
    return tid


def list_templates():
    from spine.storage import db
    return db.process_template_all()


def get_template(tid):
    from spine.storage import db
    return db.process_template_get(tid)


def save_template(name, description, steps, tid=None, actor="owner"):
    """Create a new template (tid=None, id auto-slugified from the name) or
    UPSERT one at an explicit id (tid given - create-or-overwrite, so a
    harness import can replay a template at its original id whether or not
    that id already exists on the target workspace). Steps are ALWAYS run
    through _clean_template_step - this is the one writer, so a runtime
    field can never enter the process_template table by any path."""
    from spine.storage import db, events
    if not (name or "").strip():
        raise ValueError("name required")
    if len(steps or []) > MAX_STEPS:
        raise ValueError("at most %d steps per template" % MAX_STEPS)
    clean_steps = [_clean_template_step(s) for s in (steps or [])]
    if not clean_steps:
        raise ValueError("at least one step required")
    if not tid:
        tid = _slugify(name, db.process_template_all().keys())
    doc = {"name": name[:120], "description": (description or "")[:500],
           "steps": clean_steps}
    db.process_template_put(tid, doc, actor=actor)
    events.emit("process_template", tid, action="saved", actor=actor)
    doc["id"] = tid
    return doc


def delete_template(tid, actor="owner"):
    from spine.storage import db, events
    ok = db.process_template_delete(tid)
    if ok:
        events.emit("process_template", tid, action="deleted", actor=actor)
    return ok


def template_from_process(pid, name=None, actor="owner"):
    """Strip a process RUN down to its reusable step shape and save it as a
    NEW template - an explicit owner act, never automatic (NO-MONKEY-PATCH:
    a template is ADOPTED by decision, not reconstructed by heuristically
    scanning finished runs at boot)."""
    p = get(pid)
    if not p:
        raise RuntimeError("no such process")
    return save_template(name or p.get("request", "")[:80],
                         p.get("request", ""), p.get("steps") or [],
                         actor=actor)

def _load():
    from spine.storage import db
    return db.processes_all()

def _save(ps):
    from spine.storage import db
    from spine.storage.textfix import demojibake
    # the ONE persistence edge: mangled umlauts never reach (or stay in) the db
    for p in ps:
        p["request"] = demojibake(p.get("request"))
        for st in p.get("steps") or []:
            for k in ("title", "desc"):
                if k in st:
                    st[k] = demojibake(st[k])
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

def create(request_text, client="", due="", actor="owner", steps=None, template_id=None,
           open_ended=False, repo=None):
    """File a process. With `steps` (or a `template_id`) the steps START: each
    becomes a card at once (accept_all into `repo`; with no repo the steps stay
    proposed until someone names the project) and the chain runs them - nobody signs them off first. Without
    steps the process is born EMPTY and running, a folder the work fills
    (attach_card / Henry's cards with "process"); process_drive wakes Henry
    to file the first ones. There is no LLM proposer any more.
    open_ended=True: finishing every step so far does NOT finish the process
    (sync never auto-completes it) - a goal is not reached because the cards
    filed for it so far are done. Measured 2026-09-30: the goal process with
    11 done goal cards flipped to done and told the owner "Prozess fertig"."""
    if template_id and not steps:
        tmpl = get_template(template_id)
        if not tmpl:
            raise RuntimeError("no such template")
        steps = proposed_steps(tmpl["steps"])
    # Millisecond disambiguator (mirrors checkpoints.py): a bare per-SECOND id
    # collides when two processes are filed in the same wall-clock second - the
    # second INSERT then hits `UNIQUE constraint failed: processes.id` and the
    # new process is lost with a 500. The zero-padded ms keeps ids lexically
    # sortable within a second, so `ORDER BY id DESC` stays chronological.
    pid = time.strftime("%Y%m%d-%H%M%S") + "-%03d-proc" % (int(time.time() * 1000) % 1000)
    p = {"id": pid, "request": request_text, "client": client, "due": due,
         "status": "running", "steps": [], "cost": 0.0,
         "created": time.strftime("%Y-%m-%d %H:%M:%S"), "actor": actor,
         "template_id": template_id or None}
    if steps:
        p["steps"] = steps
        p["status"] = "ready"
        _lay_dates(p)
    if open_ended:
        p["open_ended"] = True
    if repo:
        p["repo"] = repo        # the project the work belongs to - later steps land there, never in default_repo
    with _lock:
        ps = _load()
        # the ms suffix still collides for two creates in the same millisecond
        # (measured 2026-09-30: the goal process + a process right after it,
        # IntegrityError on processes.id) - the free id is decided under the
        # lock, against the store itself
        taken = {q["id"] for q in ps}
        while p["id"] in taken:
            head, ms = p["id"].rsplit("-", 2)[0], int(p["id"].rsplit("-", 2)[1])
            p["id"] = "%s-%03d-proc" % (head, (ms + 1) % 1000)
        pid = p["id"]
        ps.insert(0, p); _save(ps)
    from spine.storage import events
    events.emit("process", pid, action="filed", actor=actor)
    if steps:
        # no default_repo fallback: a process that names no project keeps its steps PROPOSED until someone
        # says where the work belongs (projects.project_question) - it never lands in the HelmDeck repo
        if repo:
            p, _made = accept_all(pid, repo, actor=actor)
    return p

# -- process-LEVEL editing (owner report 2026-09-03: "+Schritt war die
# einzige Aktion auf dem Screen ausser Steps annehmen - man kann nicht mal
# den Client/die Faelligkeit aendern oder abbrechen"). Deliberately a
# SEPARATE small surface from update_step: these fields belong to the
# process itself, not to any one step, and are gated the same as any other
# structural card action (cards.admin) rather than left open like the
# per-step editor is.
PROCESS_EDITABLE_FIELDS = ("client", "due", "request")

def update_process(pid, patch, actor="owner"):
    bad = set(patch) - set(PROCESS_EDITABLE_FIELDS)
    if bad:
        raise ValueError("cannot edit: %s (only %s)" %
                         (", ".join(sorted(bad)), ", ".join(PROCESS_EDITABLE_FIELDS)))
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid:
                p.update({k: v for k, v in patch.items() if k in PROCESS_EDITABLE_FIELDS})
                if "due" in patch and p["steps"]:
                    _lay_dates(p)
                _save(ps)
                from spine.storage import events
                events.emit("process", pid, action="edited", actor=actor, patch=patch)
                return p
    raise RuntimeError("no such process")

def _via(via):
    """WHO pressed it, beside the account: the chat runs Henry's actions under
    the owner's ACCOUNT name (billing/dispatch attribution), so the account
    alone reads as "the owner decided". `via` keeps the real hand on the record
    (2026-10-20: Henry deleted three processes, another Henry read the owner's
    name and dropped its own task: "der Owner hat sie bewusst geloescht")."""
    return {"via": via} if via else {}


def cancel_process(pid, actor="owner", via=""):
    """Stops the CHAIN (sync() skips a cancelled process entirely - no more
    auto-dispatch/auto-accept of its remaining steps) without touching any
    card a step already spawned; those keep running/stay on the board like
    any other card - cancelling the process is not an authority to yank
    live work out from under whoever is already on it."""
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid:
                if p.get("status") == "done":
                    raise RuntimeError("already done - nothing to cancel")
                p["status"] = "cancelled"
                _save(ps)
                from spine.storage import events
                events.emit("process", pid, action="cancelled", actor=actor, **_via(via))
                return p
    raise RuntimeError("no such process")

def finish_process(pid, actor="owner", via=""):
    """CLOSE an open-ended (goal) process as DONE. sync() never finishes one by
    its steps - it is a folder - so without this verb a finished goal sat on
    "running" for good (20260929-121246-611-proc: 11/11 steps done, running 6
    days) and the only terminal verbs were cancel (says "abandoned") and delete
    (erases the record). `closed` is the decision; sync() reads it, never
    infers it from the steps. Cards a step spawned are untouched."""
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid:
                if p.get("status") == "cancelled":
                    raise RuntimeError("is cancelled - nothing to finish")
                p["status"] = "done"
                p["closed"] = True
                _save(ps)
                from spine.storage import events
                events.emit("process", pid, action="finished", actor=actor, **_via(via))
                return p
    raise RuntimeError("no such process")

def delete_process(pid, actor="owner", via=""):
    """Removes the process ROW entirely (owner report 2026-09-03: cancel
    only soft-stops the chain, the process still sits in the list forever -
    sometimes you just want it gone). Any card a step already spawned is
    UNTOUCHED - same rule as cancel: this is authority over the process's
    own bookkeeping, never over a card someone is already working."""
    with _lock:
        ps = _load()
        remaining = [p for p in ps if p["id"] != pid]
        if len(remaining) == len(ps):
            raise RuntimeError("no such process")
        _save(remaining)
    from spine.storage import events
    events.emit("process", pid, action="deleted", actor=actor, **_via(via))
    return True

def move_step(pid, idx, direction, actor="owner"):
    """Swap a step with its neighbour (owner report 2026-09-03: no way to
    reorder steps at all). Works regardless of whether either step already
    has a card - the CARDS themselves are untouched, only the process's own
    step LIST order changes, which re-lays every step's due date end-to-end
    from today (same _lay_dates() every other structural change already
    runs) so the schedule reflects the new order."""
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] != pid:
                continue
            steps = p["steps"]
            if not (0 <= idx < len(steps)):
                raise RuntimeError("no such step")
            j = idx - 1 if direction == "up" else idx + 1
            if not (0 <= j < len(steps)):
                raise RuntimeError("already at the %s" % ("top" if direction == "up" else "bottom"))
            steps[idx], steps[j] = steps[j], steps[idx]
            _lay_dates(p)
            _save(ps)
            from spine.storage import events
            events.emit("process", pid, action="step_moved", actor=actor,
                        idx=idx, direction=direction)
            return p
    raise RuntimeError("no such process")

def progress_summary(pid):
    """One line per step - state, and the card's lane once it has one. What
    Henry reads out loud when asked "wo steht Prozess X" (owner report
    2026-09-03: no visibility into what's happening in the steps from
    either the UI or chat)."""
    sync()
    p = get(pid)
    if not p:
        raise RuntimeError("no such process")
    lines = []
    for i, s in enumerate(p["steps"], 1):
        state = s.get("state") or ("done" if s.get("done") else "proposed")
        lane = " (%s)" % s["lane"] if s.get("lane") else ""
        lines.append("%d. %s - %s%s" % (i, s.get("title", ""), state, lane))
    return p, lines

def update_step(pid, idx, patch):
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid and 0 <= idx < len(p["steps"]):
                s = p["steps"][idx]
                for k in ("title", "desc", "mode", "due", "days", "desktop"):
                    if k in patch:
                        s[k] = patch[k]
                if "not_before" in patch:
                    nb = (patch.get("not_before") or "").strip()
                    if nb:
                        try:
                            time.strptime(nb, "%Y-%m-%d")
                        except ValueError:
                            raise RuntimeError("not_before must be YYYY-MM-DD or empty")
                    s["not_before"] = nb
                _save(ps)
                return s
    raise RuntimeError("no such step")

def add_step(pid, title, mode="do", desktop=False, repo=None, actor="owner"):
    """A new step STARTS: it becomes a card at once (accept_step) when the
    process is running and a repo is known - nobody signs a step off."""
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid:
                st = {"title": title[:120], "desc": "", "mode": step_mode(mode),
                      "days": 1, "status": "proposed", "track": None,
                      "due": p.get("due", "")}
                if desktop:
                    st["desktop"] = True
                p["steps"].append(st)
                idx = len(p["steps"]) - 1
                _save(ps)
                break
        else:
            raise RuntimeError("no such process")
    if repo is None:
        repo = p.get("repo") or ""          # the process's own project, never the default_repo preset
    if repo and p.get("status") not in ("cancelled",):
        return accept_step(pid, idx, repo, actor=actor)
    return get(pid)

def remove_step(pid, idx):
    """Drops a step from the process's OWN bookkeeping list - never the
    card itself. Was refused once a step had a track (owner report
    2026-09-03: hit this on their own DONE process, where every step
    already has a card - "cannot remove steps" was really "cannot remove
    ANY step, ever, once the process actually ran"). A card lives in its
    own tracks table, independent of the process row that spawned it - the
    card's own `process`/`process_title` fields survive untouched, it just
    stops being counted in THIS process's pipeline/progress view. Same
    "authority over the process's bookkeeping, never over a live card"
    rule cancel_process/delete_process already follow."""
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid and 0 <= idx < len(p["steps"]):
                p["steps"].pop(idx)
                _save(ps)
                return p
    raise RuntimeError("no such step")

# -- the chain: a process is a LOOP its work travels through -------------
# Step N+1 becomes READY when step N's card reaches done. Ready agent steps
# (do/prepare) auto-dispatch; ready cowork/teach/human steps surface as
# "up next" for the human. This is what links human and automatic work:
# a human finishing their step is the trigger that starts the next agent.

def _not_before_reached(s, today=None):
    """False while a step's `not_before` (YYYY-MM-DD) lies in the future.
    Unset/blank/malformed = no date gate (never silently block a step)."""
    nb = (s.get("not_before") or "").strip()
    if not nb:
        return True
    try:
        time.strptime(nb, "%Y-%m-%d")
    except ValueError:
        return True
    return (today or time.strftime("%Y-%m-%d")) >= nb


def sync():
    """Reconcile step states with the board; auto-advance the chain.
    Behavior is driven by settings POLICY: which modes auto-dispatch, and
    whether a green gate auto-accepts (autonomy) or waits for a human
    (control)."""
    from cells.engineer.cards import sessions
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
            # not_before is a "not earlier than" date; a date-held step is
            # NOT ready, so neither auto-dispatch below nor up_next fires for
            # it. It shows as "waiting" (with `held_until` set) rather than a
            # new state, so no surface has to learn a new word today.
            date_ok = _not_before_reached(s)
            s["ready"] = prev_done and not done and bool(t) and date_ok
            s["held_until"] = (s.get("not_before") or "") if (prev_done and not done and t and not date_ok) else ""
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
                if auto_accept and p.get("status") != "cancelled" and s["ready"] \
                   and sessions.is_delivered(t) \
                   and step_mode(s.get("mode")) in auto_modes and not s.get("auto_accepted"):
                    ok, _problems = _probe_gate(t)
                    if ok:
                        s["auto_accepted"] = True
                        events.emit("process", p["id"], action="auto_accept",
                                    step=s["title"][:80], card=t["id"])
                        threading.Thread(target=_auto_accept, args=(t["id"],),
                                         daemon=True).start()
                # auto-run agent steps the moment the chain reaches them
                if p.get("status") != "cancelled" and s["ready"] \
                   and step_mode(s.get("mode")) in auto_modes \
                   and t.get("lane") == "backlog" and not s.get("auto_dispatched") \
                   and not t.get("example"):
                    s["auto_dispatched"] = True
                    events.emit("process", p["id"], action="auto_advance",
                                step=s["title"][:80], card=t["id"])
                    threading.Thread(target=_auto_dispatch, args=(t["id"],),
                                     daemon=True).start()
            prev_done = done
        if p.get("status") == "cancelled":
            pass   # a cancelled process stays cancelled - never reclassified by sync()
        elif p.get("closed"):
            pass   # finish_process decided it - stays done, never re-opened by sync()
        elif p.get("open_ended"):
            if p.get("status") != "running" and p["steps"]:
                p["status"] = "running"   # a folder, never done by its steps (create())
        elif p["steps"] and all(x.get("done") for x in p["steps"]):
            if p.get("status") != "done":
                p["status"] = "done"
                from spine.storage import events as _e
                _e.emit("process", p["id"], action="completed")
                # the plan's end is NEWS for the owner, not only an event row:
                # a finished process used to end in silence
                try:
                    from cells.copilot.chat import copilot as _cp
                    _cp.say("Prozess fertig: %s (%d/%d Schritte)" % (
                        (p.get("request") or "").split("\n")[0][:80],
                        len(p["steps"]), len(p["steps"])))
                except Exception:                            # noqa: BLE001
                    pass
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
    from cells.engineer.cards import sessions
    try:
        sessions.move_lane(tid, "working", actor="chain")
    except Exception as e:
        print("chain auto-dispatch failed:", tid, e)

def _auto_accept(tid):
    from cells.engineer.cards import sessions
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
    from cells.engineer.cards import sessions
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
    from cells.engineer.cards import sessions
    from spine.storage import events
    s = events.settings()
    floor = (s.get("policy") or {}).get("auto_dispatch_priority") or ""
    if floor not in ("urgent", "high", "medium", "low"):
        return
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    tracks = sessions.list_tracks()
    wip = sum(1 for t in tracks if t.get("lane") == "working")
    headroom = events.wip_limit_of(s) - wip
    todo = sorted((t for t in tracks if t.get("lane") == "backlog"
                   and not t.get("mode") in ("human", "teach")
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
    from cells.engineer.cards import sessions
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
    from cells.copilot.planning import pm
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
    from cells.engineer.cards import sessions
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
    headroom = (events.wip_limit_of(s)
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


# EVENT FAST PATH (owner decree 2026-09-05, "lieber Event plus polling
# backup"): a card landing on done used to wait for the next poller tick -
# 0-20s of waiting on NOTHING, the new state was already on disk - before the
# chain advanced. The lane chokepoint (lanemachine._move_lane, the one writer
# of t["lane"]) calls kick() the moment a move persists; the poller above
# stays untouched as the level-triggered reconciler that heals a missed or
# crashed event. Edge for speed, level for truth - never only one of the two.
#
# Single-flight WITH coalescing, not a bare thread per call: sync() reads and
# writes the whole process store in two separate lock windows, so two
# concurrent syncs can lose each other's updates. A kick that arrives while
# one is running folds into ONE trailing re-run (it reads the tracks fresh,
# so nothing the second event knew is lost), instead of racing the first.
_KICK = {"lock": threading.Lock(), "running": False, "again": False}


def kick():
    with _KICK["lock"]:
        if _KICK["running"]:
            _KICK["again"] = True
            return
        _KICK["running"] = True

    def go():
        while True:
            try:
                sync()
            except Exception as e:
                print("chain kick sync error:", e)
            with _KICK["lock"]:
                if not _KICK["again"]:
                    _KICK["running"] = False
                    return
                _KICK["again"] = False
    threading.Thread(target=go, daemon=True).start()

MODE_DRIVER = {"do": "claude", "prepare": "claude", "cowork": "claude", "teach": None, "human": None}

def accept_step(pid, idx, repo, actor="owner"):
    """Proposed step -> real card. Mode decides driver + task framing; teach
    and human steps become tracked-only cards (no agent session)."""
    from cells.engineer.cards import sessions
    p = get(pid)
    if not p or not (0 <= idx < len(p["steps"])):
        raise RuntimeError("no such step")
    s = p["steps"][idx]
    if s.get("track"):
        return p
    mode = step_mode(s.get("mode"))
    task = s["title"]
    if s.get("desc"):
        task += "\n\n" + s["desc"]
    prio = "high" if idx == 0 else "medium"
    if mode == "human":
        task = "HUMAN STEP (tracked only): " + task
    if mode == "do" and s.get("desktop"):
        # the owner's PC is the workplace: windows-mcp + browser (machine card)
        t = sessions.new_machine_task(os.path.expanduser("~"), task, actor=actor,
                                      priority=prio, dispatch=False)
    else:
        branch = "proc-" + pid.split("-")[0] + "-s%d" % (idx + 1)
        t = sessions.new_track(repo, branch, task, lane="backlog", client=p.get("client", ""),
                               driver=MODE_DRIVER.get(mode) or "claude", actor=actor,
                               priority=prio, due=s.get("due", ""))
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
    # tag the track with its process for the timeline swimlane - through
    # _mutate (one atomic read-modify-write of THIS card), not a load/save of
    # the whole store that could drop a concurrent writer's change.
    _tag_card(t_id, pid, p["request"], idx + 1, mode)
    return get(pid)


def _tag_card(tid, pid, request, step_no, mode):
    """THE one writer of a card's process pointer (process, process_title,
    process_step, mode). The step NUMBER is a field: the board used to recover
    it from the branch name - a data channel smuggled through a git ref, which
    broke the moment branches gained their card-id tail."""
    from spine.storage.trackstore import _mutate

    def _t(tt):
        tt["process"] = pid
        tt["process_title"] = (request or "")[:60]
        tt["process_step"] = step_no
        tt["mode"] = mode
    _mutate(tid, _t)


def attach_card(pid, tid, actor="owner"):
    """Put an EXISTING card into a process as its next step (owner
    2026-09-25: cards Henry filed from chat never got a process - only
    accept_step set one, so "mehrere Deliverables -> PROCESS" in his brief had
    no verb behind it). The step is born accepted with the card as its track;
    sync() then reads its state from the card like any other step."""
    from cells.engineer.cards import sessions
    t = sessions._find(sessions._load(), tid)
    if not t:
        raise RuntimeError("no such card: %s" % tid)
    if t.get("process") == pid:
        return get(pid)
    with _lock:
        ps = _load()
        p = next((q for q in ps if q["id"] == pid), None)
        if p is None:
            raise RuntimeError("no such process: %s" % pid)
        p["steps"].append({"title": (t.get("task") or "")[:120], "desc": "",
                           "mode": t.get("mode") or "do", "days": 1,
                           "status": "accepted", "track": tid,
                           "due": t.get("due") or p.get("due", "")})
        if p.get("status") in ("proposing", "proposed", "done"):
            p["status"] = "running"
        step_no = len(p["steps"])
        request = p["request"]
        _save(ps)
    _tag_card(tid, pid, request, step_no, t.get("mode") or "do")
    return get(pid)


def accept_all(pid, repo, actor="owner"):
    """Every step without a card -> a card (accept_step each). The one body
    behind the chat verb accept_steps and the broker's accept_steps, so
    Henry deciding a proposal and the owner tapping it do the same thing.
    Returns (process, [new card ids])."""
    p = get(pid)
    if not p:
        raise RuntimeError("no such process")
    made = []
    for i in range(len(p["steps"])):
        if not p["steps"][i].get("track"):
            p = accept_step(pid, i, repo, actor=actor)
            made.append(p["steps"][i].get("track"))
    return p, [x for x in made if x]


def detach_card(pid, tid, actor="owner"):
    """The inverse of attach_card: the card stops being a step of `pid`
    (mark_goal off). Bookkeeping only, like remove_step - the card itself
    keeps running; its process pointer is cleared by _tag_card's owner."""
    from spine.storage.trackstore import _mutate
    with _lock:
        ps = _load()
        p = next((q for q in ps if q["id"] == pid), None)
        if p is None:
            raise RuntimeError("no such process: %s" % pid)
        p["steps"] = [s for s in p["steps"] if s.get("track") != tid]
        _save(ps)

    def _t(tt):
        if tt.get("process") == pid:
            for k in ("process", "process_title", "process_step"):
                tt.pop(k, None)
    _mutate(tid, _t)
    from spine.storage import events
    events.emit("process", pid, action="detached", card=tid, actor=actor)
    return get(pid)


def set_next(pid, what, at, actor="henry"):
    """THE NEXT MOVE of a process, as a record: what happens next and WHEN
    (YYYY-MM-DD[ HH:MM]). A conversation that ends in "als Naechstes X" used
    to leave that intent in chat prose only - nothing could wake on it.
    process_drive wakes Henry once `at` is reached. Empty `what` clears it."""
    what = " ".join((what or "").split())[:300]
    at = (at or "").strip()
    if what:
        ok = False
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                time.strptime(at[:16], fmt); ok = True; break
            except ValueError:
                continue
        if not ok:
            raise ValueError("at must be YYYY-MM-DD or YYYY-MM-DD HH:MM, got %r" % at)
    with _lock:
        ps = _load()
        for p in ps:
            if p["id"] == pid:
                if what:
                    p["next"] = {"what": what, "at": at[:16],
                                 "set": time.strftime("%Y-%m-%d %H:%M:%S"), "by": actor}
                else:
                    p.pop("next", None)
                _save(ps)
                from spine.storage import events
                events.emit("process", pid, action="next", actor=actor, what=what, at=at[:16])
                return p
    raise RuntimeError("no such process")
