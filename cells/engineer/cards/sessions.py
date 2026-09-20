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
from spine.ops.runs import REC

from daemon.paths import DAEMON_ROOT as ROOT, REPO_ROOT
STORE = os.path.join(ROOT, "tracks.json")
DEFAULT_PERM = os.environ.get("HELMDECK_PERM", "auto")   # 2026-09-12: Claude auto mode - "nur fragen wenn notwendig"
from spine.agent.agentcli import CLAUDE  # single source - see its module docstring

from spine.storage import db as _db
from spine.git.worktrees import reclaim_worktree, sweep_worktrees
from spine.turn.outcomes import extract_outcome, _record_outcome
from spine.turn.blockers import _blocker_text, blocker, manual_backlog, owner_blockers, waits_for_owner, MANUAL_MODES
from spine.turn.econ import _record_econ, _record_turn, _log_turn_end
from spine.git.gitutil import (_git, _git_try, _branch_exists, is_git_repo, _current_branch, _checkpoint, _seed_worktree, _repo_hash, _owned_worktree, _git_state_broken, WORKTREE_DIRNAME)
from spine.git.gitutil import _worktree_for, _base_ref, _worktree_of_branch
from spine.storage.trackstore import _load, _save, _save_track, _find, _slug, _unique_id, _mutate, _mutate_lock_for
from spine.git.locks import _lock_for, _direct_lock_for, _uses_desktop_control, _desktop_lock, _bump_steer_epoch, _steer_epoch_current, _drain_steer_texts
from cells.engineer.cards.turnrunner import (_turn, _repair_question, _ask_repair_on, is_delivered, _settle_reply_compute, _settle_reply_apply, _settle_reply, _turn_checkpoint, resume_detached, _finish_turn, ZOMBIE_NOTE, RESUME_NOTE, GATE_CUT_NOTE)
from cells.engineer.cards.lanemachine import (_gate, _merge_to_main, _autocommit, _pull_main_into_branch, _sync_base, _base_branch, dispatch_conflict_resolution, _classify_merge, _hook_kill_tree, _repo_hook, request_ship_decision, _say_card, move_lane, lane_active, _is_dirty_block, park_and_retry_merge)
from cells.engineer.cards.dispatch import (new_track, _dispatch_failed, _start, _ensure_worktree, _start_inner, machine_policy, machine_root_ok, new_machine_task, new_direct_task, _start_machine, backfill_outcomes, _accept_machine, MACHINE_BRANCH, DIRECT_BRANCH, _OUTCOME_BACKFILL_REVIEWED, new_remote_task, claim_remote_task, submit_remote_result, reassign_remote_task, sweep_stale_device_claims, start_device_claim_sweeper, new_ship_task, _maybe_ship_card_close)
from cells.engineer.cards.cardadmin import (archive_track, delete_track, update_track, apply_board_directives, add_attachments, remove_attachment, list_checkpoints, rewind_files, fork_conversation, fork_track, history, EDITABLE, CLEARABLE, BOOLFIELDS, DIRECTIVES)
from cells.engineer.cards.lifecycle import (_interrupt_note_report, _promote_live_session, _track_idle_s, present, sweep_zombies, start_zombie_reconciler, PRESENT_IDLE_S, _BOUNCE_ESCALATE_AT)





import threading as _threading


# -- background-task lifecycle: extracted to sessions_bg.py (god-file
# breakup) - see the re-import block near start_engineer_lifecycle below,
# where bg_upsert/reconcile_bg/etc are pulled back into this namespace.




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
        from spine.ops.actionlog import ActionLog
        ActionLog(t["run_dir"]).log(
            "note", "⚠ Worker wiederholt denselben Schritt (%dx %s) - PM prueft"
            % (evidence.get("n", 0), evidence.get("name", "")))
    except Exception:
        pass
    from spine.storage import events
    events.emit("burn", tid, n=evidence.get("n"), name=evidence.get("name"))
    try:
        from cells.copilot.planning import pm
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
         "instruction": "Merge; danach entscheidet Henry über den Ship. Nichts "
                        "merged sich selbst - außer policy.auto_accept_green ist an. "
                        "Der Prozess-Chain rückt einen Schritt vor.",
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
         "instruction": "Der bewusste Zug nach Done merged wirklich und übergibt "
                        "die Ship-Entscheidung an Henry. Idempotent: eine gelandete "
                        "Karte wird nie erneut gegatet oder gemerged."},
    ],
    "gate": {"key": "gate", "default_label": "Quality Gate", "kind": "fixed",
             "between": ["working", "review"], "settings": [],
             "instruction": "Gate-before-review ist ein fixes Harness-Gesetz: kein Review "
                            "ohne bestandenen Gate. Das Ergebnis geht append-only ins "
                            "Audit-Log.",
             "why": "Fix, weil eine Abnahme sonst nur eine Meinung wäre. Das Ergebnis "
                    "wird append-only protokolliert und kann nicht nachträglich "
                    "geschönt werden."},
    # DEPLOY IS A STEP, NOT A LANE - and the map has to say both.
    #
    # The owner must SEE deploy (it is the moment his work reaches the world),
    # but in the data model it is not a lane: since the 2026-09-01 owner decree
    # it is a JUDGEMENT - every landing calls
    # lanemachine.request_ship_decision, Henry decides (ship verb, kind
    # none|ota|native), and the broker executes his kind through the repo's
    # deploy hook with SHIP_KIND. So it is declared exactly the way `gate` is -
    # a step sitting ON an edge rather than beside the lanes - and `on` names
    # that edge. Drawing it as a fifth lane would make the picture lie about
    # where it happens, and not lying is this screen's whole job.
    #
    # It is also the ONLY genuinely switchable station (PRD §4.3.1): an empty
    # repo_hooks.<repo>.deploy means there is nothing to decide about and no
    # escalation is even emitted (request_ship_decision's first check). The
    # other four are law or the entrance.
    "deploy": {"key": "deploy", "default_label": "Deploy", "kind": "policy",
               "on": ["review", "done"], "settings": ["repo_hooks.<repo>.deploy"],
               "instruction": "Nach einer Landung entscheidet HENRY, ob und wie geshippt "
                              "wird (none/ota/native) - der DAEMON führt seine Entscheidung "
                              "über den Deploy-Hook aus, er hält die Secrets, nicht der "
                              "Agent. Kein Befehl hinterlegt = der Schritt passiert "
                              "schlicht nicht.",
               "why": "Die einzige Station, die eine Vorlage wirklich an- und ausschalten "
                      "kann. Alles andere ist Gesetz oder der Eingang."},
}

# -- STATIONS: the vocabulary the owner and the templates share ----------------
# The pipeline the decree names - Karte -> Arbeit -> Gate -> Abnahme -> Deploy -
# in the ids the machine actually uses. Deliberately NO second, German set of
# ids: the German words ARE the labels (default_label / policy.lane_labels), and
# a parallel id vocabulary is one more thing that can drift out of agreement.
STATIONS = ("backlog", "working", "gate", "review", "deploy")

# What the owner might SAY, mapped to what the machine calls it. Used only to
# parse his words in the chat verb - never for storage, never for display.
STATION_ALIASES = {
    "karte": "backlog", "karten": "backlog", "backlog": "backlog", "eingang": "backlog",
    "arbeit": "working", "working": "working", "in arbeit": "working",
    "gate": "gate", "quality gate": "gate", "qualitätsgate": "gate", "qualitaetsgate": "gate",
    "abnahme": "review", "review": "review", "freigabe": "review",
    "deploy": "deploy", "deployment": "deploy", "ausliefern": "deploy",
    "auslieferung": "deploy",
}

# THE HONEST LIST. "The template switches stations on and off" is true of
# exactly ONE of them (PRD §4.3.1, each verified against the code):
#   backlog - the entrance, always there
#   working - kind: fixed
#   gate    - harness law. In a text repo it runs empty and reports PASS
#             (run_gate.py:68-70) - that is a LABEL question, not a switch
#   review  - fixed as a station; policy.auto_accept_green only decides whether
#             it WAITS, not whether it exists
#   deploy  - genuinely switchable, via an empty repo hook
# A UI offering five toggles would be found out the first time one was tapped,
# so the code names the one that is real and refuses the others BY NAME.
SWITCHABLE_STATIONS = ("deploy",)


def station_id(word):
    """What the owner said -> a station id, or "" if it is not one.

    Case- and whitespace-insensitive. The chat verb runs every station name
    through here, so a model that invents a station cannot reach the settings
    writer with it."""
    return STATION_ALIASES.get(str(word or "").strip().lower(), "")


def flow(lane_labels=None, repo_view=None):
    """The lane/gate machine as data, with the owner's lane renames applied.

    `label` resolves policy.lane_labels over the built-in default, so the UI never
    has to know that renaming is a thing - it just renders `label`.

    `repo_view` is projects.resolve(repo) - pass it and every station also
    carries whether it is ACTIVE for that repo, and why not when it is not. The
    template only ever answers the on/off question: this function still owns the
    graph, which is what keeps the map derived rather than described (the client
    must not carry a station list - see routes_info's comment on why both graphs
    are derived, and CLAUDE.md's no-monkey-patches rule).

    Without `repo_view` every station is active, which is exactly the pre-template
    behaviour - so an old caller sees no change."""
    ll = lane_labels or {}
    out = {"nodes": [], "edges": [dict(e) for e in LANE_FLOW["edges"]],
           "gate": dict(LANE_FLOW["gate"]), "deploy": dict(LANE_FLOW["deploy"])}
    # file:line for every node, read out of THIS file - see loop_state._decl_lines
    # for why it is derived rather than written down.
    try:
        import sys as _sys
        _tools = os.path.join(REPO_ROOT, "ops", "tools")
        if _tools not in _sys.path:
            _sys.path.insert(0, _tools)
        from loop_state import _decl_lines
        src = _decl_lines([n["key"] for n in LANE_FLOW["nodes"]]
                          + [LANE_FLOW["gate"]["key"], LANE_FLOW["deploy"]["key"]],
                          path=os.path.abspath(__file__),
                          rel="cells/engineer/sessions.py")
    except Exception:                                        # noqa: BLE001
        src = {}

    # -- the on/off answer, from the template ------------------------------
    # An UNKNOWN repo (or none) leaves everything active: a repo without a
    # chosen type must render as the full pipeline, not as a switched-off one.
    tpl_stations = set((repo_view or {}).get("stations") or [])
    has_tpl = bool((repo_view or {}).get("template"))
    notes = (repo_view or {}).get("station_notes") or {}
    hook = (repo_view or {}).get("deploy_hook") or ""

    def _mark(node):
        """Active? and, when not, the reason - in the owner's words.

        Two different "off"s, and conflating them would be the lie the whole
        design guards against: a station the TEMPLATE leaves out, versus the
        deploy step that has no command hidden behind it. Both render dashed;
        they do not say the same thing."""
        k = node["key"]
        node["switchable"] = k in SWITCHABLE_STATIONS
        node["note"] = notes.get(k, "")
        if not has_tpl:
            node["active"] = True
            return node
        node["active"] = k in tpl_stations
        if not node["active"]:
            node["off_reason"] = ("Diese Vorlage benutzt die Station nicht."
                                  if k in SWITCHABLE_STATIONS else
                                  # a fixed station can never be off; if it is
                                  # missing from a template's list that is the
                                  # TEMPLATE being wrong, and saying so beats
                                  # rendering a law as switched off.
                                  "Fehlt in der Vorlage - diese Station ist aber "
                                  "fest und läuft trotzdem.")
            if k not in SWITCHABLE_STATIONS:
                node["active"] = True
        elif k == "deploy" and not hook:
            # active by the template, but nothing to run: honest, and the exact
            # sentence that tells the owner what to say to turn it on.
            node["active"] = False
            node["off_reason"] = ("Kein Deploy-Befehl hinterlegt. Sag Henry den Befehl, "
                                  "dann geht die Station an.")
        return node

    for n in LANE_FLOW["nodes"]:
        n = dict(n)
        n["label"] = ll.get(n["key"], n["default_label"])
        n["source"] = src.get(n["key"], "cells/engineer/sessions.py")
        out["nodes"].append(_mark(n))
    for step in ("gate", "deploy"):
        out[step]["label"] = out[step]["default_label"]
        out[step]["source"] = src.get(LANE_FLOW[step]["key"], "cells/engineer/sessions.py")
        _mark(out[step])
    # The station VOCABULARY, in flow order: what the owner can name in chat,
    # what a template may list, what the config screen offers a page for. It is
    # NOT the picture - see out["row"] below.
    out["stations"] = list(STATIONS)
    out["row"] = _draw_row(out)
    return out


def _draw_row(f):
    """THE PICTURE: which columns the pipeline is drawn with, and where the
    steps hang off it.

    Why this is not `stations`. `STATIONS` is a vocabulary - five names the
    owner, the templates and the chat verb share. Drawing it as the row made
    the screen assert something false: gate and deploy appeared as columns
    RANKING WITH the lanes, while `done` - a real lane the owner had renamed to
    "Fertig" in policy.lane_labels - was not drawn at all. The board said four
    lanes, the map said five stations, and neither list was the other's.

    So the row is DERIVED, twice over:
      columns - the lane nodes themselves, in LANE_FLOW order. Count AND names
                come from the same nodes policy.lane_labels renamed, so a
                rename or a fifth lane needs no edit here.
      steps   - gate and deploy, placed by reading their OWN declared edge
                (`between` for the gate, `on` for deploy) and hanging them on
                the connector that leaves that lane. Move the gate onto another
                edge and the drawing follows; nothing here re-states where it
                sits.

    `after` is a lane KEY, never an index - an index would silently point at the
    wrong lane the moment the lane list changed length, which is the class of
    bug this function exists to end."""
    lanes = [n["key"] for n in f["nodes"]]
    steps = []
    for key in ("gate", "deploy"):
        node = f.get(key) or {}
        if not node.get("key"):
            continue
        # The step's own declaration of the edge it sits on. First endpoint =
        # the lane it leaves; that connector is where it gets drawn.
        edge = list(node.get("between") or node.get("on") or [])
        after = next((k for k in edge if k in lanes), "")
        # A step whose edge does not touch a drawn lane keeps its marker at the
        # end rather than vanishing: an undrawn step is the failure we came from.
        steps.append({"key": node["key"], "after": after or (lanes[-1] if lanes else ""),
                      "on": edge})
    return {"lanes": lanes, "steps": steps}


# -- public API ----------------------------------------------------------

def list_tracks():
    return _load()

def get_track(tid):
    return _find(_load(), tid)



MODES = ("auto", "plan", "acceptEdits", "default", "bypassPermissions")
# The steer sources that may end a pending owner question: the owner (or an
# operator/client) typing at the card, and the answer path itself. Everything
# else - Henry, the PM, lane pipeline, hooks, the harness - is delegated work
# and is HELD while the card is parked on a question (see steer()).
HUMAN_SOURCES = ("you", "answer", "gxp-rejection")

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
    elif isinstance(gr, list) and any(RESUME_NOTE in x or ZOMBIE_NOTE in x
                                      or GATE_CUT_NOTE in x for x in gr):
        # A zombie-sweep/Stop interrupt (no gate involved) also stashes its note
        # in gate_report - the only channel _pending_context reads. Without this
        # branch a bare "continue" after an interrupt resumes BLIND: the worker
        # never learns its turn was cut, only that a new instruction arrived.
        parts.append("Note from the desktop since your last turn:\n" + "\n".join(gr))
    # Thrash guard: if this card has failed its gate several times in a row, a
    # naive rewrite-and-retry keeps burning the budget (SageRoute's rewrite/retest
    # trap). Tell the worker to stop rewriting and change approach - break the loop.
    from spine.storage import events
    from spine.agent import turnopts
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

# COMPACTION IS A MAINTENANCE TURN, AND IT MUST SURVIVE THE OWNER TYPING.
# Measured 2026-08-30 07:46-07:49 (card 20260830-065545, actions.jsonl):
#   07:46:40  AUTO-COMPACT at 92% (183k) starts a bounded /compact turn
#   07:48:13  the owner sends a normal message -> steer()'s interrupt-and-
#             replace (a36d962) sees turn_active and cancels it. The CLI
#             surfaces "AbortError: Compaction canceled."
#   07:48:21  _maybe_compact reads an UNCHANGED ctx and concludes "this CLI
#             doesn't honor /compact", latching _autocompact_supported=False
# The second line is the worse half: that flag is a PROCESS global, so ONE
# interrupted compaction silently disabled auto-compaction for EVERY card on
# the board until the next daemon restart - and the 92% card was never
# compacted again. Two rules follow, and they are what this block encodes:
#   1. An INTERRUPT teaches nothing. Only a turn that ran to completion is
#      evidence about whether the CLI honors /compact (CLAUDE.md: derived and
#      VERIFIED from the runtime's own signals, never assumed).
#   2. Compaction that got cut is RE-QUEUED (compact_pending on the card) and
#      retried at the next idle moment by the reconciler - never dropped.
# `_compacting` is the single owner of "a maintenance turn is in flight for
# this card", set at event time around the one _turn call below. steer() reads
# it to WAIT instead of cancelling, and an owner-typed /compact reads it for
# single-flight. No wall-clock cap anywhere: the compact turn stays bounded by
# its own 180s idle watchdog, the waiters by that same bound plus slack.
_compacting = {}                 # tid -> threading.Event (set when the turn ends)
_compacting_guard = _threading.Lock()
_compact_interrupted = set()     # tids whose in-flight compaction we cut on purpose

# HOW LONG A COMPACTION MAY BE SILENT - and, since 2026-09-11, how long ANY
# steerer (owner or harness) defers to one. These used to be the same number
# (180s, chosen 2026-08-15 when a wedged compact turn blocked the whole
# post-turn pipeline for 15 minutes). Measured 2026-08-30 on the 183k session
# this bug was found on: `/compact` emits NOTHING on the stream for over three
# minutes on a near-full window - it was still working (the transcript grew at
# 08:04:16) when the 180s watchdog killed it. So 180s was not "generous slack
# above every observed compaction", it was tuned on small sessions and fails
# exactly on the big ones that need it most - hence the bigger number below.
#
# A STEERING OWNER used to get a much shorter allowance (25s) than a harness
# self-continuation (this same bound) - found 2026-09-05, a COWORK card
# watching a red CI run fired a `background-task` auto-steer on every task
# completion, each cutting the compaction after 25s and re-queueing it, so a
# 97%/195k session livelocked, starting and dying forever while the context
# never shrank. Giving background sources the full bound fixed that livelock -
# but left the SHORT cut for genuine owner input, on the theory that "the
# owner must never feel the harness". Measured wrong: Paseo's steerActiveTurn
# is simply unavailable while compacting - no owner-specific short-circuit -
# and the 25s cut bought nothing but a near-certain re-queue on any session big
# enough to need compacting in the first place (a real /compact routinely
# takes minutes). So there is now ONE bound for every steerer, and the
# owner-specific short defer is gone. A compaction that is still running past
# THIS bound is genuinely wedged - it yields and RE-QUEUES (compact_pending),
# same fallback as before, just no longer the routine case.
# Neither is a wall-clock cap on a turn: the watchdog still measures SILENCE.
_COMPACT_IDLE_S = 600


def compacting(tid):
    """The in-flight compaction's completion Event for this card, or None.
    Truth comes from the registry the compaction itself writes, not from a
    stored card flag - same rule as drivers.turn_active."""
    with _compacting_guard:
        return _compacting.get(tid)


def await_compaction(tid, log=None, timeout=_COMPACT_IDLE_S):
    """Let an in-flight compaction FINISH before this caller's own turn.
    Returns True if we ended up cutting it short (caller may proceed to
    cancel), False if there was nothing to wait for or it finished cleanly."""
    ev = compacting(tid)
    if ev is None:
        return False
    if log:
        log.log("note", "⏳ Verdichtung laeuft - deine Anweisung startet direkt danach "
                        "(der Verlauf bleibt erhalten).")
    if ev.wait(timeout):
        return False
    # Wedged past its own idle bound: the owner goes first, but we record WHY
    # it ended so the shrink check below never reads this as "unsupported".
    _compact_interrupted.add(tid)
    if log:
        log.log("note", "Verdichtung haengt - wird abgebrochen, deine Anweisung geht vor. "
                        "Sie wird beim naechsten Leerlauf nachgeholt.")
    return True


def _mark_compact_pending(tid, on):
    def _set(tt):
        if on:
            if tt.get("compact_pending"):
                return False
            tt["compact_pending"] = True
        else:
            if not tt.get("compact_pending"):
                return False
            tt.pop("compact_pending", None)
    try:
        _mutate(tid, _set)
    except Exception:
        pass


def _compact_marks(session_id):
    """How many compaction summaries the CLI has written into this session's
    OWN transcript (~/.claude/projects/<cwd>/<sid>.jsonl, the same append-only
    record claude_sessions.py already treats as the source of truth for the
    card feed - see its isCompactSummary handling).

    This exists because the turn's return value is NOT sufficient evidence that
    a compaction did or did not happen. Measured 2026-08-30 on the 183k
    session: `/compact` wrote its summary into the transcript and then the CLI
    process simply never exited, so the turn died on the watchdog and the
    harness concluded "nothing happened" - twice - about a compaction that had
    in fact already succeeded. (The 2026-08-15 note in this file described the
    same hang and drew the wrong conclusion from it.) The transcript is the
    runtime's own signal; the exit code is only the transport."""
    try:
        from spine.agent.claude_sessions import _find_transcript
        p = _find_transcript(session_id)
        if not p:
            return 0
        n = 0
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                i = line.find('"isCompactSummary"')
                if i >= 0 and "true" in line[i:i + 30]:
                    n += 1
        return n
    except Exception:
        return 0


def _compact_after_turn(t, log):
    """The post-turn compaction, on its own thread. Best-effort by contract:
    nothing downstream waits on it and a failure here must never surface as a
    turn failure - _maybe_compact already re-queues whatever it could not
    finish, so 'later' is a real outcome, not a loss."""
    try:
        _maybe_compact(t, log)
    except Exception as _e:
        log.log("note", "auto-compact skipped: %s" % str(_e)[:200])
        _mark_compact_pending(t["id"], True)


def _maybe_compact(t, log, force=False, idle_timeout=None):
    """Compact the session in place if the live context crossed the high-water
    mark. Self-verifying: /compact must actually SHRINK the context (ctx_tokens
    is the last-call-only reading, not summed - a real compaction is visible
    there). If it does not (an older CLI that treats the slash line as literal
    input), we learn that once and stop - no no-op cost, no polluting the
    conversation every turn. `force` is the owner typing /compact himself: run
    regardless of the high-water mark and regardless of a previously learned
    False (he can see the meter; his ask outranks our probe). Returns the fresh
    track (or None if nothing was done)."""
    global _autocompact_supported
    if _autocompact_supported is False and not force:
        return None
    ctx = t.get("ctx_tokens", 0)
    # high-water mark scales with the session's DERIVED window (ctx_window is
    # runtime evidence, incl. the proof-beyond-200k 1M inference above) - the
    # fixed 160k mark made a 1M-tier session "compact" at a real ~16% fill,
    # burning a full-context /compact turn while the CLI (which knows its real
    # window) rightly saw no reason to shrink anything.
    window = max(t.get("ctx_window") or 0, _CTX_WINDOW)
    if not t.get("session_id"):
        return None
    if ctx < 0.8 * window and not force:
        # NOT this call's decision to make. This runs after EVERY turn (via
        # _compact_after_turn), not just retries, and `window` can have grown
        # in the very same turn that got us here (ctx_window is re-derived
        # from live evidence - see econ.py's "[1m]"/proof-beyond-200k rule).
        # Clearing compact_pending here used to mean: a card queued for retry
        # after an interrupted/died/owner-forced-while-busy compaction lost
        # that obligation the instant a reclassification made the ratio look
        # fine - no idle grace, no re-read of the live figure, same turn that
        # caused the reclassification. Measured 2026-09-10 (card 20260910-
        # 134430): a genuinely-owed retry evaporated this way at 604k context
        # right as the session reclassified to the 1M tier.
        # compact_pending has exactly ONE owner for "is this retry still
        # needed": lifecycle.sweep_pending_compaction, which re-reads the live
        # ctx/window AGAINST THE FRESH THRESHOLD with an idle gate before
        # dropping the flag - the re-evaluation this card asks for. A plain
        # "nothing to do" turn never sets compact_pending in the first place,
        # so leaving it untouched here costs nothing.
        return None
    tid = t["id"]
    # SINGLE FLIGHT. Without this, an owner-typed /compact landing on a card
    # that is already auto-compacting starts a SECOND /compact against the same
    # session - two turns racing for one session id, and whichever loses gets
    # read as evidence about the CLI. One compaction per card, always.
    with _compacting_guard:
        if tid in _compacting:
            log.log("note", "Verdichtung laeuft bereits - kein zweiter Durchlauf.")
            return None
        done = _threading.Event()
        _compacting[tid] = done
    _compact_interrupted.discard(tid)
    marks0 = _compact_marks(t.get("session_id"))
    pct = min(100, round(ctx / window * 100))
    log.log("note", "AUTO-COMPACT: Kontext bei %d%% (~%dk) - ich verdichte die Session, "
            "damit der Verlauf erhalten bleibt und es weitergeht." % (pct, round(ctx / 1000)))
    # The watchdog here is the SILENCE bound only (see _COMPACT_IDLE_S above for
    # why it is no longer the 180s that killed the 183k compaction mid-work).
    # The 2026-08-15 concern it replaces - a wedged compact turn blocking every
    # post-turn step - is answered structurally instead: this runs off the turn
    # thread, and a steering owner cuts it via await_compaction rather than
    # waiting it out.
    try:
        sid, _out, meta = _turn(t, "/compact",
                                idle_timeout=idle_timeout or _COMPACT_IDLE_S)
    except BaseException as e:
        # The turn DIED (stalled past the watchdog, driver crash, killed
        # process). Ask the TRANSCRIPT what actually happened before deciding -
        # measured 2026-08-30, the compaction had already been written when the
        # watchdog fired, and calling that "nothing happened" is what left the
        # card at 92% across two full retries.
        if _compact_marks(t.get("session_id")) > marks0:
            _autocompact_supported = True
            _mark_compact_pending(tid, False)
            log.log("note", "AUTO-COMPACT ok: die Verdichtung steht im Transkript - der "
                            "CLI-Prozess ist danach nur nicht sauber beendet (%s). "
                            "Die Session ist verdichtet, der naechste Turn startet auf "
                            "dem kleinen Kontext." % str(e)[:120])
            return None
        # Genuinely nothing landed. Not evidence about /compact support either -
        # same "learned nothing" case as an interrupt - so re-queue, or the card
        # silently keeps its full context forever.
        _mark_compact_pending(tid, True)
        log.log("note", "AUTO-COMPACT abgebrochen (%s) - nichts gelernt, Session "
                        "unveraendert. Wird beim naechsten Leerlauf nachgeholt."
                % str(e)[:160])
        return None
    finally:
        with _compacting_guard:
            _compacting.pop(tid, None)
        done.set()                        # release every steer waiting on us

    def _apply(tt):
        if sid and tt.get("session_id") and sid != tt["session_id"]:
            chain = [s for s in (tt.get("session_chain") or []) if s != tt["session_id"]]
            chain.append(tt["session_id"])
            tt["session_chain"] = chain[-6:]
            tt["session_id"] = sid
        _record_econ(tt, meta)            # measured economics: the compact turn is billed too
    t = _mutate(tid, _apply) or t
    before = ctx
    after = t.get("ctx_tokens", before)
    # DID IT RUN, OR WAS IT CUT? A cancelled turn returns the driver's clean
    # sentinel ("(turn cancelled by you)") - plus our own flag when we cut it
    # ourselves. Either way the unchanged ctx says NOTHING about whether the
    # CLI honors /compact, so the probe must not learn from it (this is the
    # exact misread that latched _autocompact_supported=False board-wide on
    # 2026-08-30). Re-queue instead; the reconciler retries at idle.
    # THE RUNTIME'S OWN VERDICT FIRST (Paseo: compact_boundary = compaction
    # completed). The driver folds the system/compact_boundary frame into
    # meta.compaction at event time; when it is there the compaction
    # HAPPENED, whatever the interrupt flag or the meter say - measured
    # 2026-09-13 (card 20260913-215533): the boundary landed at 22:59, the
    # owner's waiting steer cut the still-open process at 23:07, and the
    # interrupt branch below then logged "haengt - wird nachgeholt" about a
    # compaction that had succeeded eight minutes earlier.
    cm = (meta or {}).get("compaction") or {}
    interrupted = (tid in _compact_interrupted
                   or "cancelled" in (_out or "").lower()
                   or "compaction canceled" in (_out or "").lower())
    _compact_interrupted.discard(tid)
    if cm:
        _autocompact_supported = True
        _mark_compact_pending(tid, False)
        post = cm.get("post_tokens")
        dur = cm.get("duration_ms")
        log.log("note", "AUTO-COMPACT ok: Kontext jetzt ~%sk (vorher ~%dk, %s) - Verlauf "
                "verdichtet, es geht ohne Unterbrechung weiter."
                % (round(post / 1000) if post else "?", round(before / 1000),
                   ("%ds" % round(dur / 1000)) if dur else "Dauer unbekannt"))
        return t
    if interrupted:
        _mark_compact_pending(tid, True)
        log.log("note", "AUTO-COMPACT unterbrochen - nichts gelernt, nichts verloren. "
                "Wird beim naechsten Leerlauf automatisch nachgeholt.")
        return t
    if after <= before * 0.75:            # a real compaction frees a big chunk
        _autocompact_supported = True
        _mark_compact_pending(tid, False)
        log.log("note", "AUTO-COMPACT ok: Kontext jetzt ~%dk - Verlauf verdichtet, es geht "
                "ohne Unterbrechung weiter." % round(after / 1000))
    elif _compact_marks(t.get("session_id")) > marks0:
        # The context figure did not move but the CLI DID write a compaction.
        # The reading is stale, not the compaction absent: ctx_tokens comes from
        # the turn's reported usage, and a /compact turn that reports nothing
        # (or reports the PRE-compaction call) leaves the meter behind until the
        # next real turn refreshes it. Judging "unsupported" on that number
        # alone is how a working compaction got switched off.
        _autocompact_supported = True
        _mark_compact_pending(tid, False)
        log.log("note", "AUTO-COMPACT ok: Verdichtung im Transkript. Das Kontext-Meter "
                        "steht erst beim naechsten Turn wieder richtig.")
    else:
        _autocompact_supported = False
        _mark_compact_pending(tid, False)
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
    if t.get("example"):
        # A message to the onboarding guide must NOT be the one path that
        # dispatches it - this runs in a background thread (routes_track_
        # actions.tracks_steer_post), so an uncaught refusal here would be
        # silent; answer the owner instead, same as lanemachine's move refusal.
        from spine.ops.actionlog import ActionLog
        from spine.storage import events
        ActionLog(t["run_dir"]).log("note",
            "Das ist die Beispielkarte - sie startet nie einen Agenten. "
            "Loesch sie, wenn du sie nicht mehr brauchst.")
        events.emit("example", tid, outcome="steer_refused", actor=actor)
        return t
    if not t.get("session_id"):
        _start(tid)                      # steering a backlog card dispatches it first
        tracks = _load(); t = _find(tracks, tid)
    from spine.storage import events
    from spine.agent import turnopts
    from spine.agent import drivers
    events.emit("touch", tid, touch="steer", actor=actor)
    was_bounced = t.get("status") == "bounced"   # routing signal, read BEFORE 'running'
    # same timing, for the SAME reason: this steer may be the owner resolving
    # a pending question - captured before _begin() clears it below.
    was_needs_you = t.get("status") == "needs_you"
    pending_q = ((t.get("question") or {}).get("question")
                or (t.get("question") or {}).get("header") or "")
    from spine.ops.actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    # The owner typing /compact is a COMMAND, not a message to the worker. Sent
    # through as ordinary text it (a) interrupts whatever turn is live and (b)
    # can race the harness's own auto-compaction for the same session. Route it
    # to the one compaction owner instead - single-flight, force past a learned
    # "unsupported", and never a second concurrent run.
    if (text or "").strip().lower() == "/compact":
        log.log("steer", text)
        if compacting(tid) is not None:
            log.log("note", "Verdichtung laeuft bereits - dein /compact wartet nicht "
                            "doppelt, das Ergebnis kommt gleich.")
            return t
        if drivers.turn_inflight(tid):     # queued counts: it is about to run
            _mark_compact_pending(tid, True)
            log.log("note", "Ein Turn laeuft - die Session wird direkt danach verdichtet "
                            "(kein Abbruch, nichts geht verloren).")
            return t
        try:
            t = _maybe_compact(t, log, force=True) or t
        except Exception as _ce:
            _mark_compact_pending(tid, True)
            log.log("note", "/compact fehlgeschlagen: %s - wird beim naechsten Leerlauf "
                            "nachgeholt." % str(_ce)[:200])
        return t
    # PARKED MEANS PARKED. A card holding an owner question accepts exactly two
    # things: the answer, or the owner's own words (reply_door already turns a
    # matching reply into an answer; free text is the owner deciding something
    # else). A DELEGATED steer - Henry, the PM, the lane pipeline, a hook - is
    # not an answer and must not consume the question. Measured 2026-09-20
    # 12:25:20: the worker asked "how should I be re-dispatched?", 0.75s later
    # Henry's queued "Zusatzanforderung" steer ran, _begin() popped the
    # question, the owner's tap 409'd "no pending question", and the worker
    # asked the same thing again a turn later. The instruction is HELD on the
    # card (held_steers, written here, consumed by the steer that finally
    # runs) so nothing is lost - it rides along with the answer.
    if source not in HUMAN_SOURCES and t.get("question"):
        held = {}

        def _hold(tt):
            if not tt.get("question"):
                return False           # answered meanwhile - let it run
            tt.setdefault("held_steers", []).append(
                {"text": text, "source": source, "actor": actor,
                 "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            held["ok"] = True
        t = _mutate(tid, _hold) or t
        if held.get("ok"):
            log.log("steer", text)
            log.log("note", "HELD - die Karte wartet auf eine Antwort des Owners (%s). "
                            "Anweisung von %s ist keine Antwort und wird mit der "
                            "Antwort nachgereicht." % (pending_q[:120], source))
            events.emit("touch", tid, touch="steer_held", actor=actor, source=source)
            return t
    # A COMPACTION IS NOT A TURN TO REPLACE. It is bounded maintenance on the
    # session this very instruction needs, and cancelling it both loses the
    # compaction AND (before the fix above) taught the probe a lie. So EVERY
    # steerer - owner typing or the harness continuing itself - waits it out
    # (Paseo steerActiveTurn: unavailable while compacting), bounded by the
    # compact turn's own idle watchdog, no new wall-clock cap; only a
    # genuinely wedged compaction past that bound yields, and it re-queues
    # (compact_pending) rather than being lost.
    if await_compaction(tid, log):
        try:
            drivers.cancel(tid)
        except Exception:
            pass
    # INTERRUPT-AND-REPLACE: if a turn is live, soft-interrupt it and start THIS
    # instruction now (Paseo's replaceAgentRun), instead of queuing behind it on
    # the per-card lock. drivers.cancel is the cooperative interrupt (~2s ack,
    # the process stays alive, the session resumes), so the interrupted turn
    # releases the lock and this steer runs immediately after. A burst collapses
    # to last-wins via the epoch: only the newest steer survives the bail below.
    my_epoch = _bump_steer_epoch(tid, text)
    # inflight, not active: a turn still QUEUED on the desktop/direct lock must
    # also be replaced - otherwise it acquires later and runs the SUPERSEDED
    # instruction after this one already answered.
    if drivers.turn_inflight(tid):
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
    from spine.comms import notify
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
    # A steer answering a WAITING goal-path card is the exact bug measured
    # 2026-09-04 ("Owner macht jetzt das Video selbst und macht spaeter
    # weiter" resolved the Play-Console video blocker, but only that one
    # card's own turn log ever carried it - four days later the planner
    # asked to release again, having forgotten). Fold it into the SAME
    # ground-truth channel GRILLEN clarifications already use, so it
    # outlives the card's next turn instead of getting overwritten by
    # last_reply. Scoped to goal-path cards only (a milestone's own `card`)
    # - a random unrelated card's Q&A is not the goal's ground truth, and
    # add_clarification's 12-slot cap would just get spent on noise.
    # actor == "daemon" is the harness talking to the card (a background-task
    # hand-back, a compaction nudge) - not an owner answer, and it was filling
    # the 12-slot clarification list with "[[helmdeck:background-done]]"
    # boilerplate the planner then read as ground truth (measured 2026-09-12).
    if was_needs_you and actor != "daemon" and not text.lstrip().startswith("[["):
        try:
            from cells.copilot.planning import pm
            plan = pm.latest_plan() or {}
            if pm.get_goal() and any((ms.get("card") == tid) for ms in (plan.get("milestones") or [])):
                fact = "Karte '%s': %s -> Antwort: %s" % (
                    (t.get("task") or "")[:80], pending_q[:200] if pending_q else "Rückfrage", text[:300])
                pm.add_clarification(fact, actor=actor, source="card", card=tid)
        except Exception:
            pass                          # a fold failure must never block the steer
    paths = turnopts.save_attachments(t.get("worktree") or t["run_dir"], attachments)
    # Auto routing sees the card's facts INCLUDING turn count - a card that's
    # already dragged on escalates to the strong model (cheap "escalate on
    # evidence"). An explicit model from the composer still wins.
    cli_model, _ = turnopts.resolve_model(model, text, bool(paths),
        signals={"value": t.get("value"), "priority": t.get("priority"), "turns": t.get("turns"),
                 "failed": was_bounced or bool(t.get("gate_failed")),
                 "fails": events.consecutive_gate_fails(t["id"]),
                 # the card's own measured meter: a worker that has grown past
                 # a cheap model's window must not be routed into it (the board
                 # chat hit exactly that, 2026-08-30 - see turnopts.CTX_WINDOWS)
                 "ctx_tokens": t.get("ctx_tokens")})
    # An explicit composer pick (incl. "auto") is a STICKY card default, not a
    # one-turn favor: without this, the picker only ever won the turn it was
    # clicked on (t["model"] stayed "" from creation) and every later harness-
    # initiated turn (dispatch retry, auto-continue, ask-repair) fell through
    # turnrunner._turn's own auto-routing again - Sonnet picked here, Opus
    # spawned two turns later with no visible cause. Persist the RAW pick
    # (not cli_model): "auto" must stay "auto" so future turns keep re-routing
    # on the card's live signals instead of freezing at today's resolution.
    if model:
        _mutate(tid, lambda tt: tt.__setitem__("model", model))
    # Hand the worker the daemon-side context it never saw (a merge conflict, a
    # failed gate) so a steer like "resolve the conflict" isn't blind. The AUDIT
    # above still logs the human's original text, not this augmentation.
    prompt = _pending_context(t) + turnopts.augment_prompt(text, thinking, paths)
    # Deliver what was HELD while the card waited on the question (see the
    # hold above) - consumed here, once, by the steer that actually runs.
    # The audit above logged only the human's words; the held texts were
    # audited when they arrived.
    held_box = {}
    _mutate(tid, lambda tt: held_box.__setitem__("v", tt.pop("held_steers", None)) or None)
    held_list = held_box.get("v") or []
    if held_list:
        prompt += "\n\n" + "\n\n".join(
            "[Nachgereicht - kam von %s, waehrend die Karte auf die Antwort wartete:]\n%s"
            % (h.get("source") or "?", h.get("text") or "") for h in held_list)
        log.log("note", "%d gehaltene Anweisung(en) mit dieser Antwort nachgereicht." % len(held_list))
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
        sid, result, meta = _turn(t, prompt, model=cli_model, perm=perm_override, by=actor)
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
    # verdict the session (one /compact on the same session) so the next steer
    # keeps headroom and the thread stays continuous - never a dead-end or a
    # fresh-session overflow. OFF THE TURN THREAD, exactly like the copilot's
    # _schedule_compact ("compaction is maintenance and must never be a pause in
    # the conversation"): a near-full window takes minutes to compact, and
    # everything after this line - the push notification, the fast-track ship -
    # used to sit behind it. The single-flight registry, not this call site,
    # is what keeps one compaction per card.
    _threading.Thread(target=_compact_after_turn, args=(t, log), daemon=True).start()
    from spine.comms import notify
    notify.card_event(t, reason)
    return _after_turn_land(t, log)


def _after_turn_land(t, log):
    """THE ONE turn-end landing branch, shared by BOTH completion paths: the
    steer path above and the FIRST turn of a machine/direct card
    (dispatch._start_machine). Until 2026-09-12 only the steer path had it -
    a direct card that finished in its first turn (the common case, e.g.
    20260912-113606-direct, DELIVERED 11:38) never autocommitted, never
    asked Henry for a ship decision, and sat in working until the owner
    moved it by hand 4.5h later (backlog/direct-cards-never-land). Two
    copies of this branch would drift again; one function cannot.
    Returns t - a ship card may have self-closed (stored record wins)."""
    # FAST-TRACK = ship EVERY finished turn, hands-free. The flag used to fire
    # only when the OWNER dragged the card to Review - which is exactly the
    # manual push fast-track exists to remove ("man muss immer noch schieben,
    # also kein Vorteil"). Now a fast_track card SUBMITS ITSELF when its turn
    # ends: gate -> merge -> deploy hook run in the background, and the change
    # is testable without touching the board. The gate still guards (red gate
    # bounces back with the report), a pending question still parks the card
    # (the owner's decision comes first), and a turn that produced NOTHING new
    # to ship is skipped so a chat-only turn can't close the card. A card
    # dispatched onto the no-worktree Paseo path (dispatch._start_inner,
    # owner-decreed 2026-08-20) has no branch to gate or merge - autocommit +
    # deploy only.
    if t.get("ship_kind"):
        # a Ship card (owner decree 2026-09-09, 18:04 correction) - its own
        # brief did DIAGNOSE->EXECUTE->VERIFY as ITS reasoning; this only
        # reads the verdict line and closes it on success. Checked BEFORE
        # "direct" below: a ship card is also direct=True (dispatch.
        # new_ship_task rides that shape) but must never ALSO run
        # _maybe_fast_track_ship_direct (it has no fast_track flag, so that
        # hook would no-op anyway, but this keeps the two paths structurally
        # exclusive rather than relying on a flag that happens to be unset).
        # Lives in dispatch.py, not here: a ship card's FIRST (often only)
        # turn dispatches through _start_machine, a completely separate
        # completion path from this steer-only one - one function shared by
        # both call sites, not two copies that could drift. MUST reassign
        # t: move_lane's write is on the STORED record, not this local
        # variable.
        t = _maybe_ship_card_close(t, log)
    elif t.get("direct"):
        _maybe_fast_track_ship_direct(t, log)
    else:
        # worktree fast-track card: CONVERT to the live-tree rails at turn end
        # (2026-08-21) - lands the branch (no gate), reclaims the worktree,
        # repoints direct; a conflict auto-steers the worker and this hook
        # closes the loop on that turn's end. The old gated ship
        # (_maybe_fast_track_ship) is retired from this path.
        _maybe_fast_track_convert(t, log)
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
    log.log("note", "FAST-TRACK: Turn fertig -> Gate + Merge im Hintergrund; "
            "Ship entscheidet Henry. Die Karte bleibt in Arbeit.")

    def _ship():
        from spine.ops.actionlog import ActionLog
        from spine.storage import events
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
            # Owner decree 2026-09-01: the merge LANDS here, the SHIP is
            # Henry's judgement - request_ship_decision replaces the
            # mechanical hook fire (and with it the hook-persist dance and
            # the deploy_fail_streak auto-repair loop: a red ship now keeps
            # its ship-decision escalation open at the broker, which is the
            # agentic retry, bounded by the broker's own attempt cap).
            request_ship_decision(t, "fast-track")
            lg.log("note", "FAST-TRACK gelandet (%s) - Ship-Entscheidung liegt bei "
                   "Henry; die Karte bleibt in Arbeit, steuern geht einfach weiter."
                   % kind)
        except Exception as e:
            try:
                lg.log("note", "FAST-TRACK fehlgeschlagen: %s" % str(e)[:250])
            except Exception:
                pass
    _threading.Thread(target=_ship, daemon=True).start()


def _auto_resolve_conflict(t, log, reason):
    """Self-healing half of the fast-track conversion: instead of parking a
    conflict for the owner, steer the card's OWN worker to merge the markers
    by plain editing (the same edit-only dispatch_conflict_resolution the
    chat/PM use). The turn-end hook re-attempts the conversion afterwards, so
    resolve -> land needs nobody. Bounded: 2 automatic tries (matches the PM
    RESOLVE ladder), then a loud escalation note - an agent that cannot merge
    the same hunk twice needs a human judgement, not a third identical try."""
    tries = int(t.get("ft_resolve_tries") or 0)
    if tries >= 2:
        log.log("note", "FAST-TRACK: Konflikt auch nach %d automatischen "
                "Aufloesungs-Versuchen offen (%s) - Henry uebernimmt die "
                "Entscheidung." % (tries, reason))
        from spine.registry import escalations
        escalations.emit("conflict-unresolved", card=t["id"],
                         detail="%s nach %d Auto-Versuchen; Branch %s"
                                % (reason, tries, t.get("branch")))
        return
    _mutate(t["id"], lambda tt: tt.__setitem__("ft_resolve_tries", tries + 1))
    from cells.engineer.cards import lanemachine as _lm
    msg = _lm.dispatch_conflict_resolution(t["id"], actor="fast-track",
                                           background=True)
    log.log("note", "FAST-TRACK: %s - der Worker loest die Markierungen "
            "AUTOMATISCH (Versuch %d/2); danach wird die Konvertierung erneut "
            "versucht, du musst nichts tun. %s"
            % (reason, tries + 1, (msg or "")[:200]))


def _maybe_fast_track_convert(t, log):
    """Turn-end hook for a fast_track card still on the WORKTREE rails: since
    the flip-on conversion exists (2026-08-20), a finished turn on such a card
    attempts the same conversion - land the branch, reclaim, repoint direct -
    instead of the old gated ship. This is also what closes the auto-resolve
    loop: the conflict-resolution turn ends, this hook runs, the conversion
    retries and lands. Same guards as the ship: only at rest, never with a
    pending question, only when there is something to land."""
    if not (t.get("fast_track") and not t.get("machine") and not t.get("direct")
            and t.get("status") == "needs_you" and not t.get("question")):
        return
    wt = t.get("worktree") or ""
    if not os.path.isdir(wt):
        return
    rc, dirty, _ = _git_try(wt, "status", "--porcelain")
    ahead = False
    integ = _current_branch(t.get("repo") or "")
    if integ and t.get("branch"):
        ahead = _git_try(t["repo"], "merge-base", "--is-ancestor",
                         t["branch"], integ)[0] != 0
    merging = _git_try(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0
    if not ((rc == 0 and dirty) or ahead or merging):
        return                          # chat-only turn - nothing to land
    _convert_fast_track_live(t, log)


def _convert_fast_track_live(t, log):
    """Fast-track ON for a card that STARTED worktree-isolated: move it onto
    the live-tree rails instead of leaving it gated for its lifetime. The old
    keep-isolated stance protected the cwd-keyed transcript and the branch
    work - but it also meant fast-track was no escape hatch when the gate
    itself was the broken part (measured 2026-08-20: the card carrying the
    gate's own daemon fix could never pass the gate the buggy daemon ran; the
    merge had to be done by hand outside the harness). Conversion only runs on
    an IDLE turn (update_track raises otherwise): land the branch work on the
    base (autocommit + the same _merge_to_main the accept path uses - the gate
    skip IS what fast-track means, debt fast-track-no-gate), reclaim the
    worktree, repoint the card onto the live tree, drop the idle session so
    the next spawn is cwd-keyed to the live tree. A CONFLICT (markers or a
    merge refusal) no longer parks for the owner - chat must never dead-end
    (2026-08-21, the Display-Glasses card wedged at 4am on exactly this): the
    card's OWN worker is auto-steered to merge the markers by editing
    (dispatch_conflict_resolution, edit-only), and the turn-end hook
    re-attempts the conversion when that turn finishes. Bounded to 2
    automatic tries (RESOLVE ladder), then it escalates to the owner.
    Returns the updated track, or None if not (yet) converted."""
    tid = t["id"]
    if _autocommit(t) == "markers":
        _auto_resolve_conflict(t, log, "offene Konfliktmarkierungen im Worktree")
        return None
    ok, kind, msg = _merge_to_main(t)
    from spine.storage import events
    events.emit("merge", tid, ok=bool(ok), outcome=kind,
                detail="fast-track-convert: " + (msg or "")[:200])
    if not ok:
        if kind == "conflict":
            _auto_resolve_conflict(t, log, "Merge-Konflikt mit der Basis")
        else:
            log.log("note", "FAST-TRACK an: Branch nicht auf die Basis mergebar "
                    "(%s) - Karte bleibt worktree-isoliert. %s"
                    % (kind, (msg or "")[:300]))
        return None
    _mutate(tid, lambda tt: tt.pop("ft_resolve_tries", None))
    from spine.git.worktrees import reclaim_worktree
    reclaim_worktree(t, log)
    def _mark(tt):
        tt["machine"] = True         # ride the no-worktree dispatch/accept path
        tt["direct"] = True          # serialized per-tree in _turn
        tt["worktree"] = tt["repo"]  # the LIVE tree, no copy
    t = _mutate(tid, _mark) or t
    from spine.agent import drivers as _drivers
    _drivers.drop_session(tid)       # idle by the guard; next turn respawns on the live tree
    log.log("note", "FAST-TRACK an: Karte auf den Live-Tree umgezogen (%s) - "
            "Branch gelandet, Worktree zurueckgegeben; ab jetzt Autocommit+"
            "Deploy ohne Gate nach jedem Turn." % kind)
    if kind == "merged":
        # real commits just landed on the base - the ship is Henry's call now
        # (owner decree 2026-09-01), same contract as every other landing.
        try:
            request_ship_decision(t, "fast-track-umzug")
        except Exception as e:
            log.log("note", "FAST-TRACK: Ship-Eskalation nach Umzug fehlgeschlagen: %s" % str(e)[:250])
    return t


def _maybe_fast_track_ship_direct(t, log):
    """FAST-TRACK on the no-worktree Paseo path (dispatch._start_inner marks
    machine+direct+worktree=repo for a fast_track card, owner-decreed
    2026-08-20 - pays no debt into gate-base-lag/finalize-loses-uncommitted,
    because there is no separate worktree copy to drift or reclaim). Same
    'ship every finished turn' contract as _maybe_fast_track_ship, but there
    is no branch to gate or merge - the turn already edited the LIVE tree.
    So: autocommit only (still refuses to land open conflict markers - that
    is data hygiene, not the gate) -> deploy hook. NO test gate, NO merge -
    Paseo semantics, registered as debt fast-track-no-gate (spine/
    registry/debt.py)."""
    if not (t.get("fast_track") and t.get("machine") and t.get("direct")
            and t.get("status") == "needs_you" and not t.get("question")):
        return
    wt = t.get("worktree") or ""
    if not os.path.isdir(wt):
        return
    rc, dirty, _ = _git_try(wt, "status", "--porcelain")
    if not (rc == 0 and dirty):
        return                          # chat-only turn - nothing to deploy
    tid = t["id"]
    log.log("note", "FAST-TRACK (direct): Turn fertig -> Autocommit + Deploy im "
            "Hintergrund. Die Karte bleibt in Arbeit.")

    def _ship():
        from spine.ops.actionlog import ActionLog
        lg = ActionLog(t["run_dir"])
        try:
            if _autocommit(t) == "markers":
                lg.log("note", "FAST-TRACK (direct): offene Konfliktmarkierungen - "
                       "nicht deployed.")
                return
            # Owner decree 2026-09-01: autocommit lands the work, the ship is
            # Henry's judgement (see _maybe_fast_track_ship for the full note).
            request_ship_decision(t, "fast-track-direct")
            lg.log("note", "FAST-TRACK (direct) gelandet - Ship-Entscheidung liegt "
                   "bei Henry; die Karte bleibt in Arbeit, steuern geht einfach weiter.")
        except Exception as e:
            try:
                lg.log("note", "FAST-TRACK (direct) fehlgeschlagen: %s" % str(e)[:250])
            except Exception:
                pass
    _threading.Thread(target=_ship, daemon=True).start()


# _try_auto_fix_deploy + deploy_fail_streak removed 2026-09-01 with the
# mechanical fast-track deploy they reacted to: a red ship now keeps its
# ship-decision escalation OPEN at Henry's broker, and Henry's own `steer`
# verb is the worker-repair path - with judgement about whether repairing is
# even the right move, which the fixed 3-strikes loop could not ask.


def reply_door(t, text):
    """Which door an owner's free-text reply to a card goes through.

    Returns (kind, answers, request_id): ("answer", {header: text}, id) when the
    card has ONE pending question that this text validly settles, else
    ("steer", None, ""). Pure - it decides, it does not dispatch, so a route can
    answer the HTTP request immediately and background the slow half.

    Lives here, next to the two doors it chooses between, because more than one
    surface asks the question: the Henry chat on the phone and /wear/talk on the
    watch both route an inline reply, and a second copy of this rule would be
    two surfaces that disagree about whether a sentence settled a question.

    Falling back to a steer rather than reporting an error is deliberate. The
    owner typed a sentence at his inbox; "that was not a valid answer" is not a
    useful thing to say to a person who just answered, and a multi-question ask
    (which one line genuinely cannot settle) is the common reason."""
    q = (t or {}).get("question") or {}
    qs = q.get("questions") or []
    if len(qs) != 1:
        return "steer", None, ""
    from spine.ops import ask
    cand = {qs[0]["header"]: text}
    _picks, err = ask.validate_answers(q, cand)
    if err:
        return "steer", None, ""
    return "answer", cand, q.get("id") or ""


def answer_question(tid, answers, request_id="", actor="owner", echo_chat=True):
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
    from spine.ops import ask
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
    from spine.ops.actionlog import ActionLog
    ActionLog(t["run_dir"]).log("note", ask.answer_note(picks))
    from spine.storage import events
    events.emit("answer", tid, actor=actor, qkind=q.get("kind"),
                picks=[ask._pick_parts(p) for p in picks])
    # The answer also lands in the owner's Henry chat, bound to this card. THIS
    # is the one owner of "the question was answered" for the inbox, and it has
    # to be here rather than at each caller: an answer can arrive from the phone
    # panel, the watch, the glasses, a notification button or an inline chat
    # reply, and only this function sees all of them. Without it the mirrored
    # question would sit in the inbox still offering options it had already
    # spent - and the owner, seeing an open question, would answer it a second
    # time into a guaranteed 409.
    #
    # `echo_chat=False` for the ONE caller that already wrote it: an inline
    # reply typed in the Henry chat is logged there verbatim, with the `mid` the
    # app minted, so the optimistic bubble can retire by identity. Writing a
    # second, RE-RENDERED copy here (free text comes back quoted from
    # _pick_parts) would both duplicate the message and leave the owner's
    # original bubble pinned to the bottom of the chat forever, because it would
    # never find its own text again.
    if echo_chat:
        try:
            from cells.copilot.chat import copilot
            copilot.say(", ".join(", ".join(ask._pick_parts(p)) for p in picks),
                        cls="you", card=tid)
        except Exception:
            pass
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

# -- background-task lifecycle (bg_upsert/reconcile_bg/_sweep_background/
# start_background_watcher): extracted to sessions_bg.py (god-file breakup).
# Re-imported here so every existing sessions.<name> caller (lifecycle.py,
# drivers.py, claude_sessions.py, server.serve) stays unchanged.
from cells.engineer.cards.sessions_bg import (
    _BG_HISTORY_CAP, BG_TERMINAL, _BG_POLL_S, _BG_MAX_WAIT_S, _bg_watcher_started,
    bg_upsert, reconcile_bg, _bg_continue_on, _continue_prompt, _sweep_background,
    _epoch_of, start_background_watcher)


def start_engineer_lifecycle():
    """Launch the Engineer cell's THREE continuous pollers (the zombie
    reconciler, the background-task auto-continue watcher, and the device
    claim sweeper - ops/docs/backlog/remote-device-execution/PLAN-
    hardening.md Phase A) as ONE registrable entry point for
    cells.start_enabled() (daemon/debt.py order 33, Phase 3). All three
    operate directly on track/session state (card `status`, session
    liveness, background-task completion, a remote device's claim) - they
    are the Engineer cell's own lifecycle, not spine-adjacent generic
    housekeeping, so they belong behind engineerEnabled the same way the
    planning loop belongs behind copilotEnabled (pm merged into copilot,
    2026-09-03).
    (Contrast: sessions.sweep_worktrees() stays a flat ONE-SHOT boot call in
    serve() - it is a backstop pass over git worktrees at startup, not a
    continuous poller, so it has nothing to "stop" if a cell is disabled later
    and stays alongside the other one-shot boot calls like backfill_outcomes.
    sweep_stale_device_claims() gets the SAME one-shot boot call too, next to
    sweep_worktrees - this function only adds the ongoing poll.)
    Call this ONCE (cells.start_enabled() only calls a cell's `start` once per
    boot): start_background_watcher() is internally idempotent
    (_bg_watcher_started guard), start_zombie_reconciler()/
    start_device_claim_sweeper() are not guarded and would spawn a second
    thread if invoked twice."""
    start_zombie_reconciler()
    start_background_watcher()
    start_device_claim_sweeper()


def adopt_session(session_id, cwd, mode="continue", first="", actor="owner"):
    """Bring an existing Claude Code session (from ~/.claude) onto the board.
      mode="continue": wrap it IN PLACE as a card - no new branch/worktree; the
        card's steer resumes the exact session (`claude --resume`) in its own cwd.
      mode="fork": open a NEW branch + worktree from that repo with a fresh
        session, seeded with the original's starting request (source untouched).
    No git commit is made either way - tracking is the card's audit trail; a fork
    creates a branch pointer, real commits come only when the agent commits code."""
    from spine.storage import events
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
    from spine.ops.actionlog import ActionLog
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
    from spine.agent import drivers
    from spine.storage import events
    killed = drivers.cancel(tid)
    if killed:
        events.emit("touch", tid, touch="cancel", actor=actor)
        t = get_track(tid)
        if t:
            from spine.ops.actionlog import ActionLog
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
    # ...but a turn QUEUED on the desktop/direct lock also has no session, and
    # is not a zombie - drivers.cancel above already armed its intent, so it
    # will abort itself the moment it acquires. Bouncing it here with "daemon
    # restarted" would be the phantom note again.
    if t and t.get("status") == "running" and not drivers.has_session(tid) \
            and not drivers.turn_queued(tid):
        box = {}

        def _unfreeze(tt):
            if tt.get("status") != "running" or drivers.has_session(tid) \
                    or drivers.turn_queued(tid):
                return False             # settled (or respawned) since the check
            box["resumable"] = _promote_live_session(tt)
            box["note"] = RESUME_NOTE if box["resumable"] else ZOMBIE_NOTE
            tt["status"] = "bounced"
            tt["gate_report"] = _interrupt_note_report(tt, box["note"])
        _mutate(tid, _unfreeze)
        if "note" in box:
            try:
                from spine.ops.actionlog import ActionLog
                ActionLog(t["run_dir"]).log("note", "STOP on a dead session - " + box["note"])
            except Exception:
                pass
            events.emit("bounce", tid, reason="stopped_zombie", actor=actor)
            return {"cancelled": True, "unfroze": True, "resumable": box["resumable"]}
    return {"cancelled": killed}

