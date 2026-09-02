# -*- coding: utf-8 -*-
"""Card lifecycle observation SERVICE - extracted from sessions.py. present()
is the "turn_active is a lifecycle observation" derivation (a phantom
`running` with a dead process reads as needs_you, at READ time - Paseo-style,
never a stored flag); sweep_zombies + start_zombie_reconciler are the startup
+ periodic backstop that reconciles every stuck card. Imports the already-
extracted services directly (trackstore). The one still-trapped dependency
(reconcile_bg, the bg-task cluster) is reached via a lazy `import sessions`
inside sweep_zombies.
"""
import os
import time

from spine.storage.trackstore import _load, _mutate
from cells.engineer.turnrunner import ZOMBIE_NOTE, RESUME_NOTE, GATE_CUT_NOTE


_BOUNCE_ESCALATE_AT = 3   # consecutive daemon-restart bounces before the note stops
                          # inviting a doomed retry and says so plainly instead


def _interrupt_note_report(t, note):
    """gate_report is the channel the worker is fed on the next steer
    (_pending_context). An interrupt (zombie sweep / Stop on a dead session) must
    NOT clobber a REAL gate/merge failure that was already there - overwriting it
    with 'daemon restarted mid-turn' leaves the worker blind, chasing a phantom
    cause across 2-3 dead-end steers. Prepend the interrupt note but PRESERVE any
    substantive prior failure lines (dropping only stacked interrupt notes)."""
    prior = [l for l in (t.get("gate_report") or [])
             if RESUME_NOTE not in l and ZOMBIE_NOTE not in l and GATE_CUT_NOTE not in l]
    return [note] + prior


def _promote_live_session(t):
    """Paseo-style LOSSLESS resume. A turn that died WITH the daemon (a restart, a
    crash) emitted a rotated `claude --resume` session id to run_dir/
    live_session.txt, but the track's session_id is only written back AFTER a turn
    returns - so a killed turn leaves the card pointing at the PRE-steer session.
    The next steer would then --resume the old conversation and lose the
    interrupted turn's context. Promoting the live session id fixes that: the next
    steer resumes the actual interrupted conversation. This is why Paseo can idle
    a session and silently continue it; we now keep the same context, just surfaced
    (the owner re-steers to continue). Returns True if a newer session was promoted."""
    rd = t.get("run_dir") or ""
    if not rd:
        return False
    try:
        with open(os.path.join(rd, "live_session.txt"), encoding="utf-8") as f:
            live = f.read().strip()
    except OSError:
        return False
    if live and live != t.get("session_id"):
        t["session_id"] = live
        return True
    return False

def _track_idle_s(t):
    """Seconds since the card last showed ANY activity (its flight-recorder /
    live-session files). Distinguishes a true zombie from the brief steer-START
    window where status is already 'running' but the session is still spawning
    (has_session False for ~1s). Unknown -> treated as very idle."""
    rd = t.get("run_dir") or ""
    newest = 0.0
    for f in ("actions.jsonl", "live_session.txt", "live_partial.txt"):
        try:
            newest = max(newest, os.path.getmtime(os.path.join(rd, f)))
        except OSError:
            pass
    return (time.time() - newest) if newest else 1e9


PRESENT_IDLE_S = 45      # spawn window: a just-started steer may briefly show
                         # running before its turn registers - don't coerce it


def _present_gxp(t, out):
    """Derive the two GxP facts the board needs, at READ time.

    Same stance as the status coercion above: derived on the way out, never
    stored. A persisted "this card is approved" boolean would go stale the
    moment the branch moves - exactly the class of bug the signature design
    exists to avoid.

    Cost is why `gxp_signed` answers the CHEAP question ("is there an unconsumed
    approved signature") and not the expensive one ("...and does it still match
    git"). The board polls, and the exact drift check costs two `git rev-parse`
    per card. It runs where it matters instead: when the sign-off window opens
    (signatures.subject) and again in the lane machine right before the merge
    (gxp.accept_block_reason). The badge is a VIEW; the guard is the authority,
    and only the guard can refuse.

    Out of scope this adds nothing - no field, no git, nothing beyond the lock
    check itself.
    """
    from spine.auth import gxp
    if not gxp.in_scope(t):
        return out
    out = dict(t) if out is None else out
    out["gxp_scope"] = True
    out["gxp_signed"] = any(
        s.get("meaning") == "approved" and not s.get("consumed_by")
        for s in (t.get("signatures") or []))
    return out


def present(t):
    """READ-side lifecycle derivation for the API (Paseo's normalizeArchivedStatus,
    server-side): a stored 'running' is only ever DELIVERED as running while a
    turn is actually in flight (drivers.turn_inflight). Otherwise - once past the
    spawn window - the client gets 'needs_you', WITHOUT touching the stored
    value. A phantom spinner is thereby impossible no matter what any write race
    puts in the DB (invariant I2); the reconciler remains the healer of the
    stored value. Returns a copy when coercing, the original otherwise.

    The invariant has TWO directions and only one of them used to hold. A
    phantom spinner (badge says running, nothing runs) was impossible; the
    MIRROR - badge says stopped while the turn runs - was not, because a turn
    QUEUED on the desktop/direct lock is not yet turn_active. That is the more
    expensive lie: the owner reads "stopped, waiting for me" while the card
    spends. turn_inflight covers both halves, and the queue is surfaced
    explicitly (`queued_for`) so running-but-not-yet-spawned reads honestly
    instead of looking like a wedged spinner."""
    out = None
    if (t or {}).get("status") == "running":
        from spine.agent import drivers
        if drivers.turn_queued(t["id"]) and not drivers.turn_active(t["id"]):
            out = dict(t)
            out["queued_for"] = "lock"     # derived hint: turn decided, waiting to spawn
        elif not drivers.turn_active(t["id"]) and _track_idle_s(t) > PRESENT_IDLE_S:
            out = dict(t)
            out["status"] = "needs_you"
            out["status_derived"] = True   # marker: coerced at read, not stored
    out = _present_gxp(t, out)
    out = _present_device(t, out)
    return out if out is not None else t


def _present_device(t, out):
    """Derive the board's device-execution hint at READ time (ops/docs/backlog/
    remote-device-execution PLAN-hardening.md Phase G). Same stance as
    _present_gxp: a VIEW, computed on the way out, never stored. `exec_site`
    is already on the track dict (it flows to the payload untouched) - this
    only ADDS `device_stale`, a cheap hint that a device card in `working`
    has been claimed longer than the sweep's TTL, i.e. its device may be
    offline. It is deliberately the CHEAP question (claimed_at age only, from
    the card's own field) - the AUTHORITATIVE offline decision (age AND the
    device's last_seen) still lives in dispatch.sweep_stale_device_claims,
    which is what actually reclaims the card. The badge points; the sweep
    acts."""
    exec_site = (t or {}).get("exec_site") or ""
    if not exec_site.startswith("local:"):
        return out
    stale = False
    if t.get("lane") == "working" and t.get("claimed_at"):
        from datetime import datetime
        try:
            from spine.storage import events
            ttl = float(((events.settings().get("policy") or {}).get("device") or {})
                        .get("claim_ttl_s", 1800))
        except Exception:
            ttl = 1800.0
        try:
            age = (datetime.strptime(time.strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")
                   - datetime.strptime(t["claimed_at"], "%Y-%m-%d %H:%M:%S")).total_seconds()
            stale = age > ttl
        except (ValueError, TypeError):
            stale = False
    if stale:
        out = dict(t) if out is None else out
        out["device_stale"] = True
    return out


def sweep_zombies(min_idle_s=0):
    from cells.engineer import sessions  # lazy: reconcile_bg still lives there
    """Reconcile status vs the live session: a card flagged status=running with no
    owning worker is a ZOMBIE (its turn died with a prior daemon, or a dead/racing
    steer thread left it stuck). Flip every such track to bounced with a visible
    note (gate_report is the bounce-reason channel both UIs already render), audit
    it, and push - so the owner learns the instruction was lost instead of staring
    at a frozen card.

    min_idle_s=0 at startup (every running-without-session card died with the old
    daemon - reap all). The PERIODIC reconciler passes min_idle_s>0 so it skips the
    steer-start race window and only reaps cards genuinely idle that long.

    Paseo-parity (the loss is now RECOVERABLE): before surfacing, promote the
    interrupted session id (run_dir/live_session.txt) onto the track, so
    re-steering RESUMES the interrupted conversation instead of the pre-steer
    one. We still surface it (bounce is re-steerable, and async push-driven
    ownership wants the owner to know a turn was cut) - but the context is no
    longer thrown away, which is what made Paseo's silent idle-resume feel
    seamless. Cards with a promotable session get the resume note."""
    from spine.agent import drivers
    from spine.storage import events
    from spine.comms import notify
    from spine.ops.actionlog import ActionLog
    swept = []
    for t in _load():
        # STARTUP (min_idle_s==0): every worker tree died with the old daemon -
        # so did every background agent inside it. A registry entry surviving
        # here is a zombie by construction: clear it (with a visible note) so
        # the card doesn't wait on a task that can never report.
        if not min_idle_s and isinstance(t.get("bg_tasks"), dict) \
                and not drivers.has_session(t["id"]):
            names = ", ".join((v.get("title") or v.get("desc") or "task")
                              for v in t["bg_tasks"].values() if v.get("status", "running") == "running")[:120]
            # reconcile (finishAll), don't DELETE: the descriptors survive as
            # 'canceled' so the owner can still see what the worker was running
            # and that the restart ended it (Paseo clickable history). Only the
            # waiting_on gate is cleared so the card is handed back.
            n = sessions.reconcile_bg(t["id"], why="Mit dem Daemon-Neustart abgebrochen")   # lazy: bg-task cluster still in sessions.py
            _mutate(t["id"], lambda tt: tt.__setitem__("waiting_on", "you")
                    if tt.get("waiting_on") == "background" else None)
            if n:
                try:
                    ActionLog(t["run_dir"]).log(
                        "note", "Hintergrund-Task(s) mit dem Daemon-Neustart abgebrochen: %s "
                        "- Henry prueft, ob sie neu gestartet werden." % names)
                except Exception:
                    pass
                # Judgement about WHAT to do with the aborted work (re-run the
                # deploy? obsolete?) is Henry's, not code's - report, don't decide
                # (owner decree 2026-08-21, ops/docs/backlog/henry-exception-broker).
                try:
                    from spine.registry import escalations
                    escalations.emit("aborted-by-restart", card=t["id"], detail=names)
                except Exception:
                    pass
        st = t.get("status")
        if st == "running":
            # genuinely working = a TURN is in flight (Paseo: "running" is a
            # derived observation, not a stored flag). has_session() was the
            # old test and it lied by design: a soft cancel keeps the worker
            # process alive for --resume, so an idle-after-cancel worker looked
            # busy forever and the frozen card was never swept ("stuck again").
            # turn_INFLIGHT, not turn_active: a turn queued behind the desktop
            # or direct-tree lock has no session yet (drivers.run hasn't been
            # reached) and no run_dir activity to make _track_idle_s vouch for
            # it - a brand-new card's run_dir is empty, so idle reads 1e9 and
            # the guard below never fires. That is exactly how card
            # 20260902-040607 got bounced 63s after being filed with the
            # phantom note "daemon restarted mid-turn", then spawned and ran
            # for minutes under a red badge once the lock freed (2026-09-02).
            if drivers.turn_inflight(t["id"]) or (min_idle_s and _track_idle_s(t) < min_idle_s):
                continue
            if drivers.has_session(t["id"]):
                # Worker alive, NO turn in flight: the turn already ended (or
                # was cancelled) and a racing status write resurrected
                # 'running'. Nothing died and nothing was lost - settle QUIETLY
                # to needs_you (Paseo's running->idle on turn end), no bounce,
                # no zombie note. Re-steering resumes the live session as-is.
                did = {}

                def _settle(tt):
                    # in-lock recheck: a turn may have started (or the steer
                    # thread settled it) since the snapshot above
                    if tt.get("status") != "running" or drivers.turn_inflight(tt["id"]):
                        return False
                    tt["status"] = "needs_you"
                    did["ok"] = True
                t2 = _mutate(t["id"], _settle)
                if not did.get("ok"):
                    continue
                t = t2
                try:
                    ActionLog(t["run_dir"]).log(
                        "note", "SETTLED - Turn war schon beendet, Status hing auf "
                        "'running' (Schreib-Rennen). Session lebt - einfach weiter steuern.")
                except Exception:
                    pass
                events.emit("settle", t["id"], reason="stale_running", actor="daemon")
                try:
                    notify.card_event(t, "needs_you")
                except Exception:
                    pass
                swept.append(t["id"])
                continue
        elif st == "gating":
            # the gate runs SYNCHRONOUSLY in a request thread (no session to check),
            # so a restart mid-gate freezes the card at 'gating' forever. Whether
            # THIS process is running that pipeline right now is an OBSERVATION
            # (lanemachine.lane_active - drivers.turn_active's pattern): a live
            # gate/merge/deploy is NEVER reaped, however long the suite takes.
            # The previous idle-clock bound here ("a real gate's runtime, ~2min")
            # was a duration GUESS, and the day the suite outgrew it the sweep
            # bounced every live gate at ~120s with a phantom "daemon restarted"
            # note while the real gate finished minutes later (measured
            # 2026-08-20, card req-worktree-base-sync). The clock below now only
            # reaps a gating card whose pipeline is verifiably NOT alive in this
            # process: the daemon died mid-gate (startup, min_idle_s==0) or the
            # pipeline thread crashed without writing a terminal status.
            from cells.engineer import lanemachine  # lazy: avoids an import cycle at module load
            if lanemachine.lane_active(t["id"]):
                continue
            if _track_idle_s(t) < (120 if min_idle_s else 0):
                continue
        else:
            continue
        box = {}
        # Repeated-bounce evidence BEFORE this one is recorded, so a card that
        # keeps taking the daemon down with it (not just failing its own turn)
        # gets told apart from an ordinary one-off restart. Derived from the
        # event trail (consecutive_gate_fails' pattern), never a stored flag.
        prior_bounces = events.consecutive_bounces(t["id"])

        def _bounce(tt, st=st):
            if tt.get("status") != st:
                return False             # settled by another writer meanwhile
            if st == "gating":
                # No worker turn was in flight - a gate/merge pipeline was. There
                # is no session to promote and no "last instruction" to resend;
                # say what actually died and how to recover (re-submit).
                note = GATE_CUT_NOTE
            else:
                note = RESUME_NOTE if _promote_live_session(tt) else ZOMBIE_NOTE
            if prior_bounces + 1 >= _BOUNCE_ESCALATE_AT:
                note = ("daemon restarted mid-turn %dx IN A ROW on this card - "
                         "resending the same instruction has failed repeatedly and "
                         "is likely to fail again (the session itself may be too "
                         "large/expensive to resume, or stuck in a loop). Do not "
                         "just retry - fork this card into a fresh session, or ask "
                         "the owner what to do." % (prior_bounces + 1))
            box["note"] = note
            tt["status"] = "bounced"
            tt["gate_report"] = _interrupt_note_report(tt, box["note"])
        t = _mutate(t["id"], _bounce) or t
        if "note" not in box:
            continue
        try:
            ActionLog(t["run_dir"]).log("note", "ZOMBIE SWEEP - " + box["note"])
        except Exception:
            pass
        events.emit("bounce", t["id"], reason="daemon_restart", actor="daemon")
        try:
            notify.card_event(t, "bounced")
        except Exception as e:
            print("sweep_zombies: push failed for %s: %s" % (t["id"], e))
        swept.append(t["id"])
    return swept


def check_landed_not_closed():
    """Board-vs-git reconciliation for the OTHER half of the accept race (the
    live-turn guard in lanemachine._move_lane stops new occurrences; this
    catches any that already happened, including ones from before that fix -
    e.g. a daemon restart landing squarely between the merge and the
    _accepted mutate). A card resting on Review/needs_you whose branch is
    ALREADY fully merged into its base (git ahead-count, not a stored flag -
    same evidence _merge_to_main itself uses to call something 'already_merged')
    is a board that forgot a real merge happened.

    SELF-HEALS, deliberately, rather than only reporting: closing this gap is
    a MECHANICAL fact-check ("did the branch already land? yes/no"), not a
    judgement call, so it does not belong on Henry's desk (CLAUDE.md: hard
    invariants live in code; Henry judges what code cannot decide). The
    resume is just a normal move_lane("done") retry - _merge_to_main's own
    ahead==0 'already_merged' branch makes this call idempotent by
    construction (same durable-execution shape as an outbox retry: the
    pipeline's terminal write is the only thing that changes, nothing lands
    twice). Escalates ONLY when the retry itself does not reach lane=="done"
    (a real conflict appeared meanwhile, gate turned red, etc.) - THAT is a
    judgement call, and Henry gets it with the retry's own report attached
    instead of a guess. Measured 2026-08-28: chat-wear-os-integration-phas
    landed on main at 11:35:47 but a concurrently-finishing turn overwrote the
    track back to review/needs_you seven seconds later - nothing before this
    would ever have told the board (or Henry) the two had split."""
    from spine.storage.trackstore import _load as _load_t
    from spine.git.gitutil import _git_try
    from spine.agent import drivers
    from cells.engineer import lanemachine
    from spine.registry import escalations
    open_kinds = {(e.get("kind"), e.get("card")) for e in escalations.list_open()}
    for t in _load_t():
        if t.get("lane") != "review" or t.get("status") != "needs_you":
            continue
        tid = t["id"]
        if t.get("question") or drivers.turn_inflight(tid) or lanemachine.lane_active(tid):
            continue                    # not settled yet - not this check's business
        if not t.get("turns") and not t.get("session_id"):
            # Never dispatched: ahead==0 here means "no work was ever done",
            # not "the work already landed" - closing it would archive a
            # backlog-shaped card, and even attempting the move produced a
            # confusing "Gate ist rot - never dispatched" chat line (measured
            # 2026-08-28 12:44, card req-worktree-base-sync). Same evidence
            # rule as everywhere: turns/session are the runtime's own record
            # that an agent actually worked this card.
            continue
        repo, branch = t.get("repo"), t.get("branch")
        if not repo or not branch or not os.path.isdir(repo):
            continue
        try:
            cur = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")[1]
            if not cur or cur == branch:
                continue                 # repo mid-something else - not our call to make
            ahead = int(_git_try(repo, "rev-list", "--count", "%s..%s" % (cur, branch))[1] or "0")
        except Exception:
            continue
        if ahead != 0:
            continue                     # real unlanded work - Review is correct
        try:
            r = lanemachine.move_lane(tid, "done", actor="reconciler")
        except Exception as e:
            escalations.emit("landed-not-closed", card=tid,
                             detail="Karte '%s': Branch ist bereits vollstaendig in %s "
                                    "(0 Commits Unterschied), aber der automatische "
                                    "Nachhol-Versuch (move -> done) crashte: %s"
                                    % ((t.get("task") or "")[:80], cur, str(e)[:250]))
            continue
        if (r or {}).get("lane") == "done":
            print("RECONCILER: closed landed-but-not-closed card %s (already in %s)"
                  % (tid, cur), flush=True)
            continue
        if ("landed-not-closed", tid) in open_kinds:
            continue                     # already reported, Henry hasn't judged yet
        escalations.emit("landed-not-closed", card=tid,
                         detail="Karte '%s': Branch ist bereits vollstaendig in %s "
                                "(0 Commits Unterschied), aber der automatische "
                                "Nachhol-Versuch (move -> done) blieb auf Review "
                                "(%s) - braucht einen Blick: %s"
                                % ((t.get("task") or "")[:80], cur, (r or {}).get("lane"),
                                    str((r or {}).get("merge_report")
                                        or (r or {}).get("gate_report") or "")[:300]))


def sweep_pending_compaction():
    """Retry a compaction that got cut. sessions._maybe_compact re-queues onto
    the card (compact_pending) whenever its /compact turn was interrupted
    rather than completed - the 2026-08-30 case: the owner types while the
    harness is compacting, interrupt-and-replace kills the maintenance turn,
    and nothing ever compacted the 92%-full session again. This is the "next
    idle moment" half: the card must be settled (no live turn, no pending
    question, not mid-lane-move) before we spend a turn on maintenance.

    Deliberately NOT a timer on the card: the flag is set at event time by the
    one compaction owner and cleared by it too, so this sweep only ever ACTS on
    a fact the runtime recorded - it never reconstructs "probably needs
    compacting" by re-reading transcripts."""
    import threading
    from spine.storage.trackstore import _load as _load_t
    from spine.agent import drivers
    from cells.engineer import sessions, lanemachine
    from spine.ops.actionlog import ActionLog
    for t in _load_t():
        if not t.get("compact_pending") or not t.get("session_id"):
            continue
        tid = t["id"]
        if t.get("status") == "running" or t.get("question"):
            continue
        if drivers.turn_inflight(tid) or sessions.compacting(tid) is not None:
            continue
        try:
            if lanemachine.lane_active(tid):
                continue
        except Exception:
            pass
        if _track_idle_s(t) < 20:
            continue                     # just settled - give the steer thread room
        # Still actually full? The interrupted turn may have partially landed,
        # or a fork/rewind may have moved the session on. Re-read the live
        # figure rather than trusting the flag alone, and drop the flag if the
        # session no longer needs it - a re-queue must never become a
        # perpetual compaction loop on a small session.
        window = max(t.get("ctx_window") or 0, sessions._CTX_WINDOW)
        if t.get("ctx_tokens", 0) < 0.8 * window:
            sessions._mark_compact_pending(tid, False)
            continue

        def _run(track=t):
            try:
                log = ActionLog(track["run_dir"])
                log.log("note", "Nachhol-Verdichtung (die unterbrochene wird jetzt "
                                "im Leerlauf beendet).")
                sessions._maybe_compact(track, log, force=True)
            except Exception as e:
                print("pending-compaction retry failed for %s: %s" % (track["id"], e),
                      flush=True)
        threading.Thread(target=_run, daemon=True).start()


def start_zombie_reconciler(interval=20, min_idle_s=45, landed_check_every=6):
    """Reconcile status vs the live session CONTINUOUSLY (Paseo-parity), not just at
    boot. HelmDeck's `status` is a STORED field a thread must remember to clear; if
    that thread dies or races (a daemon restart mid-turn, overlapping Stop presses
    whose cancel didn't reset status), the card sits frozen at 'running' with no
    session and, because sweep_zombies only ran at startup, NOTHING noticed until the
    next restart. Paseo derives lifecycle from the live run and sweeps every 15s, so
    it self-heals; this background pass gives HelmDeck the same - a stuck card is
    caught within ~`interval`s. The idle guard skips the steer-start window so a
    legitimately-spawning turn is never falsely reaped. Idempotent.

    landed_check_every: check_landed_not_closed() runs one git ahead-count per
    open Review card, so it rides along every Nth tick instead of every tick -
    the mismatch it looks for is rare and never urgent-fast (the card is
    already merged, just not visibly closed)."""
    import threading
    def _loop():
        n = 0
        while True:
            time.sleep(interval)
            n += 1
            try:
                swept = sweep_zombies(min_idle_s=min_idle_s)
                if swept:
                    print("RECONCILER: bounced %d stuck running card(s): %s"
                          % (len(swept), ", ".join(swept)), flush=True)
            except Exception as e:
                print("zombie reconciler error: %s" % e, flush=True)
            try:
                sweep_pending_compaction()
            except Exception as e:
                print("pending-compaction sweep error: %s" % e, flush=True)
            if n % landed_check_every == 0:
                try:
                    check_landed_not_closed()
                except Exception as e:
                    print("landed-not-closed check error: %s" % e, flush=True)
    threading.Thread(target=_loop, daemon=True).start()


