# -*- coding: utf-8 -*-
"""The turn-runner SERVICE - extracted from sessions.py. _turn spawns ONE
turn through the track's driver (surfaces/desktop/direct lock coordination via
locks.py); _settle_reply_compute/_apply interpret a finished turn's reply
(question repair, background-wait detection); _finish_turn is the ONE
atomic end-of-turn commit (session rotation + economics + typed lifecycle
event), the shared choke point for dispatch/machine-dispatch/steer.

Depends on the already-extracted services (gitutil, trackstore, locks,
econ, blockers, devport) directly - not back through sessions - so this is
a real service layer, not a borrower. sessions.py re-imports the public
names; ZOMBIE_NOTE/RESUME_NOTE are also used elsewhere in sessions.py and
stay resolvable via that re-import.
"""
import os
import time

from spine.git.gitutil import _checkpoint
from spine.storage.trackstore import _mutate, _load, _find
from spine.git.locks import _desktop_lock, _direct_lock_for, _lock_for, _uses_desktop_control
from spine.turn.econ import _record_econ, _record_turn, _log_turn_end
from spine.turn.blockers import blocker
from cells.engineer.cards.devport import _alloc_dev_port

ZOMBIE_NOTE = "daemon restarted mid-turn - resend the last instruction"
RESUME_NOTE = "Turn unterbrochen - erneut steuern setzt den Kontext fort"
# The gating twin of ZOMBIE_NOTE: a card cut at status='gating' lost a gate/merge
# pipeline, not a worker turn - "resend the last instruction" is the wrong verb
# (there was no instruction in flight) and sends the owner steering a worker that
# was never running. Nothing landed (merge + deploy only run AFTER a green gate),
# so the honest recovery is to re-submit the card.
GATE_CUT_NOTE = ("gate/merge pipeline died mid-run (daemon restart) - nothing was "
                 "landed; move the card to Review again to re-run the gate")


def _routing_policy(t):
    """This CARD's effective model-routing policy - the engineer cell's own
    reading of spine/registry/behavior.py's routing.* rules (owner decree
    2026-09-04: which model when is engineer/Henry policy per project, not a
    spine constant). Same shape as copilot.py::henry_pmode: resolve the
    project overlay for each row, default to turnopts' own DEFAULT_ROUTING_
    POLICY - never raise, a broken row must never block a turn from spawning.

    project = for_card(t): the card's own repo, fixed at dispatch - the same
    resolution turnopts_project already uses for pm.py's other project reads."""
    from spine.agent import turnopts
    out = dict(turnopts.DEFAULT_ROUTING_POLICY)
    try:
        from spine.storage import projectconfig
        project = projectconfig.for_card(t)
        for key, path in (("auto_model", "rule.routing.auto_model.all"),
                          ("escalate_value", "rule.routing.escalate_value.all"),
                          ("escalate_urgent", "rule.routing.escalate_urgent.all")):
            got = projectconfig.resolve(path, project)
            if got["value"] is not None:
                out[key] = got["value"]
    except Exception:                                          # noqa: BLE001
        pass                  # a broken row must never block a turn from spawning
    return out


def _turn(t, prompt, model=None, perm=None, idle_timeout=None, by=None):
    """THE choke point every turn passes through - and therefore the ONE owner
    of the turn-intent registration (drivers.turn_intent).

    A turn is alive from the moment it is decided, not from the moment it
    spawns: the body below can block for up to 960s on the desktop/direct lock
    before drivers.run() creates a session. Registering here - around the lock
    waits, not inside them - is what makes drivers.turn_inflight() true for that
    whole window, so no reconciler can mistake a QUEUED turn for a dead one and
    bounce/settle the card while it is about to run (measured 2026-09-02; see
    drivers._pending for the full trace). Event-time fold, exactly one owner,
    nothing stored on the card."""
    from spine.agent import drivers as _d
    with _d.turn_intent(t["id"]) as intent:
        return _turn_inner(t, prompt, intent, model=model, perm=perm,
                           idle_timeout=idle_timeout, by=by)


def _turn_inner(t, prompt, intent, model=None, perm=None, idle_timeout=None, by=None):
    """One turn through the track's DRIVER (drivers.py) - Claude Code by default,
    but any agent runtime configured in settings. Handles the flight-recorder
    hook: a driver with record:true gets its whole turn screen-captured into the
    track's run_dir (screen.mp4 + live.jpg glance feed). Per-turn `model` and
    `perm` overrides (from the chat composer's model + mode controls) win over
    the driver's configured values. `idle_timeout` overrides the driver's
    900s-of-silence watchdog for callers who know their own turn is bounded
    (e.g. _maybe_compact - see there for why). `by` is the human actor's name
    (steer's caller) - threaded down to the driver so the prompt it folds into
    the timeline carries WHO sent it, not just that a human did."""
    from spine.agent import drivers
    from spine.storage import events
    # Pre-P4 cards were dispatched without a reserved dev port - claim one on
    # their next turn so HELMDECK_DEV_PORT is always there (sticky afterwards).
    if not t.get("machine") and t.get("worktree") and not t.get("dev_port"):
        port = _alloc_dev_port(exclude_tid=t["id"])
        if port:
            def _claim(tt):
                tt.setdefault("dev_port", port)
            t = _mutate(t["id"], _claim) or t
    name = t.get("driver") or "claude"
    cfg = events.settings().get("drivers", {}).get(name) or {"type": "claude"}
    model = model or t.get("model")      # card's chosen model (from New Request) unless overridden
    # NO turn may fall through to the CLI's global default. Only steer()'s
    # composer path used to resolve "auto"; every harness-initiated turn
    # (dispatch, auto-continue after a background task, the ask-repair call)
    # passed no model, so the spawned CLI ran on whatever the OWNER'S OWN
    # interactive `/model` was last set to - measured live 2026-08-14: cards
    # believed to be on Auto (sonnet-tier) silently billed fable-5 turns
    # because the owner's terminal happened to be set there. Auto is resolved
    # HERE, at the one choke point every turn passes through, from the card's
    # own facts - deliberate routing always, global leak never. An explicit
    # model (composer pick or the card's stored choice) still wins untouched.
    if not model or model == "auto":
        from spine.agent import turnopts
        model, _ = turnopts.resolve_model("auto", prompt, signals={
            "value": t.get("value"), "priority": t.get("priority"),
            "turns": t.get("turns"), "failed": bool(t.get("gate_failed")),
            "fails": events.consecutive_gate_fails(t["id"]),
            "ctx_tokens": t.get("ctx_tokens")}, policy=_routing_policy(t))
    if model:
        cfg = {**cfg, "model": model}
    if perm:
        cfg = {**cfg, "perm": perm}
    if idle_timeout:
        cfg = {**cfg, "idle_timeout": idle_timeout}
    rec = None
    if cfg.get("record"):
        try:
            from spine.media import wincap
            rec = wincap.start(t["run_dir"])
        except Exception as e:
            print("recorder failed to start:", e)
    desktop = _uses_desktop_control(cfg)
    if desktop and not _desktop_lock.acquire(blocking=False):
        # Contended: QUEUE instead of failing fast. Dispatch/steer already run
        # on background threads and threading.Lock has its own wait queue, so a
        # bounded blocking acquire turns "second desktop card bounces and sits
        # until the owner notices" into "it waits its turn and runs" - with no
        # new state that could drift (the lock's queue IS the waiter list).
        # Bounded because the holder can be wedged: the wait must outlive one
        # healthy turn AND the wedge ceilings that end a sick one (5-min
        # MCP_TOOL_TIMEOUT, 900s silence watchdog) - past that, bounce with the
        # visible reason as before (_dispatch_failed / steer's error path).
        try:
            wait_s = float(events.settings().get("desktop_lock_wait_s") or 0) or 960.0
        except Exception:
            wait_s = 960.0
        try:
            from spine.ops.actionlog import ActionLog
            ActionLog(t["run_dir"]).log(
                "note", "Desktop control busy (another card is driving the "
                        "screen) - queued, waiting up to %ds for it to free." % wait_s)
        except Exception:
            pass
        events.emit("desktop_wait", t["id"], wait_s=wait_s)
        if not _desktop_lock.acquire(timeout=wait_s):
            raise RuntimeError(
                "Desktop control (windows-mcp) is already in use by another card - "
                "only one card may drive the mouse/keyboard/screen at a time. "
                "Waited %ds for it to free, then gave up - retry when the other "
                "card's turn ends." % wait_s)
    # DIRECT cards share the repo's LIVE tree - one turn per tree at a time,
    # same bounded-queue semantics (and the same wait knob) as the desktop lock.
    dlock = _direct_lock_for(t.get("worktree") or t.get("repo")) if t.get("direct") else None
    if dlock and not dlock.acquire(blocking=False):
        try:
            wait_s = float(events.settings().get("desktop_lock_wait_s") or 0) or 960.0
        except Exception:
            wait_s = 960.0
        try:
            from spine.ops.actionlog import ActionLog
            ActionLog(t["run_dir"]).log(
                "note", "Working tree busy (another direct card is editing it) - "
                        "queued, waiting up to %ds." % wait_s)
        except Exception:
            pass
        events.emit("direct_wait", t["id"], wait_s=wait_s)
        if not dlock.acquire(timeout=wait_s):
            if desktop:
                _desktop_lock.release()   # never leak the cursor lock on this bounce
            raise RuntimeError(
                "Direct build: another card is editing the same working tree. "
                "Waited %ds for it to finish, then gave up - retry when its "
                "turn ends." % wait_s)
    try:
        with _lock_for(t["id"]):   # one turn per card at a time - pays turn-locks debt
            # Stop pressed while we sat in the queue: there was no session to
            # kill, so drivers.cancel armed the intent instead. Honour it HERE,
            # with the locks held and about to be released - running now would
            # spend money on a turn the owner already stopped (and the card is
            # already showing the stopped state).
            if intent is not None and intent.cancelled:
                raise RuntimeError(
                    "Turn wurde gestoppt, waehrend er auf einen belegten Lock "
                    "(Desktop-Steuerung / Live-Tree) wartete - er wurde nicht "
                    "ausgefuehrt. Einfach neu steuern.")
            return drivers.run(cfg, t, prompt, by=by)
    finally:
        if dlock:
            dlock.release()
        if desktop:
            _desktop_lock.release()
        if rec:
            from spine.media import wincap
            wincap.stop(rec)
            from spine.ops.actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "screen recording captured for this turn")


def _repair_question(t, log):
    """Convert a turn that parked on a PROSE question into a typed one.

    Measured against the real CLI: teaching the protocol in the system prompt
    alone is not enough - a worker that needs a decision reliably writes prose
    and stops (that is exactly the trap Phase 2.4 exists to close). Asking for
    the block as the IMMEDIATE instruction does work, so when a turn parks on
    what looks like a question the harness spends ONE short turn on the same
    session to have it restated in protocol form.

    Bounded by construction: called only from _settle_reply, never recursive
    (its own result is parsed, not re-repaired), and the worker can decline with
    NOQUESTION. Switch it off with policy.ask_repair=false."""
    from spine.ops import ask
    from spine.storage import events
    try:
        _sid, out, meta = _turn(t, ask.REPAIR)
    except Exception as e:
        # a repair is a convenience, never a reason to fail a finished turn
        log.log("note", "Frage-Reparatur fehlgeschlagen: %s" % str(e)[:200])
        return None
    # measured economics: this turn is billed too. Through _mutate (it runs a
    # whole model turn, so it is only ever called OUTSIDE the mutation lock).
    _mutate(t["id"], lambda tt: (_record_econ(tt, meta), None)[1])
    if ask.NO_QUESTION in (out or "")[:200]:
        return None                # worker says it was not actually asking
    question, _ = ask.parse(out or "")
    if question:
        events.emit("askrepair", t["id"], ok=True)
    return question



def _ask_repair_on(t):
    """policy.ask_repair (default on). Off => a prose question parks the card
    exactly as it did before Phase 2.4 - no repair turn, no extra cost."""
    from spine.storage import events
    pol = events.settings().get("policy") or {}
    return bool(pol.get("ask_repair", True))



def is_delivered(t):
    """True when a parked card is really HANDING WORK BACK, as opposed to
    sitting on `needs_you` for some other reason.

    Every automation that treats "status == needs_you" as "the worker is done"
    needs this. Since Phase 2 a card can be parked because it is ASKING the
    owner a question, or because it is waiting on a background task it started -
    neither is finished work. Auto-accepting those would merge an unfinished
    branch and throw the question away, and announcing them as "delivered" is
    simply wrong. (Both cases existed before; they were just indistinguishable.)"""
    t = t or {}
    return (t.get("status") == "needs_you"
            and not t.get("question")
            and t.get("waiting_on") != "background")


def _settle_reply_compute(t, result, log):
    """The SLOW half of interpreting a finished turn's reply - runs OUTSIDE the
    mutation lock (the question-repair is a whole model turn, the background
    probe reads the transcript from disk). Pure compute: touches nothing on the
    stored track. Returns (question, cleaned, bg)."""
    from spine.ops import ask
    question, cleaned = ask.parse(result or "")
    if not question and _ask_repair_on(t) and ask.looks_like_question(cleaned):
        question = _repair_question(t, log)
    bg = None
    if not question:
        # A turn may not be waiting on the OWNER: one that ended while a
        # background task it launched is still running is waiting on THAT
        # (Phase 2.5). Saying "waiting for you" there parked cards in limbo.
        from spine.agent import claude_sessions
        try:
            bg = claude_sessions.background_wait(t)
        except Exception:
            bg = None                    # a cue is never worth failing a turn
    return question, cleaned, bg


# How much of a turn's closing words the card keeps.
#
# Was a bare 2000-char slice. The owner photographed the result on his watch
# (2026-08-30): a DELIVERED summary that stopped at "praktisch, wenn" with
# nothing after it - measured afterwards at exactly 2000 characters, cut
# mid-sentence. This is the LAST cap on that text and the only one no reading
# surface can undo: /wear/board's own body cap is already None, and it still
# showed a cut card, because the cut had happened in storage a turn earlier.
#
# 6000 rather than None: this is stored per card, forever, and rides inside the
# board payload for every listed card - unbounded here would put a whole turn
# report behind every row on a watch over a sealed relay. 6000 clears the
# summaries actually being written (the photographed one was ~2600) with room
# to spare, which is the point: the bound must stop being reached in normal
# work, not merely be reached more politely.
REPLY_MAX = 6000


def _clip_reply(text):
    """The reply as the card keeps it - and if it must be cut, cut it VISIBLY.

    A raw slice ends mid-word and reads as a bug in the message rather than as
    a bound on storage; the owner reported exactly that reading. Same rule
    routes_wear._wear_clip already applies on the way out, applied here because
    this is where the text is actually lost."""
    text = text or ""
    if len(text) <= REPLY_MAX:
        return text
    cut = text[:REPLY_MAX]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > REPLY_MAX // 2 else cut).rstrip(" ,;:-") + " …"


def _settle_reply_apply(t, question, cleaned, bg, log):
    """The WRITE half - runs INSIDE _mutate as part of the one atomic
    end-of-turn commit (_finish_turn). Together with _settle_reply_compute this
    is still the one place a reply is interpreted, so the three turn sites
    (dispatch, machine dispatch, steer) cannot drift apart. The machine block is
    stripped from BOTH the audit line and last_reply: the owner reads those, and
    raw protocol JSON in them is noise - the parsed question carries the same
    information in typed form. Returns the notify reason."""
    from spine.ops import ask
    from spine.storage import events
    log.log("reply", cleaned[:REPLY_MAX])
    t["last_reply"] = _clip_reply(cleaned)
    if not question:
        # A turn that does not ask supersedes any older pending question -
        # leaving a stale one would show buttons for a decision the worker has
        # already moved past.
        t.pop("question", None)
        if bg:
            t["waiting_on"] = "background"
            # keep the ORIGINAL start time across turns, so the watcher's
            # give-up window measures the wait, not the last poll
            bg["since"] = (t.get("background") or {}).get("since") or time.time()
            t["background"] = bg
            log.log("note", "wartet auf %d Hintergrund-Task(s): %s"
                    % (bg["n"], ", ".join(bg["names"])[:200]))
            return "background"
        t["waiting_on"] = "you"
        t.pop("background", None)
        return "needs_you"
    t["waiting_on"] = "you"
    t.pop("background", None)
    t["question"] = question
    log.log("note", "FRAGE an dich: " + ask.summary(question))
    # NB: events.emit's own first parameter is called `kind`, so the question's
    # type travels as `qkind` - `kind=` here is a TypeError, not an override.
    events.emit("question", t["id"], qkind=question["kind"],
                n=len(question["questions"]))
    return "question"





def _settle_reply(t, result, log):
    """Compose the two halves on the CALLER's dict (no store write). Production
    goes through _finish_turn, which runs the compute half outside and the
    apply half inside the mutation lock; this seam exists for the settle tests
    and any caller that manages its own persistence via _mutate."""
    question, cleaned, bg = _settle_reply_compute(t, result, log)
    return _settle_reply_apply(t, question, cleaned, bg, log)





def _turn_checkpoint(t):
    """Per-turn rewind anchor: snapshot the worktree so a message can be rewound
    to (files restored to this point) later. Non-fatal if git isn't available.
    NOT for machine cards: their "worktree" is a real folder on the owner's PC
    (often his home), and snapshotting every file in it each turn is both slow
    and none of our business - rewind is a code-worktree feature. Runs OUTSIDE
    the mutation lock (a snapshot can take seconds on a big tree)."""
    if t.get("worktree") and not t.get("machine") and os.path.isdir(t["worktree"]):
        return _checkpoint(t["worktree"])
    return None



def resume_detached(prev_ctx, meta):
    """True when the FIRST turn after a --resume spawn demonstrably did NOT
    continue the conversation (the CLI silently started fresh). Evidence, not
    assumption (Paseo: session identity is verified from the runtime's own
    signals): the init event ECHOES the resumed id on a certain attach
    (resume_echo -> never detached), and a real continuation's FIRST API call
    carries at least the prior context - a fresh boot carries only the brief.
    Floors keep small histories and CLI-side compaction out of the verdict."""
    if not meta.get("resumed_from") or meta.get("resume_echo"):
        return False
    if (prev_ctx or 0) < 25_000:
        return False                     # too small a history to judge safely
    cf = meta.get("ctx_first") or {}
    first_ctx = (cf.get("input_tokens", 0) + cf.get("cache_creation_input_tokens", 0)
                 + cf.get("cache_read_input_tokens", 0))
    if not first_ctx:
        return False                     # no witness - never flag on absence
    return first_ctx < 0.5 * prev_ctx



def _finish_turn(tid, sid, result, meta, log):
    """ONE atomic commit per finished turn (Paseo's one-owner turn-completed
    handler): session rotation + turn count + reply/question/waiting_on +
    status=needs_you + economics land together under the mutation lock, so no
    concurrent cancel/sweep snapshot can resurrect 'running' or tear the
    result apart. Shared by dispatch, machine dispatch and steer. Also emits
    the typed turn-lifecycle record (turn completed/failed/canceled + usage)
    into the flight recorder - Phase 3.2's own-event stream, not a flat step.
    Returns (track, notify_reason)."""
    t = _find(_load(), tid)
    if t is None:
        return None, "needs_you"
    # slow half first, outside the lock: question repair (a model turn), the
    # background probe (disk), the rewind snapshot (git).
    question, cleaned, bg = _settle_reply_compute(t, result, log)
    cp_commit = _turn_checkpoint(t)
    box = {}

    def _commit(tt):
        # session rotation - GUARDED (the invariant): the pointer only moves
        # forward to a session that demonstrably CONTAINS the conversation. A
        # silent fresh start (--resume ignored) once moved the pointer onto an
        # empty thread and the card lost its whole context ("Voellig falscher
        # Kontext"); now that rotation is REFUSED - the next steer resumes the
        # real conversation, and the stray thread is kept in the chain.
        if sid and tt.get("session_id") and sid != tt["session_id"]:
            old = tt["session_id"]
            chain = [s for s in (tt.get("session_chain") or []) if s != old]
            chain.append(old)
            tt["session_chain"] = chain[-6:]         # bounded - last 6 prior sessions
            tt["session_id"] = sid
            if resume_detached(tt.get("ctx_tokens"), meta):
                # --resume did NOT re-attach: the CLI silently started a FRESH
                # session for this turn (a compacted/overflowed tip that plain
                # --resume can't continue). The conversation's LIVE HEAD is now
                # this new session - it holds THIS turn's steer + reply, proven
                # by the result we just read off it - so the pointer FOLLOWS it
                # (Paseo accept-and-rebind: agent.ts handleSystemMessage accepts
                # the changed session id, emits a visible notice, never fails the
                # turn). The old head drops into the chain, where
                # read_transcript_live still renders it as prior history.
                #
                # This SUPERSEDES the old "refuse to advance, keep pointer on the
                # old head" rule. That rule predated chain-rendering and, once the
                # chain rendered, actively HID the turn: the pointer stayed on the
                # old session, so THIS turn's steer was drawn at the TOP as
                # ancient chain history (out of order - the owner's message looked
                # lost), and every future steer re-resumed the same unattachable
                # session, spawning orphan after orphan. Context (the worker's
                # in-memory history) was already gone the moment resume failed;
                # advancing loses nothing further and restores chronology.
                log.log("note", "⚠ Kontext verloren: die Session liess sich nicht "
                        "fortsetzen (%s…), der Worker hat frisch begonnen (%s…). "
                        "Der bisherige Verlauf bleibt sichtbar; ab hier baut er "
                        "auf der neuen Session auf." % (str(old)[:8], str(sid)[:8]))
        else:
            tt["session_id"] = sid or tt.get("session_id")
        tt["turns"] = tt.get("turns", 0) + 1
        # A concurrent accept (move_lane -> done) may have landed and closed
        # this very card WHILE this turn was still running (the merge and the
        # turn are two independent writers with no ordering between them).
        # Recording the reply is still correct - it is what the worker said -
        # but resetting status to needs_you would erase the accept the instant
        # after it happened, leaving a real merge on main with a board that
        # never learned about it (measured 2026-08-28, chat-wear-os-
        # integration-phas: gate+merge landed at 11:35:47, this same overwrite
        # fired seven seconds later). lane is the one owner-only field move_lane
        # sets under its own _mutate right after the merge, so it is the
        # ground-truth witness here - not a stored "done" flag being trusted,
        # a write that already happened being not undone.
        _already_landed = tt.get("lane") == "done"
        box["reason"] = _settle_reply_apply(tt, question, cleaned, bg, log)
        tt["status"] = "accepted" if _already_landed else "needs_you"
        # A successful turn makes any stale interrupt/zombie note obsolete -
        # otherwise the card keeps reading "daemon restarted mid-turn" from a
        # PAST bounce when the turn just ended cleanly.
        gr = tt.get("gate_report")
        if isinstance(gr, list) and any(ZOMBIE_NOTE in x or RESUME_NOTE in x
                                        or GATE_CUT_NOTE in x for x in gr):
            tt.pop("gate_report", None)
        # A turn that ended CLEANLY (real reply, not an error) broke out of any
        # loop, so the burn signal is stale - clear it. A looping turn never
        # reaches a clean end (the PM's correction interrupts it, or it errors),
        # so its `corrections` count survives to drive escalation.
        if tt.get("burn") and not meta.get("is_error") and not meta.get("canceled"):
            tt.pop("burn", None)
        box["cost"] = _record_turn(tt, meta, cp_commit)

    t = _mutate(tid, _commit) or t
    # the turn's lifecycle as its OWN typed event (Paseo turn_completed/
    # turn_failed/turn_canceled + usage), woven into the card feed by `ta`.
    _log_turn_end(log, meta, box.get("cost"))
    _emit_delivered_parked(t, box.get("reason", "needs_you"), cleaned)
    return t, box.get("reason", "needs_you")


def _emit_delivered_parked(t, reason, cleaned):
    """A worker that says DELIVERED and then PARKS on needs_you is finished
    work nobody drives (owner 2026-08-22: the research card delivered at 08:50
    and sat in working). Henry owns FINISH-WHAT-YOU-START (verb move ->
    review/done, full rails) but only hears the escalation CHANNEL - so the
    engineer cell reports the FACT here and Henry judges whether to land it.
    Facts only, event-time: the DELIVERED marker is the worker's own closing
    signal (harness convention, same anchor outcomes.py keys off). Fast-track
    and direct cards are excluded - their own pipelines already land/deploy."""
    try:
        if reason != "needs_you" or not t or t.get("lane") != "working":
            return
        if t.get("fast_track") or t.get("direct"):
            return
        from spine.turn.outcomes import _DELIVERED_RE
        if not _DELIVERED_RE.search((cleaned or "")[:200]):
            return
        from spine.registry import escalations
        if any(e.get("kind") == "delivered-parked" and e.get("card") == t["id"]
               for e in escalations.list_open()):
            return                      # already reported, Henry hasn't judged yet
        escalations.emit("delivered-parked", card=t["id"],
                         detail="Worker meldet DELIVERED, Karte parkt in working: %s"
                                % (t.get("task") or "")[:140])
    except Exception:
        pass                            # a cue is never worth failing a turn



# -- lanes: the kanban IS the company structure, just relabeled ----------
# backlog = request filed (client needs ABC; nothing started, no session yet)
# working = dispatched      (agent session live on its branch)
# review  = submitted       (work + recording handed back for acceptance)
# done    = accepted        (deliverable taken; branch ready to merge)
