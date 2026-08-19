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
from daemon.spine.ops.runs import REC

from daemon.paths import DAEMON_ROOT as ROOT, REPO_ROOT
STORE = os.path.join(ROOT, "tracks.json")
DEFAULT_PERM = os.environ.get("HELMDECK_PERM", "acceptEdits")
CLAUDE = (os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")

from daemon.spine.storage import db as _db
from daemon.spine.git.worktrees import reclaim_worktree, sweep_worktrees
from daemon.spine.turn.outcomes import extract_outcome, _record_outcome
from daemon.spine.turn.blockers import _blocker_text, blocker, manual_backlog, owner_blockers, waits_for_owner, MANUAL_MODES
from daemon.spine.turn.econ import _record_econ, _record_turn, _log_turn_end
from daemon.spine.git.gitutil import (_git, _git_try, _branch_exists, is_git_repo, _current_branch, _checkpoint, _seed_worktree, _repo_hash, _owned_worktree, _git_state_broken, WORKTREE_DIRNAME)
from daemon.spine.git.gitutil import _worktree_for, _base_ref, _worktree_of_branch
from daemon.spine.storage.trackstore import _load, _save, _save_track, _find, _slug, _unique_id, _mutate, _mutate_lock_for
from daemon.spine.git.locks import _lock_for, _direct_lock_for, _uses_desktop_control, _desktop_lock, _bump_steer_epoch, _steer_epoch_current, _drain_steer_texts
from daemon.cells.engineer.turnrunner import (_turn, _repair_question, _ask_repair_on, is_delivered, _settle_reply_compute, _settle_reply_apply, _settle_reply, _turn_checkpoint, resume_detached, _finish_turn, ZOMBIE_NOTE, RESUME_NOTE)
from daemon.cells.engineer.lanemachine import (_gate, _merge_to_main, _autocommit, _pull_main_into_branch, dispatch_conflict_resolution, _classify_merge, _hook_kill_tree, _repo_hook, _say_card, move_lane, _is_dirty_block, park_and_retry_merge)
from daemon.cells.engineer.dispatch import (new_track, _dispatch_failed, _start, _ensure_worktree, _start_inner, machine_policy, machine_root_ok, new_machine_task, new_direct_task, _start_machine, backfill_outcomes, _accept_machine, MACHINE_BRANCH, DIRECT_BRANCH, _OUTCOME_BACKFILL_REVIEWED)
from daemon.cells.engineer.cardadmin import (archive_track, delete_track, update_track, apply_board_directives, add_attachments, remove_attachment, list_checkpoints, rewind_files, fork_conversation, fork_track, history, EDITABLE, CLEARABLE, BOOLFIELDS, DIRECTIVES)
from daemon.cells.engineer.lifecycle import (_interrupt_note_report, _promote_live_session, _track_idle_s, present, sweep_zombies, start_zombie_reconciler, PRESENT_IDLE_S, _BOUNCE_ESCALATE_AT)





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
        from daemon.spine.ops.actionlog import ActionLog
        ActionLog(t["run_dir"]).log(
            "note", "⚠ Worker wiederholt denselben Schritt (%dx %s) - PM prueft"
            % (evidence.get("n", 0), evidence.get("name", "")))
    except Exception:
        pass
    from daemon.spine.storage import events
    events.emit("burn", tid, n=evidence.get("n"), name=evidence.get("name"))
    try:
        from daemon.cells.pm import pm
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
        _tools = os.path.join(REPO_ROOT, "tools")
        if _tools not in _sys.path:
            _sys.path.insert(0, _tools)
        from loop_state import _decl_lines
        src = _decl_lines([n["key"] for n in LANE_FLOW["nodes"]] + [LANE_FLOW["gate"]["key"]],
                          path=os.path.abspath(__file__),
                          rel="daemon/cells/engineer/sessions.py")
    except Exception:                                        # noqa: BLE001
        src = {}
    for n in LANE_FLOW["nodes"]:
        n = dict(n)
        n["label"] = ll.get(n["key"], n["default_label"])
        n["source"] = src.get(n["key"], "daemon/cells/engineer/sessions.py")
        out["nodes"].append(n)
    out["gate"]["label"] = out["gate"]["default_label"]
    out["gate"]["source"] = src.get(LANE_FLOW["gate"]["key"], "daemon/cells/engineer/sessions.py")
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
    from daemon.spine.storage import events
    from daemon.spine.agent import turnopts
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
    from daemon.spine.storage import events
    from daemon.spine.agent import turnopts
    from daemon.spine.agent import drivers
    events.emit("touch", tid, touch="steer", actor=actor)
    was_bounced = t.get("status") == "bounced"   # routing signal, read BEFORE 'running'
    from daemon.spine.ops.actionlog import ActionLog
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
    from daemon.spine.comms import notify
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
    from daemon.spine.comms import notify
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
        from daemon.spine.ops.actionlog import ActionLog
        from daemon.spine.storage import events
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
    from daemon.spine.ops import ask
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
    from daemon.spine.ops.actionlog import ActionLog
    ActionLog(t["run_dir"]).log("note", ask.answer_note(picks))
    from daemon.spine.storage import events
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
    from daemon.spine.storage import events
    pol = events.settings().get("policy") or {}
    return bool(pol.get("auto_continue", True))


def _continue_prompt():
    """Tagged as harness-injected so the card feed renders it as a system note
    instead of a message the owner appears to have typed (ask.harness_msg)."""
    from daemon.spine.ops import ask
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
        from daemon.spine.agent import drivers
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
        from daemon.spine.agent import claude_sessions
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
        from daemon.spine.ops.actionlog import ActionLog
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
        from daemon.spine.storage import events
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


def start_engineer_lifecycle():
    """Launch the Engineer cell's two continuous pollers (the zombie reconciler
    + the background-task auto-continue watcher) as ONE registrable entry point
    for cells.start_enabled() (daemon/debt.py order 33, Phase 3). Both pollers
    operate directly on track/session state (card `status`, session liveness,
    background-task completion) - they are the Engineer cell's own lifecycle,
    not spine-adjacent generic housekeeping, so they belong behind
    engineerEnabled the same way pm's proactive loop belongs behind pmEnabled.
    (Contrast: sessions.sweep_worktrees() stays a flat ONE-SHOT boot call in
    serve() - it is a backstop pass over git worktrees at startup, not a
    continuous poller, so it has nothing to "stop" if a cell is disabled later
    and stays alongside the other one-shot boot calls like backfill_outcomes.)
    Call this ONCE (cells.start_enabled() only calls a cell's `start` once per
    boot): start_background_watcher() is internally idempotent
    (_bg_watcher_started guard), start_zombie_reconciler() is not guarded and
    would spawn a second sweep thread if invoked twice."""
    start_zombie_reconciler()
    start_background_watcher()


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
    from daemon.spine.storage import events
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
    from daemon.spine.ops.actionlog import ActionLog
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
    from daemon.spine.agent import drivers
    from daemon.spine.storage import events
    killed = drivers.cancel(tid)
    if killed:
        events.emit("touch", tid, touch="cancel", actor=actor)
        t = get_track(tid)
        if t:
            from daemon.spine.ops.actionlog import ActionLog
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
                from daemon.spine.ops.actionlog import ActionLog
                ActionLog(t["run_dir"]).log("note", "STOP on a dead session - " + box["note"])
            except Exception:
                pass
            events.emit("bounce", tid, reason="stopped_zombie", actor=actor)
            return {"cancelled": True, "unfroze": True, "resumable": box["resumable"]}
    return {"cancelled": killed}

