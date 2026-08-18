# -*- coding: utf-8 -*-
"""The orchestrator - HelmDeck's Paseo half. A TRACK is a git branch, isolated in its own
worktree, bound to a RESUMABLE coding session (Claude Code --resume <session_id>). You select
a track and continue its context; history is never rebuilt. Each steer is recorded into the
flight recorder (actionlog) so what the session did stays reviewable.

Store: tracks.json (one list). Worktrees: <repo>/../helmdeck-worktrees/<repo-hash>/<branch>
(the 8-char repo hash proves OWNERSHIP by path shape - see _owned_worktree).
Permission mode is per-track and defaults to acceptEdits - the worktree is the blast-radius
control. Escalate a track to bypassPermissions only deliberately (owner decision)."""
import json, os, re, shutil, subprocess, time
from runs import REC

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "tracks.json")
DEFAULT_PERM = os.environ.get("HELMDECK_PERM", "acceptEdits")
CLAUDE = (os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")

import db as _db
from worktrees import reclaim_worktree, sweep_worktrees
from outcomes import extract_outcome, _record_outcome
from blockers import _blocker_text, blocker, manual_backlog, owner_blockers, waits_for_owner, MANUAL_MODES
from econ import _record_econ, _record_turn, _log_turn_end
from gitutil import (_git, _git_try, _branch_exists, is_git_repo, _current_branch, _checkpoint, _seed_worktree, _repo_hash, _owned_worktree, _git_state_broken, WORKTREE_DIRNAME)
from gitutil import _worktree_for, _base_ref, _worktree_of_branch
from trackstore import _load, _save, _save_track, _find, _slug, _unique_id, _mutate, _mutate_lock_for
from locks import _lock_for, _direct_lock_for, _uses_desktop_control, _desktop_lock, _bump_steer_epoch, _steer_epoch_current, _drain_steer_texts
from turnrunner import (_turn, _repair_question, _ask_repair_on, is_delivered, _settle_reply_compute, _settle_reply_apply, _settle_reply, _turn_checkpoint, resume_detached, _finish_turn, ZOMBIE_NOTE, RESUME_NOTE)
from lanemachine import (_gate, _merge_to_main, _autocommit, _pull_main_into_branch, dispatch_conflict_resolution, _classify_merge, _hook_kill_tree, _repo_hook, _say_card, move_lane, _is_dirty_block, park_and_retry_merge)
from dispatch import (new_track, _dispatch_failed, _start, _ensure_worktree, _start_inner, machine_policy, machine_root_ok, new_machine_task, new_direct_task, _start_machine, backfill_outcomes, _accept_machine, MACHINE_BRANCH, DIRECT_BRANCH, _OUTCOME_BACKFILL_REVIEWED)





import threading as _threading


_BG_HISTORY_CAP = 12       # terminal tasks kept for the app; running ones never dropped
BG_TERMINAL = ("completed", "failed", "canceled")


def bg_upsert(tid, uid, title=None, detail=None, status="running", result=None):
    """Fold ONE background-task LIFECYCLE event onto the track - Paseo's
    ProviderSubagentStore.apply(): a descriptor per task with an explicit status
    (running -> completed|failed|canceled), maintained at EVENT TIME by the pump,
    never reconstructed by transcript forensics. A launch upserts 'running', a
    <task-notification> 'completed'; reconcile_bg cancels survivors of a dead
    process. Terminal tasks are kept (bounded) so the app can show what the
    worker did and how it ended - clickable, like Paseo."""
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

# -- THE one legal write path for existing tracks (Paseo's one-owner principle) --
# Tracks are whole JSON dicts, and they used to be read+written from >=4 threads
# at once (steer, cancel, the reconciler, lane moves, answers, archive). Each
# writer did load -> edit its copy -> save: last-writer-wins, so a stale snapshot
# could resurrect 'running' and freeze a card (incident 2026-08-07 16:09, 164min).
# Paseo cannot have this bug because every lifecycle transition runs in ONE
# stream-event handler (agent-manager.ts ~3600): one owner, no competing writers.
# _mutate is that owner made explicit: a SHORT per-card mutation lock (NOT
# _lock_for - that one is held for a whole turn), a FRESH load, fn(t), save.
# Nothing outside _mutate may write status/gate_report/question/waiting_on/
# background on an existing track (invariant I1, pinned by test_status_store.py).


def flag_burn(tid, evidence):
    """The driver saw N identical consecutive tool calls (a likely loop that is
    burning tokens - drivers._burn_watch). NEVER auto-kill: a retry-with-backoff
    can be legitimate. Persist the signal First-Class (one owner, event time) and
    hand the JUDGEMENT to the PM, which knows the card + goal and escalates to
    the owner only if its own correction doesn't take."""
    box = {}

    def _set(tt):
        if tt.get("status") != "running":
            return False                 # the turn already ended - nothing to correct
        cur = dict(tt.get("burn") or {})
        cur.update(evidence)
        cur["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cur.setdefault("corrections", 0)
        tt["burn"] = cur
        box["ok"] = True
    t = _mutate(tid, _set)
    if t is None or not box.get("ok"):
        return
    try:
        from actionlog import ActionLog
        ActionLog(t["run_dir"]).log(
            "note", "⚠ Worker wiederholt denselben Schritt (%dx %s) - PM prueft"
            % (evidence.get("n", 0), evidence.get("name", "")))
    except Exception:
        pass
    import events
    events.emit("burn", tid, n=evidence.get("n"), name=evidence.get("name"))
    try:
        import pm
        pm.review_burn(tid)
    except Exception:
        pass







# Why a card is blocked on the human. One vocabulary, so a surface can rank or
# ICON the blocker instead of re-reading raw status/report fields:
#   question  - the worker asked and is parked on the answer
#   delivered - finished work, parked for your accept
#   review    - gate green, resting on Review for your accept
#   gate      - the quality gate came back red
#   conflict  - the branch cannot land (merge conflict / blocked merge)
#   failed    - dispatch died, a turn was swept, or you bounced it back
BLOCKER_REASONS = ("question", "delivered", "review", "gate", "conflict", "failed")










LANES = ("backlog", "working", "review", "done")

# -- the lane/gate flow, AS DATA -----------------------------------------
# This lives here, next to move_lane(), because move_lane IS this machine: every
# node and edge below is a branch of it. It used to be re-typed by hand in
# server.py's /loop/map handler, which is how that copy came to describe a board
# nobody had shipped for months.
#
# `kind` is the load-bearing column:
#   fixed  - harness law (CLAUDE.md). Not configurable, shown read-only.
#   policy - data. `settings` names the exact key that governs the node, so the
#            UI can link a node straight to the knob instead of describing it.
#   why    - why it is fixed / what exactly is adjustable. Same argument as
#            loop_state.LOOP_STATES: the module that decides a node is fixed owns
#            the reason. Without it the map could only draw a padlock, which
#            reads as "arbitrarily locked" rather than "deliberately fixed".
#
# Every lane's NAME is renameable (policy.lane_labels) regardless of `kind` -
# that is a label, not a rule, which is why flow() resolves it for the UI.
LANE_FLOW = {
    "nodes": [
        {"key": "backlog", "default_label": "Backlog", "kind": "policy",
         "settings": ["policy.auto_dispatch_priority", "capacity.wip_limit"],
         "instruction": "Karten warten. Ab der Priorität in policy.auto_dispatch_priority "
                        "starten sie sich selbst - aber nur im WIP-Rahmen (capacity.wip_limit).",
         "why": "Du entscheidest, was sich von selbst startet: ab welcher Priorität und "
                "wie viele Karten gleichzeitig laufen dürfen."},
        {"key": "working", "default_label": "In Arbeit", "kind": "fixed",
         "settings": [],
         "instruction": "Ein Agent arbeitet in einem ISOLIERTEN git-worktree (Harness-Gesetz: "
                        "worktree-Isolation). Jeder Turn ist gemessen (Kosten/Token -> Audit).",
         "why": "Fix, weil ohne Worktree-Isolation zwei Karten sich gegenseitig "
                "überschreiben und ohne Messung kein Ergebnis zurechenbar wäre."},
        {"key": "review", "default_label": "Review", "kind": "fixed",
         "settings": [],
         "instruction": "Beim Eintritt läuft der Quality-Gate (gate-before-review, FIX). "
                        "Rot -> die Karte wird zurückgebounced mit sichtbarem Grund.",
         "why": "Fix, weil sonst ungeprüfte Arbeit zur Abnahme käme - der Gate ist "
                "die einzige Stelle, die 'grün' beweist statt behauptet."},
        {"key": "done", "default_label": "Fertig", "kind": "policy",
         "settings": ["policy.auto_accept_green"],
         "instruction": "Merge + Deploy. Nichts merged sich selbst - außer "
                        "policy.auto_accept_green ist an. Der Prozess-Chain rückt "
                        "einen Schritt vor.",
         "why": "Standard ist: nichts merged sich selbst. Ob grüne Karten automatisch "
                "durchgehen, entscheidest du mit policy.auto_accept_green."},
    ],
    "edges": [
        {"from": "backlog", "to": "working", "verb": "dispatch", "kind": "policy",
         "settings": ["policy.auto_dispatch_priority", "policy.auto_dispatch_modes"],
         "instruction": "Der Agent wird gestartet (idempotent - eine laufende Karte "
                        "nimmt ihre Position wieder auf)."},
        {"from": "working", "to": "review", "verb": "submit", "kind": "fixed",
         "settings": [],
         "instruction": "Aufräumen + Commit, dann der Gate. Danach wird der Merge nur "
                        "KLASSIFIZIERT (dry-run) - die Karte bleibt mit dem Befund auf Review."},
        {"from": "review", "to": "working", "verb": "bounce", "kind": "fixed",
         "settings": [],
         "instruction": "Der Mensch schickt die Karte zurück - als 'bounce' in der "
                        "Ökonomie verbucht."},
        {"from": "review", "to": "done", "verb": "accept", "kind": "policy",
         "settings": ["policy.auto_accept_green"],
         "instruction": "Der bewusste Zug nach Done merged wirklich und fährt den "
                        "Deploy-Hook. Idempotent: eine gelandete Karte wird nie erneut "
                        "gegatet oder gemerged."},
    ],
    "gate": {"key": "gate", "default_label": "Quality Gate", "kind": "fixed",
             "between": ["working", "review"], "settings": [],
             "instruction": "Gate-before-review ist ein fixes Harness-Gesetz: kein Review "
                            "ohne bestandenen Gate. Das Ergebnis geht append-only ins "
                            "Audit-Log.",
             "why": "Fix, weil eine Abnahme sonst nur eine Meinung wäre. Das Ergebnis "
                    "wird append-only protokolliert und kann nicht nachträglich "
                    "geschönt werden."},
}


def flow(lane_labels=None):
    """The lane/gate machine as data, with the owner's lane renames applied.

    `label` resolves policy.lane_labels over the built-in default, so the UI never
    has to know that renaming is a thing - it just renders `label`."""
    ll = lane_labels or {}
    out = {"nodes": [], "edges": [dict(e) for e in LANE_FLOW["edges"]],
           "gate": dict(LANE_FLOW["gate"])}
    # file:line for every node, read out of THIS file - see loop_state._decl_lines
    # for why it is derived rather than written down.
    try:
        import sys as _sys
        _tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
        if _tools not in _sys.path:
            _sys.path.insert(0, _tools)
        from loop_state import _decl_lines
        src = _decl_lines([n["key"] for n in LANE_FLOW["nodes"]] + [LANE_FLOW["gate"]["key"]],
                          path=os.path.abspath(__file__), rel="daemon/sessions.py")
    except Exception:                                        # noqa: BLE001
        src = {}
    for n in LANE_FLOW["nodes"]:
        n = dict(n)
        n["label"] = ll.get(n["key"], n["default_label"])
        n["source"] = src.get(n["key"], "daemon/sessions.py")
        out["nodes"].append(n)
    out["gate"]["label"] = out["gate"]["default_label"]
    out["gate"]["source"] = src.get(LANE_FLOW["gate"]["key"], "daemon/sessions.py")
    return out


# -- public API ----------------------------------------------------------

def list_tracks():
    return _load()

def get_track(tid):
    return _find(_load(), tid)



MODES = ("plan", "acceptEdits", "default", "bypassPermissions")

def _pending_context(t):
    """Review/merge/gate checks run OUTSIDE the agent session (daemon-side, only
    in the actionlog), so the worker never sees a merge conflict or a failed
    gate - it's in the woven chat view but not the session. When the owner steers
    to fix one ("resolve the conflict"), prepend the actual report so the worker
    isn't blind. Empty string when nothing is pending."""
    parts = []
    # Repo hooks (preview/deploy) ALSO run daemon-side, outside the session -
    # same blind spot as gate/merge below. Incident (2026-08-15): a fast-track
    # deploy hook actually SUCCEEDED ("DEPLOY HOOK OK"), but its output tail
    # happened to contain a harmless "(23) Failed writing body" curl artifact;
    # the owner read that as a failure and told the worker "Deploy hook
    # failed", and the worker - with no way to check `t["deploy_hook"]` itself
    # (that field existed on the track the whole time, just never surfaced
    # here) - had to trust the owner's framing and chased a phantom infra bug.
    # steer() clears these after this call, so each hook result is told to the
    # worker exactly once (on the next steer), never repeated on later ones.
    for hook_kind in ("deploy_hook", "preview_hook"):
        dh = t.get(hook_kind)
        if dh:
            parts.append("%s HOOK %s (ran outside this session, daemon-side):\n%s" % (
                hook_kind.split("_")[0].upper(), "OK" if dh.get("ok") else "FAILED",
                str(dh.get("tail") or "")[:800]))
    gr = t.get("gate_report")
    if t.get("gate_failed") and gr:
        parts.append("Quality gate FAILED:\n" + ("\n".join(gr) if isinstance(gr, list) else str(gr)))
    elif isinstance(gr, list) and any(RESUME_NOTE in x or ZOMBIE_NOTE in x for x in gr):
        # A zombie-sweep/Stop interrupt (no gate involved) also stashes its note
        # in gate_report - the only channel _pending_context reads. Without this
        # branch a bare "continue" after an interrupt resumes BLIND: the worker
        # never learns its turn was cut, only that a new instruction arrived.
        parts.append("Note from the desktop since your last turn:\n" + "\n".join(gr))
    # Thrash guard: if this card has failed its gate several times in a row, a
    # naive rewrite-and-retry keeps burning the budget (SageRoute's rewrite/retest
    # trap). Tell the worker to stop rewriting and change approach - break the loop.
    import events, turnopts
    fails = events.consecutive_gate_fails(t["id"])
    if fails >= turnopts.ESCALATE_TURNS:
        parts.append("This card has FAILED its quality gate %d times in a row. Do "
                     "NOT just rewrite and resubmit - that pattern has not worked. "
                     "Step back: re-examine the assumption behind the fix, or say "
                     "plainly what is blocking you and stop." % fails)
    rep = t.get("review_report") or t.get("merge_report")
    if rep and (t.get("merge_kind") == "conflict" or t.get("merge_failed") or t.get("gate_failed")):
        parts.append("Review/merge check reported:\n" + str(rep))
    if not parts:
        return ""
    return ("[Desktop context since your last turn - the review/merge/gate ran "
            "outside this session, so you did not see this. Use it if the "
            "instruction refers to it:]\n\n" + "\n\n".join(parts) + "\n\n---\n\n")


# -- AUTO-COMPACT-AND-CONTINUE (Paseo parity: auto compaction at the brim) ----
# A persistent claude -p session fills over turns. Left alone it dead-ends the
# worker ("mein Kontext ist am Ende") and, worse, the NEXT resume of a full
# session rotates to a FRESH .jsonl carrying none of the prior conversation -
# the whole chat "disappears" from the card. So when a turn leaves the context
# near the brim we run ONE bounded /compact on the same session: it summarises
# itself in place, the next steer keeps headroom, the thread stays continuous.
_COMPACT_AT_TOKENS = 160_000     # ~80% of a 200k window - the high-water mark
_CTX_WINDOW = 200_000

# RE-ENABLED 2026-08-14 (was disabled 2026-08-10 as a0853d4; see debt.py
# [auto-compaction-disabled] history). BOTH things blamed for the "/compact
# corruption" were already root-caused and fixed by OTHER commits before this
# one was reinstated - the corruption was never actually /compact:
#   1. "shrink check read summed usage, not compacted context" - true of this
#      function's original Aug 7 form, but ctx_tokens has read the last-call-
#      only usage (meta.ctx_usage, Paseo-style, see _record_econ above) since
#      66930bb (2026-08-08 - TWO DAYS before the disable commit). The shrink
#      check below was already comparing against the right number.
#   2. "a later --resume silently started a FRESH session" - the actual cause
#      was the claude.cmd shim eating the trailing `--resume <sid>` arg when
#      exec'd via `cmd /s /c` (ANY --resume could silently miss, compaction or
#      not). Fixed by ea09780 (2026-08-10, the SAME DAY, 5h after the disable
#      commit): drivers now spawn the real exe as an argv list, never the
#      shim. The incident that got compaction blamed (Fix AI-Kosten-Tracking,
#      2026-08-10) is fully explained by the shim bug alone.
# accept-and-rebind (_finish_turn, Weg B) stays as the safety net for ANY
# unresumable session (idle eviction, a killed process, a genuinely corrupt
# tip) - compaction was never the only way to hit that path. This function
# stays self-verifying (probes once, learns True/False) so a CLI that doesn't
# honor /compact costs nothing per turn.
_autocompact_supported = None    # None=unprobed, True/False learned from first /compact


def _maybe_compact(t, log):
    """Compact the session in place if the live context crossed the high-water
    mark. Self-verifying: /compact must actually SHRINK the context (ctx_tokens
    is the last-call-only reading, not summed - a real compaction is visible
    there). If it does not (an older CLI that treats the slash line as literal
    input), we learn that once and stop - no no-op cost, no polluting the
    conversation every turn. Returns the fresh track (or None if nothing was
    done)."""
    global _autocompact_supported
    if _autocompact_supported is False:
        return None
    ctx = t.get("ctx_tokens", 0)
    # high-water mark scales with the session's DERIVED window (ctx_window is
    # runtime evidence, incl. the proof-beyond-200k 1M inference above) - the
    # fixed 160k mark made a 1M-tier session "compact" at a real ~16% fill,
    # burning a full-context /compact turn while the CLI (which knows its real
    # window) rightly saw no reason to shrink anything.
    window = max(t.get("ctx_window") or 0, _CTX_WINDOW)
    if ctx < 0.8 * window or not t.get("session_id"):
        return None
    pct = min(100, round(ctx / window * 100))
    log.log("note", "AUTO-COMPACT: Kontext bei %d%% (~%dk) - ich verdichte die Session, "
            "damit der Verlauf erhalten bleibt und es weitergeht." % (pct, round(ctx / 1000)))
    # SHORT watchdog, not the driver's default 900s: incident (2026-08-15) - a
    # /compact turn finished writing its own transcript (the session showed
    # "Compacted") but the underlying CLI process never exited, so this call
    # sat blocked for the full 15 minutes before the default idle-timeout
    # finally killed it - and every OTHER post-turn step (fast-track ship
    # included) waits on this call returning. Compact is a small, bounded
    # operation; 3 minutes of total silence is already generous slack above
    # every observed real compaction, and failing fast here just falls
    # through to the existing self-verifying "CLI doesn't honor /compact"
    # path below - never a hard failure, just a faster one.
    sid, _out, meta = _turn(t, "/compact", idle_timeout=180)

    def _apply(tt):
        if sid and tt.get("session_id") and sid != tt["session_id"]:
            chain = [s for s in (tt.get("session_chain") or []) if s != tt["session_id"]]
            chain.append(tt["session_id"])
            tt["session_chain"] = chain[-6:]
            tt["session_id"] = sid
        _record_econ(tt, meta)            # measured economics: the compact turn is billed too
    t = _mutate(t["id"], _apply) or t
    before = ctx
    after = t.get("ctx_tokens", before)
    if after <= before * 0.75:            # a real compaction frees a big chunk
        _autocompact_supported = True
        log.log("note", "AUTO-COMPACT ok: Kontext jetzt ~%dk - Verlauf verdichtet, es geht "
                "ohne Unterbrechung weiter." % round(after / 1000))
    else:
        _autocompact_supported = False
        log.log("note", "AUTO-COMPACT: diese CLI honoriert /compact nicht - fuer diese "
                "Session abgeschaltet. Kontext-Meter + Nudge bleiben aktiv.")
    return t


def steer(tid, text, perm=None, actor="owner", source="you",
          model="", thinking="", attachments=None, mode=None):
    """Continue the track's session (resume - context preserved, NO history rebuild).
    model/thinking/attachments come from the chat composer: model is resolved
    through the whitelist (incl. Auto), attachments are saved into the worktree
    for the agent to read, and the augmented prompt (thinking directive +
    attachment refs) is what the driver sees - but the AUDIT logs the human's
    original text, not the augmentation."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if not t.get("session_id"):
        _start(tid)                      # steering a backlog card dispatches it first
        tracks = _load(); t = _find(tracks, tid)
    import events, turnopts, drivers
    events.emit("touch", tid, touch="steer", actor=actor)
    was_bounced = t.get("status") == "bounced"   # routing signal, read BEFORE 'running'
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    # INTERRUPT-AND-REPLACE: if a turn is live, soft-interrupt it and start THIS
    # instruction now (Paseo's replaceAgentRun), instead of queuing behind it on
    # the per-card lock. drivers.cancel is the cooperative interrupt (~2s ack,
    # the process stays alive, the session resumes), so the interrupted turn
    # releases the lock and this steer runs immediately after. A burst collapses
    # to last-wins via the epoch: only the newest steer survives the bail below.
    my_epoch = _bump_steer_epoch(tid, text)
    if drivers.turn_active(tid):
        log.log("note", "⏹ neue Anweisung ersetzt den laufenden Turn (Interrupt).")
        try:
            drivers.cancel(tid)
        except Exception as _ie:
            log.log("note", "Interrupt fehlgeschlagen: %s" % str(_ie)[:150])
    if _steer_epoch_current(tid) != my_epoch:
        # a newer steer superseded this one. AUDIT the command anyway and hand it
        # to the winner via the pending list - bundled, never silently dropped.
        log.log("steer", text)
        log.log("note", "⏫ mit der nächsten Anweisung gebündelt (ein Turn).")
        return t
    _burst = _drain_steer_texts(tid)
    if len(_burst) > 1:
        text = "\n\n".join(_burst)        # the winner carries the WHOLE burst
        log.log("note", "%d schnelle Anweisungen zu einem Turn gebündelt." % len(_burst))
    if source and source != "you":
        log.log("note", "DELEGATED by %s -> this card's worker" % source)
    log.log("steer", text)               # audit the human's words, not the augmented prompt
    log.log("turn", "Turn gestartet", event="started")
    # the card is moving again, so whatever we last pushed about it is stale -
    # the next notification is news and must not be swallowed by the dedup
    import notify
    notify.clear_dedup(tid)

    def _begin(tt):
        # A card on Review that's being resolved (e.g. steering the agent to fix
        # a conflict) STAYS on Review - steering no longer demotes it to Working.
        # Any other lane (backlog/done) still means "back to active work".
        if tt["lane"] not in ("working", "review"):
            events.emit("lane", tid, frm=tt["lane"], to="working")
            tt["lane"] = "working"
        # Any steer supersedes a pending question - the owner either answered it
        # through the buttons (this IS that steer) or decided something else
        # instead. Clearing here, not at turn end, means the panel disappears
        # the moment the turn starts rather than lingering for the whole turn.
        tt.pop("question", None)
        tt["status"] = "running"
    t = _mutate(tid, _begin) or t
    paths = turnopts.save_attachments(t.get("worktree") or t["run_dir"], attachments)
    # Auto routing sees the card's facts INCLUDING turn count - a card that's
    # already dragged on escalates to the strong model (cheap "escalate on
    # evidence"). An explicit model from the composer still wins.
    cli_model, _ = turnopts.resolve_model(model, text, bool(paths),
        signals={"value": t.get("value"), "priority": t.get("priority"), "turns": t.get("turns"),
                 "failed": was_bounced or bool(t.get("gate_failed")),
                 "fails": events.consecutive_gate_fails(t["id"])})
    # Hand the worker the daemon-side context it never saw (a merge conflict, a
    # failed gate) so a steer like "resolve the conflict" isn't blind. The AUDIT
    # above still logs the human's original text, not this augmentation.
    prompt = _pending_context(t) + turnopts.augment_prompt(text, thinking, paths)
    # Consumed: pop the hook results now so they're told to the worker exactly
    # ONCE (this steer), not repeated on every later unrelated one.
    if t.get("deploy_hook") or t.get("preview_hook"):
        _mutate(tid, lambda tt: (tt.pop("deploy_hook", None), tt.pop("preview_hook", None)))
    perm_override = mode if mode in MODES else None   # whitelist - no arbitrary mode
    # SELF-HEAL a missing OR broken worktree before spawning into it. The tree
    # is regenerable from the branch; without the isdir half, a reclaimed/
    # hand-deleted/never-created tree made EVERY steer die with WinError 267
    # (spawn cwd invalid) - a dead-end the owner cannot steer out of, on a
    # card that is otherwise fine. isdir alone is not enough, though: an
    # existing-but-never-`git worktree add`'d directory (interrupted add,
    # stray mkdir) also passes isdir, so a steer reused it as-is and dispatched
    # into a folder with no .git - the same class _ensure_worktree now guards
    # against internally, checked again here so the CALLER's decision whether
    # to even invoke it doesn't reintroduce the bug one level up.
    if (not t.get("machine") and t.get("branch")
            and (not os.path.isdir(t.get("worktree") or "")
                 or _git_state_broken(t["worktree"]))):
        try:
            wt_new = _ensure_worktree(t)
            t["worktree"] = wt_new
            _mutate(tid, lambda tt: tt.__setitem__("worktree", wt_new))
            log.log("note", "WORKTREE neu erzeugt (%s) - fehlte oder war nie initialisiert, Branch haelt den Stand." % wt_new)
        except Exception as _we:
            log.log("note", "WORKTREE fehlt und Neuaufbau schlug fehl: %s" % str(_we)[:200])
    try:
        sid, result, meta = _turn(t, prompt, model=cli_model, perm=perm_override)
    except BaseException as e:
        # The steer thread must NEVER die leaving 'running' behind - that flag
        # is a stored promise only this thread would clear, and a card frozen
        # on it shows an eternal spinner (Paseo avoids the whole class by
        # deriving lifecycle from the live run; the reconciler is our derive
        # loop, this is the fast path). _mutate loads fresh under the card's
        # mutation lock, so a concurrent cancel's write can't be resurrected.
        rel = {}

        def _release(tt):
            if tt.get("status") != "running":
                return False             # a concurrent cancel already settled it
            tt["status"] = "needs_you"
            rel["did"] = True
        _mutate(tid, _release)
        if rel.get("did"):
            log.log("note", "turn ABGEBROCHEN (%s) - Karte freigegeben, steuern setzt fort."
                    % str(e)[:160])
        log.log("turn", "Turn fehlgeschlagen", event="failed", error=str(e)[:500])
        raise
    # REPLACE HANDOFF: this turn was soft-interrupted to make room for a NEWER
    # steer (the epoch moved and the driver returned the cancelled sentinel).
    # Don't settle - the newer steer owns the card and will finish it. Settling
    # here would flap the status mid-replace.
    if _steer_epoch_current(tid) != my_epoch and "cancelled" in (result or "").lower():
        log.log("turn", "Turn ersetzt", event="canceled")
        return t
    # ONE atomic end-of-turn commit: session rotation, turn count, reply/
    # question/waiting_on, status, economics - all under the mutation lock.
    t, reason = _finish_turn(tid, sid, result, meta, log)
    # Auto-compact-and-continue: if this turn left the context near the brim,
    # verdict the session NOW (one bounded /compact on the same session) so the
    # next steer keeps headroom and the thread stays continuous - never a
    # dead-end or a fresh-session overflow. Best-effort, self-verifying.
    try:
        t = _maybe_compact(t, log) or t
    except Exception as _e:
        log.log("note", "auto-compact skipped: %s" % str(_e)[:200])
    import notify
    notify.card_event(t, reason)
    # FAST-TRACK = ship EVERY finished turn, hands-free. The flag used to fire
    # only when the OWNER dragged the card to Review - which is exactly the
    # manual push fast-track exists to remove ("man muss immer noch schieben,
    # also kein Vorteil"). Now a fast_track card SUBMITS ITSELF when its turn
    # ends: gate -> merge -> deploy hook run in the background, and the change
    # is testable without touching the board. The gate still guards (red gate
    # bounces back with the report), a pending question still parks the card
    # (the owner's decision comes first), and a turn that produced NOTHING new
    # to ship is skipped so a chat-only turn can't close the card.
    _maybe_fast_track_ship(t, log)
    return t


def _maybe_fast_track_ship(t, log):
    """Fast-track = every finished turn is DEPLOYED for testing while the card
    STAYS exactly where it is (owner: "keep the card in the same state but
    still deploy everything so I can test - not automatically review/done").
    So: background gate -> merge -> deploy, NO lane change, NO status change,
    the card never closes and the owner keeps steering the same session. The
    gate still guards main (red = no deploy, reasons in the chat); the accept
    flow on Review stays the human judgement it always was."""
    if not (t.get("fast_track") and not t.get("machine")
            and t.get("status") == "needs_you" and not t.get("question")):
        return
    wt = t.get("worktree") or ""
    if not os.path.isdir(wt):
        return
    # anything to ship? dirty tree OR branch commits not yet in the integration
    rc, dirty, _ = _git_try(wt, "status", "--porcelain")
    ahead = False
    integ = _current_branch(t.get("repo") or "")
    if integ and t.get("branch"):
        ahead = _git_try(t["repo"], "merge-base", "--is-ancestor",
                         t["branch"], integ)[0] != 0
    if not ((rc == 0 and dirty) or ahead):
        return                          # chat-only turn - nothing to deploy
    tid = t["id"]
    log.log("note", "FAST-TRACK: Turn fertig -> Gate + Merge + Deploy im Hintergrund. "
            "Die Karte bleibt in Arbeit.")

    def _ship():
        from actionlog import ActionLog
        import events
        lg = ActionLog(t["run_dir"])
        try:
            if _autocommit(t) == "markers":
                lg.log("note", "FAST-TRACK: offene Konfliktmarkierungen - nicht deployed.")
                return
            ok, problems = _gate(t)
            events.emit("gate", tid, ok=ok, source="fast-track")
            if not ok:
                lg.log("note", "FAST-TRACK: Gate rot - NICHT deployed, Karte bleibt "
                       "in Arbeit. Grund:\n%s" % "\n".join(problems)[:500])
                return
            accept_ok, kind, msg = _merge_to_main(t)
            events.emit("merge", tid, ok=bool(accept_ok), outcome=kind,
                        detail="fast-track: " + (msg or "")[:200])
            if not accept_ok:
                lg.log("note", "FAST-TRACK: Merge nicht moeglich (%s) - nicht deployed. %s"
                       % (kind, (msg or "")[:300]))
                return
            hk = _repo_hook(t, "deploy")   # None = no hook configured
            # PERSIST the hook outcome - _repo_hook ran on THIS thread's local
            # `t` copy (a subprocess call, kept outside the mutation lock), the
            # same reason move_lane's _land() persists it post-hook. Without
            # this the field only ever lived in this thread's dict and never
            # reached the DB, so _pending_context's next-steer surfacing of
            # deploy_hook (added for exactly this failure mode) was silently a
            # no-op for every fast-track ship - the worker still never saw it.
            _hooks = {k: t[k] for k in ("preview_hook", "deploy_hook") if k in t}
            if _hooks:
                _mutate(tid, lambda tt: tt.update(_hooks))
            lg.log("note", "FAST-TRACK deployed (%s)%s - teste auf dem Handy; die Karte "
                   "bleibt in Arbeit, steuern geht einfach weiter."
                   % (kind, " · ACHTUNG: Deploy-Hook rot" if hk is False else ""))
            if hk is False:
                _try_auto_fix_deploy(t, lg)
            elif hk is True:
                _mutate(tid, lambda tt: tt.pop("deploy_fail_streak", None))
        except Exception as e:
            try:
                lg.log("note", "FAST-TRACK fehlgeschlagen: %s" % str(e)[:250])
            except Exception:
                pass
    _threading.Thread(target=_ship, daemon=True).start()


_DEPLOY_FIX_CAP = 3   # matches turnopts.ESCALATE_TURNS - the gate thrash-guard's cap


def _try_auto_fix_deploy(t, lg):
    """A fast-track deploy hook failure (in practice: a native build broke,
    like a Gradle task blowing up) already landed on main by the time we see
    it - the merge already happened, only the build/distribute step failed.
    Left alone, that just sits as a red note until the owner happens to
    notice - unattended is the whole point of fast-track, so make the repair
    unattended too: feed the worker the actual error and let it try to fix it,
    same as it already would for a red gate. Bounded (never more than
    _DEPLOY_FIX_CAP attempts in a row) so a genuinely, persistently broken
    build doesn't burn turns forever without the owner ever finding out -
    mirrors the existing gate thrash-guard in _pending_context."""
    tid = t["id"]
    streak = (t.get("deploy_fail_streak") or 0) + 1
    _mutate(tid, lambda tt: tt.__setitem__("deploy_fail_streak", streak))
    if streak > _DEPLOY_FIX_CAP:
        lg.log("note", "FAST-TRACK: Deploy-Hook %dx in Folge rot - kein automatischer "
               "Reparaturversuch mehr, wartet auf dich." % (streak - 1))
        return
    tail = ((t.get("deploy_hook") or {}).get("tail") or "")[:1200]
    instr = ("FAST-TRACK deploy hook FAILED after your last change was already merged "
             "to main (repair attempt %d/%d - stops auto-retrying past this). This "
             "usually means a native build broke. Actual error:\n\n%s\n\nInvestigate and "
             "fix it. Your next turn's fast-track ship retries the deploy automatically "
             "once you've committed a fix." % (streak, _DEPLOY_FIX_CAP, tail))
    lg.log("note", "FAST-TRACK: Deploy-Hook rot - Worker bekommt den Fehler automatisch "
           "zur Reparatur (Versuch %d/%d)." % (streak, _DEPLOY_FIX_CAP))
    steer(tid, instr, actor="fast-track", source="fast-track-deploy-fix")


def answer_question(tid, answers, request_id="", actor="owner"):
    """Answer the worker's pending multiple-choice question (Phase 2.4).

    The owner's pick becomes the next steer, so the SAME session continues via
    `--resume` with the decision in hand - the turn is resumed, not restarted,
    and the card never parks on a question nobody could answer.

    `request_id` is the optimistic-concurrency guard: the app sends back the id
    it rendered, so a stale panel (the worker asked again, or another device
    already answered) is rejected instead of steering the worker with an answer
    to a question it has moved past.

    The answer is either one of the worker's offered labels or the owner's own
    free text (the Paseo 'Other' escape hatch) - see ask.validate_answers. Free
    text is no injection risk: the owner is authenticated and could type the
    same thing through /steer anyway."""
    import ask
    # CLAIM the question atomically via _mutate (the per-card MUTATION lock,
    # deliberately NOT the turn lock - answering ends in a steer, whose turn
    # holds that one). Answering is backgrounded by the server, so two quick
    # taps are two threads: without this both could read the same pending
    # question and steer the worker twice with contradictory decisions.
    # Clearing it here - not leaving it to steer() - makes the second caller
    # lose deterministically. A raise inside fn aborts before the save, so an
    # invalid answer leaves the panel standing.
    box = {}

    def _claim(t):
        q = t.get("question")
        if not q:
            raise RuntimeError("no pending question on this card")
        if request_id and request_id != q.get("id"):
            raise RuntimeError("this question was already answered or replaced")
        picks, err = ask.validate_answers(q, answers)
        if err:
            raise ValueError(err)          # invalid: leave the panel standing
        box["q"], box["picks"] = q, picks
        t.pop("question", None)
    t = _mutate(tid, _claim)
    if t is None:
        raise RuntimeError("no such track: " + tid)
    q, picks = box["q"], box["picks"]
    from actionlog import ActionLog
    ActionLog(t["run_dir"]).log("note", ask.answer_note(picks))
    import events
    events.emit("answer", tid, actor=actor, qkind=q.get("kind"),
                picks=[ask._pick_parts(p) for p in picks])
    # steer() clears the pending question itself and runs the turn under the
    # per-card lock, so the worker continues with the decision.
    return steer(tid, ask.answer_prompt(picks), actor=actor, source="answer")


# -- AUTO-CONTINUE on background completion (Paseo adoption, Phase 2.5) -------
# A turn that ends while a worker-launched background task is still running used
# to park the card in needs_you limbo: the owner had nothing to do, and nothing
# would ever wake the card again - the finished build just sat there. Now the
# harness watches for the task to finish and continues the card ITSELF.
#
# The completion signal is the runtime's own: Claude Code injects a
# <task-notification> carrying the originating tool-use-id when a background
# task ends, and claude_sessions.background_wait() reads exactly that. So this
# fires on positive evidence of completion, never on a timer - and when the
# evidence never arrives the card simply keeps its honest "waiting on a
# background task" cue instead of being auto-steered on a guess.

_BG_POLL_S = 20.0            # how often the watcher re-reads the transcripts
_BG_MAX_WAIT_S = 6 * 3600    # stop watching a task that never reports (6h)
_bg_watcher_started = False


def _bg_continue_on(t):
    """policy.auto_continue (default on). Off => the card keeps the cue but is
    never steered automatically."""
    import events
    pol = events.settings().get("policy") or {}
    return bool(pol.get("auto_continue", True))


def _continue_prompt():
    """Tagged as harness-injected so the card feed renders it as a system note
    instead of a message the owner appears to have typed (ask.harness_msg)."""
    import ask
    return ask.harness_msg(
        "background-done",
        "Dein Hintergrund-Task ist fertig - das hier ist ein automatischer "
        "Hinweis des Harness, keine Nachricht vom Owner.\n"
        "Hol dir seine Ausgabe (BashOutput bzw. das Task-Ergebnis) und arbeite "
        "genau dort weiter, wo du auf ihn gewartet hast. Wenn die Ausgabe zeigt, "
        "dass etwas fehlgeschlagen ist, behebe es oder sag klar, was der Owner "
        "entscheiden muss.")


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
    for t in _load():
        if t.get("waiting_on") != "background" or t.get("status") == "running":
            continue
        # ORPHAN reconciliation (finishAll): a background task is a child of the
        # worker process. If this daemon holds NO live session for the card (a
        # restart wiped the registry, or the worker crashed) and no turn is in
        # flight, the tasks died with their parent - flip the still-running ones
        # to 'canceled' NOW instead of parking the card for the full 6h. The
        # continue-on-clear path below then resumes the worker to pick up.
        import drivers
        if not drivers.has_session(t["id"]) and not drivers.turn_active(t["id"]):
            if reconcile_bg(t["id"]):
                t = _find(_load(), t["id"]) or t
        since = ((t.get("background") or {}).get("since")
                 or _epoch_of(t.get("updated")) or time.time())
        if time.time() - since > _BG_MAX_WAIT_S:
            def _giveup(tt):
                if tt.get("waiting_on") != "background":
                    return False
                tt["waiting_on"] = "you"     # give up watching, hand it back
                tt.pop("background", None)
            _mutate(t["id"], _giveup)
            continue
        import claude_sessions
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
        _mutate(t["id"], _claim)
        if not claim.get("ok"):
            continue
        from actionlog import ActionLog
        # steer only ACTIVE work, and only if the owner allows auto-continue;
        # otherwise the cue is cleared (above) and the card honestly waits on
        # the owner instead of on a task that has already reported.
        if t.get("lane") not in ("working", "review") or not _bg_continue_on(t):
            ActionLog(t["run_dir"]).log(
                "note", "Hintergrund-Task fertig - Karte wartet auf dich "
                "(kein Auto-Continue)")
            continue
        ActionLog(t["run_dir"]).log(
            "note", "Hintergrund-Task fertig - Karte laeuft automatisch weiter")
        import events
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


def adopt_session(session_id, cwd, mode="continue", first="", actor="owner"):
    """Bring an existing Claude Code session (from ~/.claude) onto the board.
      mode="continue": wrap it IN PLACE as a card - no new branch/worktree; the
        card's steer resumes the exact session (`claude --resume`) in its own cwd.
      mode="fork": open a NEW branch + worktree from that repo with a fresh
        session, seeded with the original's starting request (source untouched).
    No git commit is made either way - tracking is the card's audit trail; a fork
    creates a branch pointer, real commits come only when the agent commits code."""
    import events
    cwd = os.path.abspath(cwd)
    if not os.path.isdir(cwd):
        raise RuntimeError("session working dir not found: " + cwd)
    # one session = one card (the Paseo invariant). Two cards sharing a
    # session id would both mirror the same ever-growing conversation. The
    # CHAIN counts too: a rotated-away session is that card's own history
    # (read_transcript_live renders it); adopting it would spawn a second card
    # writing into the middle of another card's conversation. lane=done stays
    # exempt (deliberate: finished work releases its session for re-adoption) -
    # the UI still LINKS those to the owning card instead, which is the better
    # flow (open the card, steer it), but the API keeps the escape hatch.
    for ex in _load():
        if ex.get("lane") == "done":
            continue
        if session_id == ex.get("session_id") \
                or session_id in (ex.get("session_chain") or []):
            raise RuntimeError("session already on the board as card " + ex["id"])
    short = (session_id or "sess")[:8]

    if mode == "fork":
        task = ("Fork of a prior Claude Code session in this repo. Original "
                "starting request:\n\n" + (first or "(unknown)")
                + "\n\nContinue that line of work here.")
        t = new_track(cwd, "fork-" + short, task, lane="backlog", actor=actor)
        def _stamp(tt):
            tt["forked_from"] = session_id
        return _mutate(t["id"], _stamp) or t

    # continue: a card that IS the existing session, running in its own cwd
    tid = _unique_id("adopt-" + short)
    run_dir = os.path.join(REC, tid); os.makedirs(run_dir, exist_ok=True)
    branch = _current_branch(cwd) or "(no git)"
    t = {"id": tid, "repo": cwd, "branch": branch, "worktree": cwd,
         "task": (first or "Continued Claude Code session")[:400],
         "client": "", "session_id": session_id, "perm": DEFAULT_PERM,
         "lane": "working", "status": "needs_you", "turns": 0, "run_dir": run_dir,
         "last_reply": "", "value": events.settings()["value_per_card"],
         "driver": "claude", "priority": "medium", "due": "", "rank": None,
         "model": "", "attachments": [], "adopted": True,
         # remembered so the first steer forks AWAY from the source session
         # instead of writing into the desktop's live conversation
         "adopted_source": session_id,
         "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0, "models": [],
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from actionlog import ActionLog
    ActionLog(run_dir).log("note", "ADOPTED Claude session %s (cwd %s)" % (session_id, cwd))
    events.emit("filed", tid, branch=branch, value=t["value"], actor=actor, driver="claude")
    _save_track(t)
    return t


def reorder(ids, actor="owner"):
    """Persist manual card order. rank = position in the given (single-lane)
    ordered id list; the board sorts by rank first, so this overrides the
    computed priority/due order - 'policy is data', order is now data too."""
    changed = 0
    for i, tid in enumerate(ids):
        def _rank(tt, i=i):
            if tt.get("rank") == i:
                return False
            tt["rank"] = i
        t = _mutate(tid, _rank)
        if t and t.get("rank") == i:
            changed += 1
    return {"reordered": changed}


def cancel_turn(tid, actor="owner"):
    """Stop a running turn (the composer's Stop button). Kills the driver
    subprocess; the turn returns as '(cancelled)'. Audit records it.

    If there is NO live session but the card is still flagged running, it is a
    ZOMBIE: a turn that died between daemon restarts (a 1800s kill, a driver
    crash) leaves status=running with no owning worker, and the old behaviour -
    cancel returns false, do nothing - left the phone watching a frozen card with
    a spinner that Stop could never clear. Now Stop unfreezes it exactly like the
    startup sweep does (bounce + resend note), so the button always does
    something instead of no-oping on a dead session."""
    import drivers, events
    killed = drivers.cancel(tid)
    if killed:
        events.emit("touch", tid, touch="cancel", actor=actor)
        t = get_track(tid)
        if t:
            from actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "turn CANCELLED by %s" % actor)

            # Reset the card OFF "running" here. Normally the steer thread does
            # this when _turn returns after the kill, but a racing/dead steer
            # thread (a daemon restart, overlapping cancels) can leave it stuck
            # at running with no session - a frozen spinner. The turn is
            # cancelled; it's the owner's move now. Through _mutate, so this
            # write and the steer thread's settle can interleave in any order
            # and the end state is still needs_you (invariant I3).
            def _settle(tt):
                if tt.get("status") != "running":
                    return False
                tt["status"] = "needs_you"
            _mutate(tid, _settle)
        return {"cancelled": True}
    # no live session - clear a stuck/zombie card so Stop is never a no-op, and
    # promote the interrupted session so re-steering RESUMES it losslessly.
    t = get_track(tid)
    if t and t.get("status") == "running" and not drivers.has_session(tid):
        box = {}

        def _unfreeze(tt):
            if tt.get("status") != "running" or drivers.has_session(tid):
                return False             # settled (or respawned) since the check
            box["resumable"] = _promote_live_session(tt)
            box["note"] = RESUME_NOTE if box["resumable"] else ZOMBIE_NOTE
            tt["status"] = "bounced"
            tt["gate_report"] = _interrupt_note_report(tt, box["note"])
        _mutate(tid, _unfreeze)
        if "note" in box:
            try:
                from actionlog import ActionLog
                ActionLog(t["run_dir"]).log("note", "STOP on a dead session - " + box["note"])
            except Exception:
                pass
            events.emit("bounce", tid, reason="stopped_zombie", actor=actor)
            return {"cancelled": True, "unfroze": True, "resumable": box["resumable"]}
    return {"cancelled": killed}


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
             if RESUME_NOTE not in l and ZOMBIE_NOTE not in l]
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


def present(t):
    """READ-side lifecycle derivation for the API (Paseo's normalizeArchivedStatus,
    server-side): a stored 'running' is only ever DELIVERED as running while a
    turn is actually in flight (drivers.turn_active). Otherwise - once past the
    spawn window - the client gets 'needs_you', WITHOUT touching the stored
    value. A phantom spinner is thereby impossible no matter what any write race
    puts in the DB (invariant I2); the reconciler remains the healer of the
    stored value. Returns a copy when coercing, the original otherwise."""
    if (t or {}).get("status") != "running":
        return t
    import drivers
    if drivers.turn_active(t["id"]):
        return t
    if _track_idle_s(t) <= PRESENT_IDLE_S:
        return t                       # spawn window - let it settle
    out = dict(t)
    out["status"] = "needs_you"
    out["status_derived"] = True       # marker: coerced at read, not stored
    return out


def sweep_zombies(min_idle_s=0):
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
    import drivers, events, notify
    from actionlog import ActionLog
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
            n = reconcile_bg(t["id"], why="Mit dem Daemon-Neustart abgebrochen")
            _mutate(t["id"], lambda tt: tt.__setitem__("waiting_on", "you")
                    if tt.get("waiting_on") == "background" else None)
            if n:
                try:
                    ActionLog(t["run_dir"]).log(
                        "note", "Hintergrund-Task(s) mit dem Daemon-Neustart abgebrochen: %s "
                        "- steuern startet sie neu." % names)
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
            # so a restart mid-gate freezes the card at 'gating' forever. Reap it -
            # but only once idle past a real gate's runtime (~2min) so a legit slow
            # gate is never cut. 0 at startup (a gating card then died with the daemon).
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


EDITABLE = ("task", "description", "priority", "due", "value", "client", "driver",
            "project_id", "billing", "rate", "autopilot", "fast_track")
# project_id may be explicitly cleared (unassign from a project) - unlike the
# other fields, "" / null is a meaningful value here, not "leave unset".
CLEARABLE = ("project_id",)
# "autopilot" is a card's own flag, NOT a mode: `mode` is already overloaded
# (execution mode for process steps, then the completion statistic auto/assisted
# written on accept by events._completion_mode), so the opt-in gets its own key
# and can never be set as a side effect of a touch-free acceptance.
# For the same reason a CARD's mode is never compared against
# policy.auto_dispatch_modes (that gates process STEPS in processes.sync):
# card dispatch only excludes the needs-a-person modes human/teach/cowork,
# so the 'auto' stat on an accepted card can never block a (re)dispatch
# (test_mode_dispatch.py pins this).
BOOLFIELDS = ("autopilot", "fast_track")

def archive_track(tid, on=True, actor="owner"):
    """Reversible: hides the card from work views; economics and audit stay."""
    import events

    def _flag(tt):
        tt["archived"] = bool(on)
    t = _mutate(tid, _flag)
    if not t:
        raise RuntimeError("no such track: " + tid)
    events.emit("archive", tid, on=bool(on), actor=actor)
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", ("ARCHIVED" if on else "UNARCHIVED") + " by " + actor)
    if on:
        # Archiving is terminal for work views - reclaim the isolation. Safe by
        # construction: a dirty tree is kept, an unmerged branch is kept (only
        # the regenerable worktree of a landed/clean card goes).
        reclaim_worktree(t, log)
    return t

def delete_track(tid, actor="owner"):
    """Destructive but bounded: removes the card, its worktree and branch.
    The audit trail is NOT deletable - events and the recording stay."""
    import events
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if t.get("worktree") and os.path.exists(t["worktree"]):
        subprocess.run(["git", "-C", t["repo"], "worktree", "remove", "--force",
                        t["worktree"]], capture_output=True, text=True)
    if _branch_exists(t["repo"], t["branch"]):
        subprocess.run(["git", "-C", t["repo"], "branch", "-D", t["branch"]],
                       capture_output=True, text=True)
    _db.track_delete(tid)
    events.emit("delete", tid, branch=t["branch"], task=t["task"][:80], actor=actor)
    return {"deleted": tid}

def update_track(tid, patch, actor="owner"):
    """Edit a card's request fields after creation. Only benign fields -
    lane/status/economics move through their own verbs.

    "driver" is technically in EDITABLE (a card can switch execution engine
    after filing - e.g. claude -> claude-desktop to grant windows-mcp/GUI
    control) but it is NOT benign like the others: it's a capability grant,
    not a request-detail edit. This function is the ONE place that field is
    ever written (server.py's /tracks/<id>/update and copilot.py's
    set_driver action both route through here), so its guards apply
    regardless of caller - role-gating still belongs to the caller (mirrors
    fast_track/resolve_conflict: policy.chat_admin_roles checked BEFORE
    calling this), but "is this even a real driver" and "not mid-turn" are
    invariants no caller should be able to skip."""
    import events
    if "driver" in patch and patch["driver"] is not None:
        valid = set((events.settings().get("drivers") or {}).keys())
        if patch["driver"] not in valid:
            raise ValueError("unknown driver '%s' - choices: %s"
                              % (patch["driver"], ", ".join(sorted(valid)) or "(none configured)"))
        import drivers
        if drivers.turn_active(tid):
            raise RuntimeError("cannot change driver while a turn is running - wait for it to finish")
    changed = {}

    def _edit(t):
        for k in EDITABLE:
            if k not in patch:
                continue
            v = patch[k] or None if k in CLEARABLE else patch[k]
            if k not in CLEARABLE and v is None:
                continue
            if k in BOOLFIELDS:
                v = bool(v)      # "off" arrives as false/0/"" - never as a string
            if v == t.get(k):
                continue
            t[k] = float(v) if k in ("value", "rate") and v is not None else v
            changed[k] = t[k]
        if not changed:
            return False
    t = _mutate(tid, _edit)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if changed:
        events.emit("edit", tid, actor=actor, fields=changed)
        from actionlog import ActionLog
        log = ActionLog(t["run_dir"])
        log.log("note", "EDITED by %s: %s" % (actor, ", ".join(changed)))
        # Visible capability-grant note (never a silent change) whenever the
        # NEW driver carries windows-mcp - the card's agent gains real
        # desktop/GUI control from here on, and every future turn on this
        # driver is screen-recorded (see events.py DEFAULTS["drivers"]).
        if "driver" in changed:
            dcfg = (events.settings().get("drivers") or {}).get(changed["driver"]) or {}
            if "mcp__windows-mcp__*" in (dcfg.get("allowed_tools") or []):
                log.log("note", "⚠ Desktop-Zugriff aktiviert (%s) von %s - "
                        "der Agent kann jetzt Maus/Tastatur/Bildschirm steuern, "
                        "Turns werden aufgezeichnet." % (changed["driver"], actor))
            # A driver's tool grant is baked into the argv at spawn and can't be
            # hot-swapped on a live process (drivers.apply_opts refuses it). The
            # guard above already blocked the change if a turn was in flight, so
            # any surviving session is IDLE - drop it now instead of leaving the
            # stale old-grant process to linger until the next turn notices. The
            # flip then takes hold on the very next message with no ghost process.
            import drivers as _drivers
            _drivers.drop_session(tid)
        # Flipping fast_track ON is itself a ship trigger, not just future turns:
        # a card can already be sitting on a finished-but-undeployed turn (owner
        # enables fast-track AFTER the turn ended), and the hook in _run_turn
        # only fires at turn-end - without this the flag does nothing until the
        # NEXT turn completes, and the owner asks "why didn't it deploy" while
        # the worker (unaware fast-track exists) wrongly says to use Review.
        if changed.get("fast_track") is True:
            _maybe_fast_track_ship(t, log)
    return t

DIRECTIVES = os.path.join(ROOT, "board_directives.json")

def apply_board_directives():
    """One-shot board-data patches shipped as repo DATA (policy is data). A
    card worker is worktree-isolated and never touches the live DB, so a card
    whose deliverable is a board change ships it here; the DAEMON applies it at
    startup through update_track (audit event + actionlog note included).
    Each entry {"id", "card", "set": {...}} is applied ONCE - the entry id is
    recorded on the card - so a later owner edit is never overwritten on
    restart. Done cards are left alone (their fields are accounting by then)."""
    if not os.path.exists(DIRECTIVES):
        return 0
    try:
        with open(DIRECTIVES, encoding="utf-8") as f:
            entries = json.load(f)
    except ValueError as e:
        print("directives: unreadable board_directives.json:", e)
        return 0
    applied = 0
    for entry in entries:
        did, tid = entry.get("id"), entry.get("card")
        if not did or not tid:
            continue
        t = get_track(tid)
        if not t or did in (t.get("directives_applied") or []) or t.get("lane") == "done":
            continue
        try:
            update_track(tid, entry.get("set") or {}, actor="directive:" + did)
        except (RuntimeError, ValueError) as e:
            print("directives: %s failed: %s" % (did, e))
            continue
        _mutate(tid, lambda tt: tt.setdefault("directives_applied", []).append(did) or None)
        applied += 1
    if applied:
        print("directives: applied %d board directive(s)" % applied)
    return applied

def add_attachments(tid, attachments, actor="owner"):
    """Attach files (PDF etc.) to an existing card, Jira/Plane-style. Saved into
    the card's run_dir/.attachments and appended to the card's file list; the
    worker sees them on its next turn (prompt lists attached files)."""
    import turnopts, events
    t = _find(_load(), tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    new_paths = turnopts.save_attachments(t["run_dir"], attachments)
    if new_paths:
        def _attach(tt):
            tt["attachments"] = (tt.get("attachments") or []) + new_paths
        t = _mutate(tid, _attach) or t
        events.emit("edit", tid, actor=actor, fields={"attachments": len(new_paths)})
        from actionlog import ActionLog
        ActionLog(t["run_dir"]).log("note", "%s attached %d file(s)" % (actor, len(new_paths)))
    return t

def remove_attachment(tid, name, actor="owner"):
    """Detach a file from the card by its basename (leaves the file on disk -
    append-only audit; the card just stops referencing it)."""
    def _detach(t):
        before = t.get("attachments") or []
        t["attachments"] = [p for p in before if os.path.basename(p) != name]
        if len(t["attachments"]) == len(before):
            return False
    t = _mutate(tid, _detach)
    if not t:
        raise RuntimeError("no such track: " + tid)
    return t

def list_checkpoints(tid):
    """The per-turn rewind anchors recorded for this card (newest last)."""
    t = _find(_load(), tid)
    return (t or {}).get("checkpoints") or []

def rewind_files(tid, commit, actor="owner"):
    """Restore the worktree's FILES to a recorded checkpoint (reversible: the
    current state is snapshotted first, and git keeps the objects). Only a
    checkpoint this card recorded is accepted - never an arbitrary ref. The
    session/conversation is NOT touched; use fork for a fresh line from here."""
    t = _find(_load(), tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt):
        raise RuntimeError("no worktree for this card")
    valid = {c.get("commit") for c in (t.get("checkpoints") or [])}
    if commit not in valid:
        raise RuntimeError("unknown checkpoint for this card")
    undo = _checkpoint(wt)                 # safety anchor of the current state
    _git(wt, "checkout", commit, "--", ".")
    if undo:
        def _anchor(tt):
            tt.setdefault("checkpoints", []).append(
                {"turn": tt.get("turns"), "commit": undo,
                 "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "reply": "(pre-rewind snapshot)"})
        _mutate(tid, _anchor)
    import events
    events.emit("rewind", tid, commit=commit[:12], undo=(undo or "")[:12], actor=actor)
    from actionlog import ActionLog
    ActionLog(t["run_dir"]).log("note", "REWOUND files to %s (undo %s) by %s"
                                % (commit[:8], (undo or "?")[:8], actor))
    return {"ok": True, "undo": undo}

def fork_conversation(tid, first="", actor="owner"):
    """Fork this card's LIVE CONVERSATION into a new sibling card: same context
    up to now, growing independently from here - so a crowded card (many
    unrelated threads steered into one) can be split without losing what it
    already knows. Different from fork_track (which forks the CODE at a ref
    with a FRESH session - no context carried).

    Mechanism: reuses the adopted_source pattern already proven for adopting an
    external Claude Code session (adopt_session, drivers.py:765) - the new card
    is seeded with the source's CURRENT session id, but adopted_source is set to
    that same id, so the driver's first spawn adds --fork-session. The CLI then
    clones the conversation into a FRESH session id on that first turn; the
    source card's own session is never touched or resumed-into. After that
    first turn, session_chain carries the pre-fork id, so the split-off card's
    transcript still SHOWS the shared history (read_transcript_live renders
    session_chain), then continues on its own below it - the owner sees exactly
    where the fork happened, not a history-less blank card.

    Isolation: a MACHINE card has no code-isolation model (its "worktree" is a
    real folder) - the new card shares the same cwd, same as filing two machine
    cards there today. A git card gets its OWN worktree (checked out at the
    source's CURRENT branch tip) so two cards never write into the same
    checkout at once - a chat split is not a licence for concurrent edits."""
    import events
    src = get_track(tid)
    if not src:
        raise RuntimeError("no such card: " + tid)
    sid = src.get("session_id")
    if not sid:
        raise RuntimeError("this card has no conversation yet to fork - steer it at least once first")
    new_id = _unique_id("chatfork")
    run_dir = os.path.join(REC, new_id)
    os.makedirs(run_dir, exist_ok=True)
    machine = bool(src.get("machine"))
    if machine:
        worktree = src.get("worktree", "")
        branch = src.get("branch", "(no git)")
    else:
        branch = "chatfork-" + _slug(src.get("branch", ""))[:20] + "-" + new_id.split("-")[-1][-4:]
        worktree = _worktree_for(src["repo"], branch)
        if os.path.exists(worktree):
            raise RuntimeError("fork worktree already exists")
        _git(src["repo"], "worktree", "add", worktree, "-b", branch, src.get("branch", "HEAD"))
    t = {"id": new_id, "repo": src["repo"], "branch": branch, "worktree": worktree,
         "machine": machine,
         "task": (first or ("Fork of the conversation from card %s" % tid))[:400],
         "client": src.get("client", ""), "session_id": sid,
         "perm": src.get("perm", DEFAULT_PERM), "lane": "working",
         "status": "needs_you", "turns": 0, "run_dir": run_dir, "last_reply": "",
         "value": src.get("value", 0), "driver": src.get("driver", "claude"),
         "priority": src.get("priority", "medium"), "due": src.get("due", ""),
         "model": "", "attachments": [],
         # remembered so the FIRST steer forks AWAY from the source session
         # instead of resuming into it (same guard adopt_session relies on)
         "adopted_source": sid,
         "forked_from": tid, "forked_from_session": sid,
         "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0, "models": [],
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from actionlog import ActionLog
    ActionLog(run_dir).log("note", "KONVERSATION FORKED von Karte %s (Session %s...)"
                           % (tid, sid[:8]))
    events.emit("chatfork", new_id, source_card=tid, session=sid, actor=actor)
    _save_track(t)
    return t


def fork_track(tid, from_ref="", actor="owner"):
    """Fork a NEW card from this card's state (its branch tip, or a specific
    commit hash). Append-only: creates a new branch/worktree/session off the
    ref; the source card is never modified. The forked worktree carries the
    code exactly as of `ref`."""
    import events
    src = get_track(tid)
    if not src:
        raise RuntimeError("no such card: " + tid)
    repo = src["repo"]
    ref = (from_ref or "").strip() or src["branch"]
    new_id = _unique_id("fork")
    branch = "fork-" + _slug(src["branch"])[:20] + "-" + new_id.split("-")[0][-4:]
    wt = _worktree_for(repo, branch)
    if os.path.exists(wt):
        raise RuntimeError("fork worktree already exists")
    _git(repo, "worktree", "add", wt, "-b", branch, ref)
    run_dir = os.path.join(REC, new_id)
    os.makedirs(run_dir, exist_ok=True)
    short = (from_ref[:8] + " of ") if from_ref else ""
    t = {"id": new_id, "repo": repo, "branch": branch, "worktree": wt,
         "task": "Forked from %s%s:\n\n%s" % (short, src["branch"], src["task"]),
         "client": src.get("client", ""), "session_id": None,
         "perm": src.get("perm", DEFAULT_PERM), "lane": "backlog",
         "status": "queued", "turns": 0, "run_dir": run_dir, "last_reply": "",
         "value": src.get("value", 0), "driver": src.get("driver", "claude"),
         "priority": src.get("priority", "medium"), "due": src.get("due", ""),
         "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0, "models": [],
         "forked_from": tid, "forked_ref": from_ref or "tip",
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from actionlog import ActionLog
    ActionLog(run_dir).log("note", "FORKED from card %s (%s%s) by %s" % (
        tid, short or "tip of ", src["branch"], actor))
    _save_track(t)
    events.emit("fork", new_id, source_card=tid, ref=from_ref or "tip", actor=actor)
    return t

def history(tid):
    """The track's conversation as recorded steers/replies (the reviewable timeline)."""
    from actionlog import read_timeline
    t = get_track(tid)
    if not t:
        return []
    return [r for r in read_timeline(t["run_dir"])
            if r.get("kind") in ("steer", "reply", "note", "turn")]
