# -*- coding: utf-8 -*-
"""Engineer background-task lifecycle - extracted from sessions.py (god-file
breakup, see spine/registry/debt.py daemon-god-files).

A background task (a Bash/Task tool the card's worker spawned and is
waiting on) is a CHILD of the worker process - Paseo's ProviderSubagent
model: bg_upsert folds ONE lifecycle event onto the track at event time
(never reconstructed by transcript forensics), reconcile_bg is finishAll
(a dead worker process means every still-running task died with it),
_sweep_background is the poller that continues a card once its background
work genuinely finished.

sessions.py's own functions (steer, _load, _find, _mutate) are imported
LAZILY inside the function bodies that need them - sessions.py imports THIS
module at module level to re-export these names unchanged for existing
callers (lifecycle.py, drivers.py, claude_sessions.py all already call
sessions.bg_upsert/reconcile_bg directly), so a top-level import back would
cycle."""
import threading as _threading
import time

_BG_HISTORY_CAP = 12       # terminal tasks kept for the app; running ones never dropped
BG_TERMINAL = ("completed", "failed", "canceled")
_BG_POLL_S = 20.0            # how often the watcher re-reads the transcripts
_BG_MAX_WAIT_S = 6 * 3600    # stop watching a task that never reports (6h)
_bg_watcher_started = False


def bg_upsert(tid, uid, title=None, detail=None, status="running", result=None):
    """Fold ONE background-task LIFECYCLE event onto the track - Paseo's
    ProviderSubagentStore.apply(): a descriptor per task with an explicit status
    (running -> completed|failed|canceled), maintained at EVENT TIME by the pump,
    never reconstructed by transcript forensics. A launch upserts 'running', a
    <task-notification> 'completed'; reconcile_bg cancels survivors of a dead
    process. Terminal tasks are kept (bounded) so the app can show what the
    worker did and how it ended - clickable, like Paseo."""
    from cells.engineer.cards.sessions import _mutate
    if not uid:
        return
    def _apply(t):
        tasks = dict(t.get("bg_tasks") or {})
        cur = dict(tasks.get(uid) or {})
        now = time.time()
        cur.setdefault("since", now)
        cur.setdefault("title", title or "task")
        if title:
            cur["title"] = title[:80]
        if detail:
            cur["detail"] = detail[:600]
        cur["status"] = status
        if result is not None:
            cur["result"] = str(result)[:2000]
        cur["updated"] = now
        tasks[uid] = cur
        # bound the TERMINAL history (last N by finish time); a running task is
        # never evicted - it is load-bearing for the waiting_on gate.
        terminal = sorted(((u, v) for u, v in tasks.items()
                           if v.get("status") in BG_TERMINAL),
                          key=lambda kv: kv[1].get("updated", 0))
        for u, _v in terminal[:max(0, len(terminal) - _BG_HISTORY_CAP)]:
            tasks.pop(u, None)
        t["bg_tasks"] = tasks
    _mutate(tid, _apply)


def reconcile_bg(tid, status="canceled", why="Prozess beendet, bevor der Task meldete"):
    """finishAll (Paseo sidechain-tracker.finishAll): a background task is a CHILD
    of the worker process, so when that process dies - a timeout tree-kill, a
    daemon restart, a crash - every still-running task died with it and can never
    report. Transition them to a terminal status so a dead build never lingers as
    a phantom the card waits on forever (the 'wartet auf N Hintergrund-Task' that
    only ever grew). Returns how many were reconciled."""
    from cells.engineer.cards.sessions import _mutate
    box = {}
    def _apply(t):
        tasks = t.get("bg_tasks")
        if not isinstance(tasks, dict):
            return False
        n = 0
        for v in tasks.values():
            if v.get("status", "running") == "running":
                v["status"] = status
                v["updated"] = time.time()
                v.setdefault("result", why)
                v.setdefault("title", v.get("desc") or "task")   # migrate pre-P2 entries
                n += 1
        if not n:
            return False
        box["n"] = n
    _mutate(tid, _apply)
    return box.get("n", 0)


def running_bg(t):
    """Titles of this card's background tasks that are STILL RUNNING - the ONE
    reading of the descriptors for everyone who asks "does this card still
    work?" (board snapshot, daemonctl's restart refusal, restart_daemon.py).
    A card whose turn ended (status=needs_you) can carry these for an hour:
    2026-09-17 three readers had three answers - the snapshot said nothing
    runs, the in-app restart would have killed a 27-run benchmark, only the
    CLI restart refused. 'running' is trustworthy because reconcile_bg closes
    every descriptor when the owning process dies."""
    tasks = t.get("bg_tasks")
    if not isinstance(tasks, dict):
        return []
    return [str(v.get("title") or k) for k, v in tasks.items()
            if isinstance(v, dict) and v.get("status", "running") == "running"]


def _bg_continue_on(t):
    """policy.auto_continue (default on). Off => the card keeps the cue but is
    never steered automatically."""
    from spine.storage import events
    pol = events.settings().get("policy") or {}
    return bool(pol.get("auto_continue", True))


def _continue_prompt():
    """Tagged as harness-injected so the card feed renders it as a system note
    instead of a message the owner appears to have typed (ask.harness_msg)."""
    from spine.ops import ask
    return ask.harness_msg(
        "background-done",
        "Dein Hintergrund-Task ist fertig - das hier ist ein automatischer "
        "Hinweis des Harness, keine Nachricht vom Owner.\n"
        "Hol dir seine Ausgabe (BashOutput bzw. das Task-Ergebnis) und arbeite "
        "genau dort weiter, wo du auf ihn gewartet hast. Wenn die Ausgabe zeigt, "
        "dass etwas fehlgeschlagen ist, behebe es oder sag klar, was der Owner "
        "entscheiden muss.")


def _repair_bg_gate(t):
    """Close the launch/settle RACE, and return the repaired track (or None).

    bg_upsert folds a task at EVENT TIME; _settle_reply_compute reads the
    registry once when the turn ends. A task launched in the worker's LAST
    tool call can therefore be registered AFTER the settle already decided
    "nothing outstanding" - the turn parks waiting_on='you', status
    needs_you, and the card claims it needs the owner while a job of its own
    is still running. Measured 2026-09-21 on 20260921-073824-direct: the
    track's `updated` and the task's `since` are the SAME second (08:10:12),
    waiting_on='you', background=None, task 'running'. Nothing repaired it:
    _sweep_background only ever looked at cards already gated on
    'background', so the card sat parked and the owner saw "braucht mich".

    Ordering-independent by construction: this asks the live driver whether a
    turn is in flight instead of trusting the stored status, so it is correct
    whether the upsert lands before or after _finish_turn. A pending owner
    question always wins - that is a real needs_you."""
    if (t.get("waiting_on") == "background" or t.get("question")
            or t.get("status") == "running"):
        return None
    reg = t.get("bg_tasks")
    if not isinstance(reg, dict):
        return None
    now = time.time()
    open_reg = [v for v in reg.values()
                if v.get("status", "running") == "running"
                and now - (v.get("since") or now) < _BG_MAX_WAIT_S]
    if not open_reg:
        return None
    from spine.agent import drivers
    if drivers.turn_active(t["id"]):
        return None                  # the settle that is still to come owns it
    from cells.engineer.cards.sessions import _mutate

    def _fix(tt):
        if (tt.get("waiting_on") == "background" or tt.get("question")
                or tt.get("status") == "running"):
            return False
        tt["waiting_on"] = "background"
        bg = dict(tt.get("background") or {})
        bg["n"] = len(open_reg)
        bg["names"] = [v.get("title") or v.get("desc") or "task" for v in open_reg[:4]]
        bg.setdefault("since", min(v.get("since") or now for v in open_reg))
        tt["background"] = bg
    fixed = _mutate(t["id"], _fix)
    if fixed:
        try:
            from spine.ops.actionlog import ActionLog
            ActionLog(fixed["run_dir"]).log(
                "note", "Gate korrigiert: Karte stand auf 'braucht dich', wartet aber "
                        "auf %d Hintergrund-Task(s) - %s"
                        % (len(open_reg),
                           ", ".join(v.get("title") or "task" for v in open_reg[:4])[:160]))
        except Exception:
            pass
    return fixed


def _sweep_background():
    """One pass: continue every card whose background task has finished.

    Two jobs with DIFFERENT gates, and they must not share one. Keeping
    waiting_on honest - orphan reconciliation, the give-up window, clearing the
    cue once nothing is outstanding - runs for EVERY waiting card. Only the
    auto-steer is gated on lane + policy.auto_continue. They used to be gated
    together, so a card with auto_continue off (or parked outside
    working/review) kept its "wartet auf Hintergrund-Task" cue forever after
    the tasks were long done - and with it the idle-eviction protection
    (drivers._running_cards), leaking the very session it no longer needed."""
    from cells.engineer.cards.sessions import _load, _find, _mutate, steer
    for t in _load():
        t = _repair_bg_gate(t) or t
        if t.get("waiting_on") != "background" or t.get("status") == "running":
            continue
        # ORPHAN reconciliation (finishAll): a background task is a child of the
        # worker process. If this daemon holds NO live session for the card (a
        # restart wiped the registry, or the worker crashed) and no turn is in
        # flight, the tasks died with their parent - flip the still-running ones
        # to 'canceled' NOW instead of parking the card for the full 6h. The
        # continue-on-clear path below then resumes the worker to pick up.
        from spine.agent import drivers
        if not drivers.has_session(t["id"]) and not drivers.turn_active(t["id"]):
            if reconcile_bg(t["id"]):
                t = _find(_load(), t["id"]) or t
        since = ((t.get("background") or {}).get("since")
                 or _epoch_of(t.get("updated")) or time.time())
        if time.time() - since > _BG_MAX_WAIT_S:
            gave = {}

            def _giveup(tt):
                if tt.get("waiting_on") != "background":
                    return False
                tt["waiting_on"] = "you"     # give up watching, hand it back
                tt.pop("background", None)
                gave["ok"] = True
            t = _mutate(t["id"], _giveup) or t
            if gave.get("ok"):
                # the hand-back must never be silent: the card just became a
                # real needs_you (status was already parked there by
                # _finish_turn) and no follow-up turn exists to notify for it.
                from spine.ops.actionlog import ActionLog
                ActionLog(t["run_dir"]).log(
                    "note", "Hintergrund-Task hat nach 6h nicht gemeldet - "
                    "Karte zurueck an dich")
                from spine.comms import notify
                try:
                    notify.card_event(t, "needs_you")
                except Exception:
                    pass
            continue
        from spine.agent import claude_sessions
        try:
            state, _payload = claude_sessions.background_state(t)
        except Exception:
            continue                          # try again next pass
        # Continue ONLY on positive evidence that the transcript was read and
        # nothing is outstanding. "unknown" (missing/rotated transcript) must
        # never be mistaken for "the build finished" - that would spend a real
        # turn of the owner's money on a guess.
        if state != "clear":
            continue
        # Clear the claim BEFORE steering: that is what stops the next pass from
        # firing this card a second time, and it is why the steer can safely be
        # detached below. The in-lock recheck makes a racing second watcher pass
        # lose deterministically.
        claim = {}

        def _claim(tt):
            if tt.get("waiting_on") != "background":
                return False
            tt["waiting_on"] = "you"
            tt.pop("background", None)
            claim["ok"] = True
        t = _mutate(t["id"], _claim) or t
        if not claim.get("ok"):
            continue
        from spine.ops.actionlog import ActionLog
        # steer only ACTIVE work, and only if the owner allows auto-continue;
        # otherwise the cue is cleared (above) and the card honestly waits on
        # the owner instead of on a task that has already reported. `status`
        # was already forced to "needs_you" by the turn that started this wait
        # (_finish_turn always sets it, background-vs-not is carried by
        # waiting_on alone) - so the claim above just made is_delivered() true.
        # That transition has no turn of its own to notify from (unlike the
        # auto-continue branch below, which gets a fresh turn's own
        # card_event), so the push has to fire HERE or it never fires at all.
        if t.get("lane") not in ("working", "review") or not _bg_continue_on(t):
            ActionLog(t["run_dir"]).log(
                "note", "Hintergrund-Task fertig - Karte wartet auf dich "
                "(kein Auto-Continue)")
            from spine.comms import notify
            try:
                notify.card_event(t, "needs_you")
            except Exception:
                pass
            continue
        ActionLog(t["run_dir"]).log(
            "note", "Hintergrund-Task fertig - Karte laeuft automatisch weiter")
        from spine.storage import events
        events.emit("autocontinue", t["id"], actor="daemon")

        # A continuation is a full turn (up to 1800s). Run it OFF the watcher
        # thread - held inline, one long build's follow-up would stall the whole
        # loop, so a second card finishing behind it would wait out that entire
        # turn before anyone noticed. Per-card serialisation still holds: _turn
        # takes the card's own lock.
        def _go(tid=t["id"]):
            try:
                steer(tid, _continue_prompt(), actor="daemon", source="background-task")
            except Exception as e:
                print("auto-continue failed for %s: %s" % (tid, e))

        _threading.Thread(target=_go, daemon=True).start()


def _epoch_of(stamp):
    try:
        return time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return None


def start_background_watcher(interval=None):
    """Start the auto-continue loop (idempotent). Called from server.serve."""
    global _bg_watcher_started
    if _bg_watcher_started:
        return
    _bg_watcher_started = True
    iv = _BG_POLL_S if interval is None else interval
    import threading

    def loop():
        while True:
            time.sleep(iv)
            try:
                _sweep_background()
            except Exception as e:
                print("background watcher error:", e)

    threading.Thread(target=loop, daemon=True).start()
