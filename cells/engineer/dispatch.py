# -*- coding: utf-8 -*-
"""The dispatch SERVICE - extracted from sessions.py. new_track files a
request (backlog or immediately started); _start/_start_inner/_ensure_
worktree spawn a card's FIRST turn; machine_policy/new_machine_task/
new_direct_task/_start_machine are the machine + direct build paths
(a real folder or the live repo root as workplace, no worktree/branch);
backfill_outcomes + _accept_machine finish the machine accept flow.

Imports the already-extracted services DIRECTLY (trackstore, gitutil,
turnrunner, lanemachine, blockers, outcomes) - by the time this cluster was
reached, EVERY real dependency was already a service, so this needed ZERO
lazy back-references into sessions.py (down from the 19 in the original
failed machine-task attempt, and the 4 lanemachine needed) - concrete proof
that extracting bottom-up collapses coupling instead of hiding it.
"""
import os
import shutil
import time

from spine.ops.runs import REC
from spine.registry import i18n as _i18n

from spine.storage.trackstore import _load, _save_track, _find, _slug, _unique_id, _mutate
from spine.git.gitutil import (_git, _git_try, _branch_exists, _git_state_broken,
                     _owned_worktree, _seed_worktree, _base_ref,
                     _worktree_for, _worktree_of_branch)
from cells.engineer.turnrunner import _turn, _finish_turn, is_delivered
from cells.engineer.lanemachine import _gate, _say_card, move_lane
from cells.engineer.devport import _alloc_dev_port
from spine.turn.blockers import blocker
from spine.turn.outcomes import extract_outcome, _record_outcome

# same env var as sessions.DEFAULT_PERM - process-idempotent, safe to read
# independently rather than importing sessions (would cycle).
DEFAULT_PERM = os.environ.get("HELMDECK_PERM", "acceptEdits")


def new_track(repo, branch, task, perm=DEFAULT_PERM, lane="working", client="",
              value=None, driver="claude", actor="owner", priority="medium", due="",
              model="", attachments=None, project_id=None, billing="fixed", rate=None,
              description=""):
    """File a request. lane=backlog stores it un-started (no worktree, no session);
    lane=working starts the branch session immediately. value = what the
    deliverable is worth (settings default when omitted) - set at intake so
    margin is computable at acceptance. project_id assigns the card to a
    fixed-price/T&M project (projects.py); its own `value` then stops feeding
    the totals - the project's billing does (events.metrics)."""
    from spine.storage import events
    from spine.agent import turnopts
    repo = os.path.abspath(repo)
    tracks = _load()
    tid = _unique_id(_slug(branch))
    run_dir = os.path.join(REC, tid)
    os.makedirs(run_dir, exist_ok=True)
    # attachments filed with the request are saved now; the first run reads them.
    # model chosen in the composer becomes the card's execution model (Auto too).
    att_paths = turnopts.save_attachments(run_dir, attachments)
    # Auto routing sees the card's own facts (value/priority); an explicit model
    # from the composer still wins (resolve_model only routes for "auto").
    cli_model, _ = turnopts.resolve_model(model, task, bool(att_paths),
        signals={"value": value, "priority": priority})
    t = {"id": tid, "repo": repo, "branch": branch, "worktree": "", "task": task,
         "dev_port": None,     # reserved at dispatch (_alloc_dev_port), sticky
         # task = the one-line title (Jira summary); description = the long body
         # (Jira/Plane description). Both editable; the agent reads title+desc+files.
         "description": description or "",
         "client": client, "session_id": None, "perm": perm, "lane": "backlog",
         # WHO ASKED for this card - distinct from `client` (the customer it is
         # billed to). Captured at intake because four-eyes needs it later: the
         # person who filed a card must not also be the one who approves it
         # (signatures.four_eyes_violation). Nothing can reconstruct this after
         # the fact, so it is recorded here or it is lost.
         "dispatched_by": actor,
         "status": "queued", "turns": 0, "run_dir": run_dir, "last_reply": "",
         "value": float(value) if value is not None else events.settings()["value_per_card"],
         "driver": driver or "claude", "priority": priority or "medium", "due": due or "",
         "rank": None, "model": cli_model or "", "attachments": att_paths,
         "project_id": project_id or None,
         # billing (per card): fixed = `value` is the agreed price, recognized on
         # done; tm = worked hours (time_in_work) x `rate`, accrues live; none =
         # internal/unbilled (contributes 0). A card is billed on its own; a
         # process groups cards into one SoW rollup (events.metrics).
         "billing": billing if billing in ("fixed", "tm", "none") else "fixed",
         "rate": float(rate) if rate is not None else None,
         "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0, "models": [],
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from spine.ops.actionlog import ActionLog
    ActionLog(run_dir).log("note", "REQUEST filed: %s (branch %s)" % (task, branch))
    events.emit("filed", tid, branch=branch, value=t["value"], actor=actor, driver=t["driver"])
    _save_track(t)
    if lane == "working":
        t = _start(tid)
    return t

def _dispatch_failed(t, e):
    """Dispatch runs on a background thread, so an uncaught exception is
    invisible - the card must carry the error itself: status=bounced,
    the failure in last_reply, a note in the flight recorder, an event."""
    from spine.storage import events
    err = "DISPATCH FAILED: %s" % e
    from spine.ops.actionlog import ActionLog
    try:
        log = ActionLog(t["run_dir"])
        log.log("note", err[:2000])
        log.log("turn", "Turn fehlgeschlagen", event="failed", error=str(e)[:500])
    except Exception:
        pass
    events.emit("error", t["id"], where="dispatch", detail=str(e)[:600])

    def _fail(tt):
        tt["status"] = "bounced"
        tt["last_reply"] = err[:2000]
    _mutate(t["id"], _fail)

def _start(tid):
    """Dispatch a backlog request: create the worktree + open its coding session."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if t["session_id"]:
        return t
    try:
        return _start_inner(t)
    except Exception as e:
        _dispatch_failed(t, e)
        raise

def _ensure_worktree(t):
    """Make sure the card's worktree EXISTS, (re)creating it from the branch if
    needed, and return its path. The worktree is regenerable state (the branch
    holds the commits) - so a missing directory must never be a hard error:
    dispatch uses this, and steer SELF-HEALS through it instead of dying with
    WinError 267 (spawn cwd invalid) when the tree is gone (reclaimed, cleaned
    by hand, or never created because a bad branch name broke dispatch).

    A path existing is NOT proof it is a working worktree: `git worktree add`
    can be interrupted after it creates the directory but before it finishes
    (or something else mkdir'd the slot first), leaving a plain folder that was
    never `git init`'d into a worktree. Dispatching an agent into that folder
    lets every git command inside the turn fail with 'not a git repository' -
    the failure surfaces deep in the turn, not here, so it looked unrelated
    until traced back. _git_state_broken is the same check reclaim already
    trusts to judge a worktree's git link; reuse it here so a broken/never-init
    slot gets rebuilt before dispatch instead of handed out as-is."""
    wt = _worktree_for(t["repo"], t["branch"])
    existing = _worktree_of_branch(t["repo"], t["branch"])
    if existing and os.path.isdir(existing):
        return existing                     # reuse a prior checkout (e.g. legacy dir)
    if os.path.exists(wt) and _owned_worktree(wt) and _git_state_broken(wt):
        _git_try(t["repo"], "worktree", "remove", "--force", wt)
        if os.path.isdir(wt):
            shutil.rmtree(wt, ignore_errors=True)
    if not os.path.exists(wt):
        _git_try(t["repo"], "worktree", "prune")   # drop a stale registration of this path
        if _branch_exists(t["repo"], t["branch"]):
            _git(t["repo"], "worktree", "add", wt, t["branch"])
        else:
            # Explicit base + --no-track (Paseo): never branch off whatever HEAD
            # happens to be, and never let the card branch claim an upstream.
            base = _base_ref(t["repo"])
            _git(t["repo"], "worktree", "add", wt,
                 "-b", t["branch"], "--no-track", base)
            _record_base_branch(t, base)
        _seed_worktree(t["repo"], wt)
    return wt


def _record_base_branch(t, base):
    """Fold the card's BASE onto the card at the one event where it is a fact -
    branch creation - and never again (debt accept-merge-base-branch). The base
    cannot be re-derived later: the repo checkout moves, so reading HEAD at gate
    or accept time answers a different question than "what did this card fork
    from". Recording it at the fork is the same shape as drivers.turn_active and
    sessions.record_bg - observed once, at event time, by exactly one owner.

    lanemachine._sync_base consumes it (merge the base INTO the card before the
    gate, so a card never reds on base drift it never touched - debt
    gate-base-lag) and VERIFIES the ref still resolves rather than trusting the
    stored string. A card dispatched before this existed simply has no field;
    the consumer falls back to the repo's checked-out branch, never a guess
    written back to the card."""
    def _base(tt):
        tt["base_branch"] = base

    t["base_branch"] = base        # the caller's snapshot sees it immediately
    try:
        _mutate(t["id"], _base)
    except Exception:
        pass                        # a card not (yet) in the store is not a dispatch failure


def _start_inner(t):
    if t.get("fast_track") and not t.get("machine"):
        # FAST-TRACK, Paseo semantics (owner-decreed 2026-08-20, debt
        # fast-track-no-worktree): the whole point of worktree isolation - a
        # regenerable, disposable copy - kept fast-track cards exposed to base
        # drift for the card's ENTIRE open lifetime (a gate can red on code the
        # card never touched, see debt gate-base-lag). The owner chose to drop
        # isolation for this class rather than build the sync-loop fix: a
        # fast-track card edits the LIVE tree directly, same no-worktree rails
        # as new_direct_task (below) - no branch, no gate-before-review, no
        # merge. sessions._maybe_fast_track_ship_direct replaces the normal
        # gate+merge ship with autocommit+deploy for these cards.
        def _mark(tt):
            tt["machine"] = True         # ride the no-worktree dispatch/accept path
            tt["direct"] = True          # serialized per-tree in _turn
            tt["worktree"] = tt["repo"]  # the LIVE tree, no copy
        t = _mutate(t["id"], _mark) or t
    if t.get("machine"):
        return _start_machine(t)
    tid = t["id"]
    wt = _ensure_worktree(t)
    from spine.ops.actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "DISPATCHED -> branch %s" % t["branch"])
    log.log("steer", t["task"])
    log.log("turn", "Turn gestartet", event="started")
    from spine.storage import events
    events.emit("lane", tid, frm=t.get("lane"), to="working")

    port = t.get("dev_port") or _alloc_dev_port(exclude_tid=tid)

    def _begin(tt):
        tt["worktree"] = wt; tt["lane"] = "working"; tt["status"] = "running"
        if port:
            tt["dev_port"] = port
    t = _mutate(tid, _begin) or t
    prompt = t["task"]
    if t.get("description"):              # the long-form body (Jira-style)
        prompt += "\n\n" + t["description"]
    if t.get("attachments"):             # files filed with the request
        prompt += "\n\nAttached files (read them as needed): " + ", ".join(t["attachments"])
    sid, result, meta = _turn(t, prompt)
    t, reason = _finish_turn(tid, sid, result, meta, log)
    from spine.comms import notify
    notify.card_event(t, reason)
    return t


# -- MACHINE tasks: the board reaches the PC, not just the repo --------------
# A machine card is a card whose workplace is a REAL directory on this Windows
# machine instead of a git worktree - the shape adopt_session(mode="continue")
# already used, made first-class so the chat can DELEGATE anything that isn't
# repo work ("open X", "sort these files", "why is the printer offline") instead
# of refusing it. The chat still executes nothing itself; it dispatches the
# agent that does, exactly like resolve_conflict dispatches a worker to edit.
#
# What is deliberately NOT weakened: auth (owner-gated at the chat action),
# audit (filed/turn/done events + the flight recorder, same as any card),
# economics (every turn priced), and gate-before-review - a machine card has no
# branch and NEVER merges to main, so the code-landing gate is untouched. Its
# gate is the owner's own accept, which is the stricter human one.

MACHINE_BRANCH = "(machine)"


def machine_policy():
    """Owner policy for machine tasks. Defaults are permissive-for-the-owner by
    design (it is his own PC, and a blocked chat is the bug we are fixing);
    house rules may RESTRICT - never the other way round, per the charter.
      policy.machine {enabled, roles, roots, perm}
        enabled: false switches the capability off entirely
        roles:   who may dispatch machine work (default owner only)
        roots:   [] = the whole machine; else allowed parent directories
        perm:    driver permission mode (headless needs bypassPermissions to be
                 able to run commands at all - an unanswerable prompt IS a block)"""
    from spine.storage import events
    p = dict((events.settings().get("policy") or {}).get("machine") or {})
    p.setdefault("enabled", True)
    p.setdefault("roles", ["owner"])
    p.setdefault("roots", [])
    p.setdefault("perm", "bypassPermissions")
    return p


def machine_root_ok(cwd):
    """(ok, reason). Empty roots = the whole PC is in scope (the default)."""
    roots = machine_policy().get("roots") or []
    if not roots:
        return True, ""
    c = os.path.normcase(os.path.abspath(cwd))
    for r in roots:
        r = os.path.normcase(os.path.abspath(r))
        if c == r or c.startswith(r + os.sep):
            return True, ""
    return False, ("'%s' liegt ausserhalb der erlaubten Ordner (policy.machine.roots: %s)"
                   % (cwd, ", ".join(roots)))


def new_machine_task(cwd, task, actor="owner", priority="medium", description="",
                     dispatch=True, driver="claude-desktop", value=None, model=""):
    """File (and by default start) a task that runs ON THIS MACHINE in `cwd`.
    Same card, same audit, same economics - only the workplace differs.

    Driver defaults to claude-desktop (windows-mcp + screen-recording), NOT plain
    claude: a machine task's whole point is to control this PC/browser, so the
    agent MUST have the GUI/browser tools. With the plain `claude` driver it can
    only read/write files and ends up talking instead of acting - exactly how the
    "open Chrome, log into Play Console, upload the AAB" card drifted and stuck."""
    from spine.storage import events
    pol = machine_policy()
    if not pol.get("enabled", True):
        raise RuntimeError("machine tasks are switched off (policy.machine.enabled=false)")
    # a machine task with a driver that lacks windows-mcp is toolless by
    # construction; fall back to claude-desktop rather than silently strand it.
    dcfg = (events.settings().get("drivers") or {}).get(driver) or {}
    if "mcp__windows-mcp__*" not in (dcfg.get("allowed_tools") or []):
        driver = "claude-desktop"
    cwd = os.path.abspath(os.path.expandvars(os.path.expanduser(cwd or os.path.expanduser("~"))))
    if not os.path.isdir(cwd):
        raise RuntimeError("no such directory on this machine: %s" % cwd)
    ok, why = machine_root_ok(cwd)
    if not ok:
        raise RuntimeError(why)
    t = new_track(cwd, MACHINE_BRANCH, task, lane="backlog", actor=actor,
                  priority=priority, description=description, driver=driver,
                  value=value, model=model, perm=pol.get("perm", "bypassPermissions"))
    def _mark(tt):
        tt["machine"] = True
        tt["worktree"] = cwd         # the driver's cwd - a real folder, no worktree
    cur = _mutate(t["id"], _mark) or t
    from spine.ops.actionlog import ActionLog
    ActionLog(cur["run_dir"]).log("note", "MACHINE task filed - workplace %s (by %s)" % (cwd, actor))
    events.emit("machine", cur["id"], action="filed", cwd=cwd, actor=actor)
    if dispatch:
        return move_lane(cur["id"], "working", actor=actor)
    return cur


DIRECT_BRANCH = "(direct)"

def new_direct_task(repo, task, actor="owner", priority="medium", description="",
                    dispatch=True, value=None, model="", driver="claude"):
    """Paseo-style DIRECT build card: the repo working tree ITSELF is the
    workplace - no worktree, no branch, no merge. Rides the machine path end to
    end (machine=True: _start_machine dispatches into the folder, _accept_machine
    accepts without a merge), differing from new_machine_task in exactly two ways:

    - the workplace is the REPO ROOT, so the repo's own CLAUDE.md, hooks and
      loop-state machinery apply to the agent for free (setting_sources project);
    - the driver stays the plain coding `claude` (machine tasks force
      claude-desktop for GUI reach) - a direct build needs the repo tools, not
      the mouse, and MUST NOT take the single desktop lock while it compiles.

    The cost is REGISTERED, not hidden (daemon/debt.py 'direct-build-no-gate'):
    a direct card edits the shared tree with no gate-before-review and no
    isolation - Paseo semantics, chosen by the owner for solo direct building.
    Two direct cards on the same tree are serialized in _turn (bounded queue,
    same pattern as the desktop lock) so they cannot edit blind over each other.
    Gated by the same policy.machine switch/roles as machine work."""
    from spine.storage import events
    pol = machine_policy()
    if not pol.get("enabled", True):
        raise RuntimeError("direct tasks are switched off (policy.machine.enabled=false)")
    repo = os.path.abspath(os.path.expandvars(os.path.expanduser(repo)))
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise RuntimeError("not a git repo (direct builds edit a repo's working tree): %s" % repo)
    ok, why = machine_root_ok(repo)
    if not ok:
        raise RuntimeError(why)
    t = new_track(repo, DIRECT_BRANCH, task, lane="backlog", actor=actor,
                  priority=priority, description=description, driver=driver,
                  value=value, model=model, perm=pol.get("perm", "bypassPermissions"))
    def _mark(tt):
        tt["machine"] = True         # ride the no-worktree dispatch/accept path
        tt["direct"] = True          # serialized per-tree in _turn; shown as direct
        tt["worktree"] = repo        # the driver's cwd - the LIVE tree, no copy
    cur = _mutate(t["id"], _mark) or t
    from spine.ops.actionlog import ActionLog
    ActionLog(cur["run_dir"]).log(
        "note", "DIRECT build filed - workplace is the live tree %s (by %s)" % (repo, actor))
    events.emit("machine", cur["id"], action="filed_direct", cwd=repo, actor=actor)
    if dispatch:
        return move_lane(cur["id"], "working", actor=actor)
    return cur


def _start_machine(t):
    """Dispatch a machine card: no worktree, no branch - just open the session in
    its directory and run the first turn there."""
    from spine.storage import events
    tid = t["id"]
    cwd = t.get("worktree") or t.get("repo")
    if not cwd or not os.path.isdir(cwd):
        raise RuntimeError("machine task has no working directory: %r" % cwd)
    from spine.ops.actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "DISPATCHED (machine) -> %s" % cwd)
    log.log("steer", t["task"])
    log.log("turn", "Turn gestartet", event="started")
    events.emit("lane", tid, frm=t.get("lane"), to="working")

    def _begin(tt):
        tt["worktree"] = cwd; tt["lane"] = "working"; tt["status"] = "running"
    t = _mutate(tid, _begin) or t
    prompt = t["task"]
    if t.get("description"):
        prompt += "\n\n" + t["description"]
    if t.get("attachments"):
        prompt += "\n\nAttached files (read them as needed): " + ", ".join(t["attachments"])
    sid, result, meta = _turn(t, prompt)
    t, reason = _finish_turn(tid, sid, result, meta, log)
    from spine.comms import notify
    notify.card_event(t, reason)
    return t


# -- the card's RESULT, persisted at accept -----------------------------------
# The snapshot only surfaced last_reply while a card was needs_you; once
# accepted, its result text vanished from the PM's view - so an owner decision
# the card's final reply had long answered resurfaced as "open" in the plan
# triage. Folded into the track at EVENT TIME (the accept) by the two accept
# mutators (move_lane / _accept_machine) - the one place a card finishes.


# Pays debt [legacy-outcome-on-read]. Cards accepted BEFORE the outcome field
# existed never ran _record_outcome, so their result must be reconstructed from
# the frozen last_reply ONCE (daemon start) instead of re-derived on every
# snapshot read. extract_outcome demonstrably misfires on multi-sentence
# replies - a reply that OPENS with an aside stamps the aside as the result
# (the chatfork card led with "Verstanden fuer naechstes Mal..." instead of
# the actual answer). So this backfill was NOT adopted blindly: an agent
# reviewed ALL 44 legacy done cards against their full final replies
# (2026-08-12, card chat-fix--sessions-extract-ou). Where the heuristic hit
# the core, its value is used; the misses below carry a hand-written outcome.
# "" = the reply holds no result at all (cancelled turn, usage-limit banner,
# lost context) - better an empty line than a nonsense one.
_OUTCOME_BACKFILL_REVIEWED = {
    "20260811-153456-chatfork":
        "Kailashs Tester-Zusage steht: seine Gruppe appclosedtesting@googlegroups.com "
        "ist neben helmdeck-testers in der Play Console eingetragen und zur "
        "Google-Pruefung eingereicht; Opt-in-Link fuer seine 63 Tester verschickt "
        "(bis zu 91 Tester gesamt).",
    "20260728-232103-req-zombie-running-status":
        "Startup zombie sweep shipped (b69c141, e9e6698): sessions.sweep_zombies + "
        "drivers.has_session clear stale 'running' cards on daemon start, with test.",
    "20260728-205508-night-pay-debt-nightshift":
        "Limit-signal fix prepared in the worktree (driver signal patch, debt flip, "
        "tests, workorder); python/git were permission-gated in that session, so "
        "verify+commit were handed to the owner/harness.",
    "20260728-095049-req-dispatch-failure-is-invi":
        "Dispatch failure is visible now: filing a card against a non-git folder "
        "returns an immediate 'repo is not a git repository' error instead of a "
        "silent backlog fallback (7a4c9e7, test_dispatch_visibility.py green).",
    "20260728-094539-req-add-headless-unit-tests":
        "Driver unit tests rewritten against the streaming _ClaudeSession (new "
        "stream-events fixture, stale one removed), committed 1260272; "
        "pytest ops/tests/unit -> 35 passed, fully headless.",
    "20260727-220243-adopt-34656ce4":
        "Kartenansicht auf Overview-first umgebaut: Tab 'Overview' (Status-Chips, "
        "Description zuerst, Worker-Digest, editierbare Felder + Rewind), Tab 'Chat' "
        "mit Transkript+Composer; der APK-Build blieb permission-blockiert.",
    "20260728-094539-req-confirm-legacy-8140-fal":
        "Legacy :8140 UI is a pure redirect now: /, /classic, /recorder, /dashboard "
        "all 302 to the :3300 web UI, old templates deleted, auth intact (/tracks "
        "still 401); merge conflicts resolved marker-free.",
    "20260728-094539-req-one-command-check-script":
        "ops/tools/check_all.sh mirrors the loop in one command (compile+tsc+lint+unit, "
        "8 checks green), repointed at app/ after the Expo cutover; test_drivers.py "
        "conflict resolved by taking expo-migration's superset (482e0ec).",
    "20260803-222549-chat-pm-coordinator-resilienc":
        "PM coordinator resilience shipped: on a blocker/bounce the PM classifies, "
        "delegates a fix and re-submits (2 tries) before escalating with an unblock "
        "proposal; closing debt.py conflict resolved (7b467c2, gate PASS).",
    "20260803-004026-pm-relay-pairing-hardening":
        "Relay pairing hardening landed: deterministic pairing-code lifecycle + "
        "reconnect/backoff, pinned by the pairing-lifecycle suite (gate 6/6 on the "
        "merged tree); final merge with main was a semantic no-op, resolved marker-free.",
    "20260728-094539-req-remove-committed-google":
        "Assessment: the committed Google service-account key is a live, non-expiring "
        "credential in git history since 2024-05-23; repo is private (3 collaborators) "
        "and nothing references it, but it must be revoked in GCP IAM.",
    "20260803-212935-pm-launch-karten-auf-mode-a":
        "Root cause: same-second card-id collision - INSERT OR REPLACE silently "
        "overwrote the first card (audit + economics lost). Fixed via "
        "sessions._unique_id (9297069); the 'unresolved conflict' was gate "
        "flakiness from that bug, gate now PASS (9).",
    "20260803-233536-pm-store-listing-paket-date":
        "Store listing package intact (ops/docs/store/* + privacy page in relay.py); "
        "chat.tsx conflict resolved by combining main's ChatBody structure with the "
        "i18n fix, 5 merged-in untranslated strings fixed; i18n lint 699 keys PASS, "
        "gate 14/14.",
    "20260804-090522-pm-mode-wert-an-die-policy":
        "Refused as written, with proof: rewriting mode on accepted cards would "
        "falsify the measured automation ratio, and the premise was a misdiagnosis "
        "(shown from the event log) - 'auto' is a completion statistic, not a "
        "dispatch mode. Gate PASS (14).",
    "20260806-190555-paseo-p1-runtime":
        "P1 Runtime-Haertung geliefert (c770ef8); die vier Gate-Bounces entlarvten "
        "einen Harness-Bug: gate_failed wird nie persistiert, darum erreichte der "
        "Gate-Output den Worker strukturell nie (betrifft auch merge_report und "
        "Modell-Eskalation).",
    "20260806-190555-paseo-p2-notify":
        "P2 notify shipped (41fa92a); self-review fixed 4 more defects: auto-accept "
        "could merge a still-asking card (now sessions.is_delivered), PM push "
        "bypassed the presence policy, injected prompts rendered as owner messages, "
        "bg watcher ran inline.",
    "20260803-002954-stream-backend": "",
    "20260808-053628-req-fix-dashboard-zu-berf": "",
    "20260808-160412-machine": "",
}


def backfill_outcomes():
    """One-shot outcome backfill for pre-outcome done cards, run at daemon
    start (next to apply_board_directives - same repo-data-applied-once shape).
    KEY PRESENCE marks a migrated card, so '' is a valid stamped outcome and
    each card is visited exactly once across restarts. Reviewed overrides beat
    the heuristic; everything else takes extract_outcome(last_reply). New
    accepts persist their outcome at event time and are never touched here."""
    stamped = 0
    for t in _load():
        if t.get("lane") != "done" or "outcome" in t:
            continue
        tid = t["id"]
        out = _OUTCOME_BACKFILL_REVIEWED.get(tid)
        if out is None:
            out = extract_outcome(t.get("last_reply"))

        def _stamp(tt):
            if "outcome" in tt:
                return False   # lost the race to an accept mutator - theirs wins
            tt["outcome"] = out
        if _mutate(tid, _stamp) is not None:
            stamped += 1
    return stamped


def _accept_machine(t, lane, actor, log):
    """Review/Done for a machine card. There is no branch to gate or merge, so
    Review RESTS it for the owner to judge and Done records the acceptance
    economics. The repo deploy hook does NOT run for a real machine/PC-folder
    card (nothing landed in a repo) - but DOES run for a direct card (worktree
    == the live repo tree, so a Done here is the first/only time this specific
    accept path deploys it, for an owner who accepts by hand instead of
    relying on fast-track's own auto-ship)."""
    from spine.storage import events
    if lane == "review":
        log.log("note", "REVIEW (machine): erledigt auf dem Rechner - wartet auf deine Abnahme.")

        def _submit(tt):
            tt["status"] = "submitted"; tt["lane"] = "review"
            tt["review_report"] = ("Maschinen-Aufgabe - kein Branch, kein Merge. Pruefe das "
                                   "Ergebnis auf dem Rechner und nimm die Karte ab.")
        t = _mutate(t["id"], _submit) or t
        _say_card(t, _i18n.t("say.machineReview"))
        return dict(t, review_preview=True, merge_kind="machine")
    events.emit("touch", t["id"], touch="review", actor=actor)
    te = [e for e in events.read_events() if e.get("track") == t["id"]]
    mode = events._completion_mode(te, t.get("turns"))
    events.emit("done", t["id"], mode=mode, ai_cost=t.get("ai_cost", 0.0),
                value=t.get("value"), models=t.get("models", []),
                tokens_in=t.get("tokens_in", 0), tokens_out=t.get("tokens_out", 0))
    events.emit("machine", t["id"], action="accepted", cwd=t.get("worktree") or "", actor=actor)
    log.log("note", "ACCEPTED (machine, %s) - AI $%.4f, value %s"
            % (mode, t.get("ai_cost", 0.0), t.get("value")))

    def _accept(tt):
        tt["status"] = "accepted"; tt["mode"] = mode; tt["lane"] = "done"
        _record_outcome(tt)
    t = _mutate(t["id"], _accept) or t
    events.emit("lane", t["id"], frm="review", to="done")
    if t.get("direct"):
        from cells.engineer.lanemachine import _repo_hook
        _repo_hook(t, "deploy")   # something DID land in a repo for a direct card
    _say_card(t, _i18n.t("say.machineAccepted"))
    from spine.comms import notify
    notify.card_event(t, "done")
    try:
        from cells.pm import pm
        pm.on_card_done(t["id"])   # re-judge the golden triangle at event time
    except Exception:
        pass
    return t
