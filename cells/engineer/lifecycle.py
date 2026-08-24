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
    turn is actually in flight (drivers.turn_active). Otherwise - once past the
    spawn window - the client gets 'needs_you', WITHOUT touching the stored
    value. A phantom spinner is thereby impossible no matter what any write race
    puts in the DB (invariant I2); the reconciler remains the healer of the
    stored value. Returns a copy when coercing, the original otherwise."""
    out = None
    if (t or {}).get("status") == "running":
        from spine.agent import drivers
        if not drivers.turn_active(t["id"]) and _track_idle_s(t) > PRESENT_IDLE_S:
            out = dict(t)
            out["status"] = "needs_you"
            out["status_derived"] = True   # marker: coerced at read, not stored
    out = _present_gxp(t, out)
    return out if out is not None else t


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
                # (owner decree 2026-08-21, docs/backlog/henry-exception-broker).
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
            if drivers.turn_active(t["id"]) or (min_idle_s and _track_idle_s(t) < min_idle_s):
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
                    if tt.get("status") != "running" or drivers.turn_active(tt["id"]):
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


def start_zombie_reconciler(interval=20, min_idle_s=45):
    """Reconcile status vs the live session CONTINUOUSLY (Paseo-parity), not just at
    boot. HelmDeck's `status` is a STORED field a thread must remember to clear; if
    that thread dies or races (a daemon restart mid-turn, overlapping Stop presses
    whose cancel didn't reset status), the card sits frozen at 'running' with no
    session and, because sweep_zombies only ran at startup, NOTHING noticed until the
    next restart. Paseo derives lifecycle from the live run and sweeps every 15s, so
    it self-heals; this background pass gives HelmDeck the same - a stuck card is
    caught within ~`interval`s. The idle guard skips the steer-start window so a
    legitimately-spawning turn is never falsely reaped. Idempotent."""
    import threading
    def _loop():
        while True:
            time.sleep(interval)
            try:
                swept = sweep_zombies(min_idle_s=min_idle_s)
                if swept:
                    print("RECONCILER: bounced %d stuck running card(s): %s"
                          % (len(swept), ", ".join(swept)), flush=True)
            except Exception as e:
                print("zombie reconciler error: %s" % e, flush=True)
    threading.Thread(target=_loop, daemon=True).start()


