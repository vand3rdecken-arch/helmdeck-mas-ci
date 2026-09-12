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
import re
import shutil
import time

from spine.ops.runs import REC
from spine.registry import i18n as _i18n

from spine.storage.trackstore import (_load, _save_track, _find, _slug, _unique_id,
                                      _mutate, _card_branch)
from spine.git.gitutil import (_git, _git_try, _branch_exists, _git_state_broken,
                     _owned_worktree, _seed_worktree, _base_ref,
                     _worktree_for, _worktree_of_branch)
from cells.engineer.cards.turnrunner import _turn, _finish_turn, is_delivered
from cells.engineer.cards.lanemachine import _gate, _say_card, move_lane
from cells.engineer.cards.devport import _alloc_dev_port
from spine.turn.blockers import blocker
from spine.turn.outcomes import extract_outcome, _record_outcome

# same env var as sessions.DEFAULT_PERM - process-idempotent, safe to read
# independently rather than importing sessions (would cycle).
DEFAULT_PERM = os.environ.get("HELMDECK_PERM", "auto")   # 2026-09-12: Claude auto mode - "nur fragen wenn notwendig"


def _repo_default_kind(repo):
    """The card kind THIS REPO's template declares, or "" if it declares none.

    THE one reader of `projects.resolve(repo)['card_kind']` (debt
    repo-template-card-kind-unwired: the value existed, was surfaced, and was
    consumed by nobody - a setting that reported success and changed nothing).

    Total by construction: a repo with no project record, an unreadable db, a
    template that was deleted - all mean "this repo expresses no preference",
    which is the pre-template behavior. A broken record may cost the default,
    never the card."""
    try:
        from spine.ops import projects
        return (projects.resolve(repo) or {}).get("card_kind") or ""
    except Exception as e:                                       # noqa: BLE001
        print("dispatch: repo card_kind for %s unreadable (%s) - using the "
              "per-card default" % (repo, e), flush=True)
        return ""


def _direct_ok(repo):
    """May a card in `repo` actually run on the live tree? (ok, why_not, policy).

    The same three guards new_direct_task enforces - the policy switch, a real
    git repo, the allowed root. They are checked HERE too because the repo
    default reaches the live tree without going through that function, and a
    default that quietly bypassed a policy switch would be a hole, not a
    convenience. The policy dict comes back with the answer so the caller can
    also take its `perm` - live-tree work is governed by policy.machine, and a
    card that landed there by repo default must run under the same rules as one
    that got there by name."""
    try:
        pol = machine_policy()
        if not pol.get("enabled", True):
            return False, "policy.machine.enabled=false", pol
        if not os.path.isdir(os.path.join(repo, ".git")):
            return False, "kein git-Repo: %s" % repo, pol
        ok, why = machine_root_ok(repo)
        if not ok:
            return False, why, pol
        return True, "", pol
    except Exception as e:                                       # noqa: BLE001
        return False, "Direct-Vorpruefung fehlgeschlagen: %s" % e, {}


def new_track(repo, branch, task, perm=DEFAULT_PERM, lane="working", client="",
              value=None, driver="claude", actor="owner", priority="medium", due="",
              model="", attachments=None, project_id=None, billing="fixed", rate=None,
              description="", card_kind="", example=False):
    """File a request. lane=backlog stores it un-started (no worktree, no session);
    lane=working starts the branch session immediately. value = what the
    deliverable is worth (settings default when omitted) - set at intake so
    margin is computable at acceptance. project_id assigns the card to a
    fixed-price/T&M project (projects.py); its own `value` then stops feeding
    the totals - the project's billing does (events.metrics).

    `card_kind` ("new_track" | "new_direct_task") is the caller stating the
    entry point OUTRIGHT. Left empty, the REPO decides via its template - this
    is the one place a card is born, so it is the one place that question is
    answered (see _repo_default_kind).

    `example` (accounts-boards-prd phase 3) marks the one guided onboarding
    card seed_example_card files at setup: set HERE, at birth, so it is never
    a card that later "becomes" inert - lanemachine._move_lane refuses to
    dispatch it and every economics/planning read site skips it, all keyed
    off this one flag."""
    from spine.storage import events
    from spine.agent import turnopts
    repo = os.path.abspath(repo)
    tracks = _load()
    tid = _unique_id(_slug(branch))
    # WHICH KIND OF CARD THIS IS - decided BEFORE the branch name, because the
    # two answers are the same decision: a live-tree card carries DIRECT_BRANCH
    # and never gets a derived branch or a worktree.
    #
    # Precedence: an explicit `card_kind`, else the branch sentinel a wrapper
    # already passed (new_direct_task/new_machine_task have chosen by calling
    # at all), else the repo's template. So the repo default only ever fills a
    # silence - it can never override a caller who said what they wanted.
    if branch in (MACHINE_BRANCH, DIRECT_BRANCH):
        kind = "new_direct_task" if branch == DIRECT_BRANCH else "new_machine_task"
    else:
        kind = card_kind or _repo_default_kind(repo)
    if kind == "new_direct_task" and branch != DIRECT_BRANCH:
        # The repo (or the caller) asked for the live tree. Honour it only if
        # the guards allow it - and if they do not, fall back to the isolated
        # worktree LOUDLY. Silently building something other than what the
        # template promises is the failure mode templates exist to prevent.
        ok, why, pol = _direct_ok(repo)
        if ok:
            branch = DIRECT_BRANCH
            # Live-tree work runs under policy.machine's permission mode. A
            # direct card has to be able to COMMIT its own work; left on the
            # worktree default (acceptEdits) the git write is gated and the card
            # stalls with nothing saying why. Only filled when the caller did
            # not ask for a specific mode - an explicit perm still wins.
            if perm == DEFAULT_PERM:
                perm = pol.get("perm", "auto")
        else:
            kind = "new_track"
            print("dispatch: %s wants live-tree cards (Vorlage card_kind="
                  "new_direct_task) but %s - Karte laeuft im Worktree"
                  % (repo, why), flush=True)
    # ONE owner for the card's branch name. Callers pass a HUMAN STEM ("chat-"
    # + the request, "req-" + the request, "connector-" + name); what actually
    # goes on the board is derived here from the card id and verified free, so
    # no caller can hand in a name that already addresses a live card's
    # worktree. Machine and direct cards keep their fixed marker - they have no
    # branch and no worktree by construction and never reach _worktree_for.
    if branch not in (MACHINE_BRANCH, DIRECT_BRANCH):
        branch = _card_branch(repo, branch, tid)
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
         "example": bool(example),
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    # THE DIRECT-CARD FIELDS, set in exactly one place. They used to be written
    # after the fact by new_direct_task's own _mutate; folding them in here at
    # BUILD time makes this function the single owner of the shape, so a card
    # born from the repo default and one born from the explicit entry point are
    # the same object rather than two lookalikes maintained in parallel.
    if kind == "new_direct_task":
        t["machine"] = True      # ride the no-worktree dispatch/accept path
        t["direct"] = True       # serialized per-tree in _turn; shown as direct
        t["worktree"] = repo     # the driver's cwd - the LIVE tree, no copy
    from spine.ops.actionlog import ActionLog
    ActionLog(run_dir).log("note", "REQUEST filed: %s (branch %s)" % (task, branch))
    events.emit("filed", tid, branch=branch, value=t["value"], actor=actor, driver=t["driver"])
    _save_track(t)
    # example cards never dispatch, even if a future caller mis-files one
    # straight into lane="working" - the same law _move_lane enforces on
    # every later move, held here too so birth can't be the one path around it.
    if lane == "working" and not example:
        t = _start(tid)
    return t


_EXAMPLE_TITLE = "So funktioniert HelmDeck"
_EXAMPLE_BODY = (
    "Das ist eine Beispielkarte - keine Sorge, sie startet nie einen Agenten "
    "und kostet nichts. Sie zeigt nur, wie eine Karte durchs Board wandert:\n\n"
    "1. Backlog - hier liegt sie jetzt, angefragt, aber noch nicht gestartet.\n"
    "2. Working - ein Agent bekommt einen eigenen, isolierten Arbeitsbereich "
    "(worktree) und einen eigenen Branch, damit nichts sich in die Quere kommt.\n"
    "3. Review - fertige Arbeit läuft zuerst durchs Gate (Tests/Checks); nur "
    "grün darf weiter, rot geht mit einer Punktliste zurück nach Working.\n"
    "4. Done - du nimmst ab, die Arbeit wird ins Hauptrepo gemerged.\n\n"
    "Du kannst diese Karte jederzeit löschen, wenn du sie nicht mehr brauchst."
)


def seed_example_card(actor="system"):
    """The ONE guided onboarding card owner first-run seeds alongside the
    default board (accounts-boards-prd phase 3, PRD section 4.1): explains the
    lane machine without touching it, `example=True` so it is inert by
    construction wherever a card is inert-checked (lanemachine._move_lane,
    events.metrics, the PM's dispatcher/planning, Henry's snapshot - PRD
    section 8's risk item, grep-verified across all of them in this phase).

    Filed against the daemon's OWN repo root: it never dispatches, so which
    repo it names is otherwise moot, and REPO_ROOT is guaranteed to be a real
    git checkout on every install (unlike an owner's project repo, which may
    not exist yet at first-run). card_kind is pinned to "new_track" so this
    repo's own template (if it names one) can never route it onto the
    live-tree/direct path - an example card must always look like the
    ordinary worktree shape a newcomer will actually use."""
    from daemon.paths import REPO_ROOT
    return new_track(REPO_ROOT, "example", _EXAMPLE_TITLE, lane="backlog",
                     description=_EXAMPLE_BODY, value=0.0, billing="none",
                     driver="", actor=actor, priority="low", card_kind="new_track",
                     example=True)


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
    p.setdefault("perm", "auto")
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
                  value=value, model=model, perm=pol.get("perm", "auto"))
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
                    dispatch=True, value=None, model="", driver="claude",
                    fast_track=False):
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
    # A path INSIDE a repo names the repo: walk up to the toplevel instead of
    # rejecting it. Henry's chat turns run with cwd=DAEMON_ROOT (henry_pmode's
    # docstring), so a direct task minted from board chat arrived here as
    # <repo>\daemon and bounced with "not a git repo" (owner screenshot
    # 2026-09-02 14:33) - about a directory that sits two levels inside a
    # perfectly good one. Derived from the filesystem's own signal (the .git
    # dir), same answer `git rev-parse --show-toplevel` gives, without needing
    # git on PATH. machine_root_ok below judges the RESOLVED root, so the
    # allowlist still sees the real repo, not the subdirectory.
    _cur = repo
    while not os.path.isdir(os.path.join(_cur, ".git")):
        _parent = os.path.dirname(_cur)
        if _parent == _cur:      # filesystem root - genuinely no repo anywhere above
            raise RuntimeError("not a git repo (direct builds edit a repo's "
                               "working tree): %s" % repo)
        _cur = _parent
    repo = _cur
    ok, why = machine_root_ok(repo)
    if not ok:
        raise RuntimeError(why)
    t = new_track(repo, DIRECT_BRANCH, task, lane="backlog", actor=actor,
                  priority=priority, description=description, driver=driver,
                  value=value, model=model, perm=pol.get("perm", "auto"))
    # machine/direct/worktree are NOT set here any more: passing DIRECT_BRANCH
    # already told new_track which kind of card this is, and it writes those
    # three at build time (one owner for the shape - see its comment). What is
    # left is the one flag only this entry point can express.
    def _mark(tt):
        if fast_track:
            # ship-on-turn-end from birth (sessions._maybe_fast_track_ship_direct):
            # autocommit + deploy hook, no gate/merge - the quick-fix class the
            # owner triages in chat (2026-08-29). Same registered debt
            # fast-track-no-gate as the after-the-fact flag flip.
            tt["fast_track"] = True
    cur = (_mutate(t["id"], _mark) or t) if fast_track else t
    from spine.ops.actionlog import ActionLog
    ActionLog(cur["run_dir"]).log(
        "note", "DIRECT build filed - workplace is the live tree %s (by %s)" % (repo, actor))
    events.emit("machine", cur["id"], action="filed_direct", cwd=repo, actor=actor)
    if dispatch:
        return move_lane(cur["id"], "working", actor=actor)
    return cur


def ship_process(repo):
    """This project's SHIP PROCESS - the text of rule.ship.process (spine/
    registry/behavior.py, block `ship`), resolved for the repo's project key.
    Owner decree 2026-09-12: the ship process is config per project, in the
    db, because every software ships differently; the ship card's brief is
    the METHOD, this is the WHERE/WHAT. Returns "" when the project set none
    (the brief then tells the card to read DEPLOY.md/README itself). Never
    raises - a broken row must not stop a landing from filing its card."""
    try:
        from spine.storage import projectconfig
        got = projectconfig.resolve("rule.ship.process.all", projectconfig.project_key(repo))
        return (got.get("value") or "").strip()
    except Exception:                                          # noqa: BLE001
        return ""


def new_ship_task(repo, kind, actor="henry", origin_card=None, dispatch=True):
    """Owner decree 2026-09-09 (18:04 correction): a ship runs as its own
    visible board card - lane, timeline, steerable, self-correcting like any
    other card - instead of an invisible deploy-hook subprocess after an
    accept. Henry's ship DECISION (kind=ota|native,
    cells/copilot/broker/henry_broker.py's `ship` verb) spawns this; the
    card's own agent turn (cells/engineer/harness/agents/ship-worker.md) does
    DIAGNOSE -> EXECUTE -> VERIFY as its own reasoning and ends its reply
    with a literal 'SHIP: OK'/'SHIP: FAILED' verdict line that
    sessions._maybe_ship_card_close reads to self-close it on success.

    Rides the SAME no-worktree direct-build shape new_direct_task uses (no
    branch, no merge, live repo root as workplace, bypassPermissions) -
    shipping needs the real git refs / build artifacts / relay distribution a
    worktree copy would not have. `dispatch=False` here: `ship_kind` must be
    set BEFORE the first turn is dispatched (we call move_lane ourselves,
    after marking) so drivers._agent_for already sees it on that very first
    turn and speaks ship-worker.md, not machine-worker.md - a race that would
    otherwise strand the card's first (and often only) turn on the wrong brief.

    kind="decide" (owner decree 2026-09-12, "ship als Karte - damit es losgehen
    kann und selber Infos sammeln und nachdenken"): the DECISION itself runs
    inside this card. Until now a landing escalated to Henry's one-shot
    judgement turn, which read exactly what ops/tools/ship_facts.py printed
    (phone channels only) - it could not discover that the desktop-mac
    workflow had been failing on GitHub billing for two days, because no
    fact it was handed said so, and a judgement turn has neither the time
    nor the brief to go looking. A card has hands, auto-mode permissions,
    gh/git/relay reach and as many turns as it needs: it researches, decides
    none|ota|native, executes, verifies, and closes itself ('SHIP: NONE' is
    a deliberate non-ship and closes too). Henry stays what he is - the
    exception broker for a card that parks needs_you.

    dispatch=False returns the marked card WITHOUT starting its first turn
    (lanemachine.request_ship_decision files synchronously for dedup, then
    dispatches on its own thread so the origin card's accept never blocks on
    a ship that may take twenty minutes)."""
    if kind not in ("decide", "ota", "native"):
        raise ValueError("new_ship_task: kind must be 'decide', 'ota' or 'native', got %r" % kind)
    if kind == "decide":
        task = ("Ship-Entscheidung + Ausfuehrung. Recherchiere selbst, entscheide "
                "none|ota|native, fuehre aus, verifiziere - siehe Brief. Beende die "
                "letzte Antwort mit genau einer Zeile 'SHIP: OK', 'SHIP: NONE' oder "
                "'SHIP: FAILED'.")
        desc = "Ausgeloest von einer Landung%s - entscheidet selbst, ob und wie geshippt wird." % (
            (" (Karte %s)" % origin_card) if origin_card else "")
    else:
        task = ("Ship (%s). Diagnose, execute, verify - see your brief. End your "
               "final reply with exactly the line 'SHIP: OK' or 'SHIP: FAILED'." % kind)
        desc = "Ausgeloest von Henrys Ship-Entscheid (%s)%s." % (
            kind, (" fuer Karte %s" % origin_card) if origin_card else "")
    proc = ship_process(repo)
    if proc:
        task += "\n\nSHIP-PROZESS DIESES PROJEKTS (Settings > Harness > Ship, pro Projekt):\n" + proc
    else:
        task += ("\n\nSHIP-PROZESS: fuer dieses Projekt ist keiner hinterlegt (Settings > "
                 "Harness > Ship). Lies DEPLOY.md / README / settings.repo_hooks.deploy "
                 "und nenne im Bericht, was du nicht finden konntest.")
    t = new_direct_task(repo, task, actor=actor, priority="high",
                        description=desc, dispatch=False, driver="claude")

    def _mark(tt):
        tt["ship_kind"] = kind
        if origin_card:
            tt["ship_origin"] = origin_card
    cur = _mutate(t["id"], _mark) or t
    from spine.ops.actionlog import ActionLog
    ActionLog(cur["run_dir"]).log(
        "note", "SHIP card filed (%s) - workplace is the live tree %s" % (kind, repo))
    if not dispatch:
        return cur
    return move_lane(cur["id"], "working", actor=actor)


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
    # The SAME landing branch as the steer path (sessions._after_turn_land):
    # ship card -> self-close on its verdict; direct card -> autocommit + ship
    # decision to Henry; worktree fast-track -> convert. Was ship-cards-only
    # here until 2026-09-12, so a direct card finishing in its first turn
    # never landed (backlog/direct-cards-never-land). Lazy import: sessions
    # imports this module at load time. MUST reassign t: a ship card's
    # move_lane writes the STORED record, not this local variable.
    from cells.engineer.cards import sessions as _sessions
    t = _sessions._after_turn_land(t, log)
    return t


def _maybe_ship_card_close(t, log):
    """Turn-end hook for a Ship card (owner decree 2026-09-09, 18:04
    correction: ship runs as its own visible board card, not an invisible
    deploy-hook subprocess). cells/engineer/harness/agents/ship-worker.md
    instructs the card's OWN agent turn to diagnose/execute/verify itself
    and end its reply with a literal 'SHIP: OK'/'SHIP: FAILED' line - this
    is the ONE place that verdict becomes a real board state. Lane
    transitions stay code-owned everywhere else in this daemon (no verb
    lets an agent call move_lane itself - the HANDS discipline,
    cells/copilot/broker/henry_broker.py's docstring); this hook is the
    equivalent for a ship card's own conclusion, triggered from code
    immediately at turn-end rather than by an external actor noticing.

    Called from TWO sites - _start_machine above (a ship card's first turn)
    and sessions.py's steer-completion path (a retry after a FAILED verdict)
    - because those are genuinely separate completion paths in this daemon
    (test_fast_track_direct.py pins the same split for fast-track's own
    ship-on-turn-end hooks: 'the dispatch turn itself never ships' there
    either). One function, not two copies that could drift apart.

    A FAILED verdict (or a crash mid-turn with no verdict line at all) does
    NOTHING extra - the card is already exactly where an ordinary unfinished
    turn parks it (needs_you, lane unchanged): visible on the board,
    steerable by the owner or Henry, same as any other stuck card.

    Returns the FRESH track dict when it moved the lane (move_lane's own
    write is the ground truth, same reasoning henry_broker's `move` verb
    already applies), else `t` unchanged - the caller must use this return
    value, not its own now-stale `t`, or the lane flip is invisible to
    whoever called this."""
    reply = t.get("last_reply") or ""
    # 'SHIP: NONE' (a decide card that researched and found nothing to ship,
    # 2026-09-12) is as final as OK - the card's reply holds the why, and a
    # deliberate non-ship left on the board as needs_you would read as stuck.
    if not re.search(r"^SHIP:\s*(OK|NONE)\s*$", reply, re.M):
        return t
    try:
        r = move_lane(t["id"], "done", actor="ship-agent")
    except Exception as e:
        log.log("note", "Ship-Karte meldete OK, aber die Selbst-Abnahme stuerzte ab: %s" % str(e)[:200])
        return t
    if (r or {}).get("lane") != "done":
        reason = (r or {}).get("merge_report") or (r or {}).get("gate_report") or "unbekannt"
        log.log("note", "Ship-Karte meldete OK, aber die Selbst-Abnahme kam nicht an "
                "(blieb auf %s) - Grund: %s" % ((r or {}).get("lane"), str(reason)[:300]))
    return r or t


# -- REMOTE DEVICE tasks: a team member's own PC executes, the gate stays here
# (ops/docs/backlog/remote-device-execution). A device card is a NORMAL
# worktree/branch card in every respect that matters to lanemachine.py - it
# is filed with new_track exactly like a local card, and it is NEVER marked
# machine/direct/fast_track. That is the one hard constraint the whole
# feature rests on: those three flags are owner-only convenience paths that
# bypass _gate/_merge_to_main by design (each is its own registered debt);
# extending any of them to a team member's device would hand out an
# unreviewed path to main. A device card differs from a local card in
# exactly one way - who runs the turn - and the turn is not run here at all;
# claim_remote_task/submit_remote_result bracket the part a local card does
# inside _turn, with the device doing the work in between.

def new_remote_task(repo, branch, task, device_id, actor, priority="medium",
                    description="", value=None, model=""):
    """File a card for a REGISTERED DEVICE to execute. Stays in `backlog`
    (never dispatch=True/_start_inner - there is no local worktree to open a
    session in yet) with exec_site recording which device owns it. The
    device claims it via claim_remote_task when it next polls."""
    from spine.storage import events
    t = new_track(repo, branch, task, lane="backlog", actor=actor,
                  priority=priority, description=description, driver="claude",
                  value=value, model=model)
    def _mark(tt):
        tt["exec_site"] = "local:" + device_id
    cur = _mutate(t["id"], _mark) or t
    from spine.ops.actionlog import ActionLog
    ActionLog(cur["run_dir"]).log(
        "note", "filed for remote device %s (by %s)" % (device_id, actor))
    events.emit("remote_device", cur["id"], action="filed", device=device_id, actor=actor)
    return cur


_TS_FMT = "%Y-%m-%d %H:%M:%S"


def claim_remote_task(device_id):
    """The oldest backlog card filed for this device, or None. Marks it
    'working'/'running' WITHOUT touching _start_inner - there is no local
    worktree to create; the device is now the one doing the work, and the
    card's worktree field stays empty until submit_remote_result imports it.
    Stamps `claimed_at` (UTC-naive, same format as devices.json's
    created/last_seen) - the one fact sweep_stale_device_claims needs to
    tell a genuinely abandoned claim from a card mid-turn."""
    from spine.storage import events
    candidates = [t for t in _load()
                 if t.get("exec_site") == "local:" + device_id and t.get("lane") == "backlog"]
    if not candidates:
        return None
    t = min(candidates, key=lambda t: t.get("id", ""))
    def _claim(tt):
        tt["lane"] = "working"; tt["status"] = "running"
        tt["claimed_at"] = time.strftime(_TS_FMT)
    cur = _mutate(t["id"], _claim) or t
    events.emit("lane", cur["id"], frm="backlog", to="working")
    events.emit("remote_device", cur["id"], action="claimed", device=device_id)
    return cur


def device_card_status(device_id, tid):
    """Is card `tid` STILL this device's to work on? The cheap poll a mid-turn
    worker uses to notice a reassign/reclaim/revoke WITHOUT waiting for its
    turn to finish (ops/docs/backlog/remote-device-execution PLAN-hardening.md
    Phase E). Returns {"assigned": bool, "reason": str}. `assigned` is False -
    the worker should abandon the turn - when the card was reassigned to
    another device (exec_site changed), reclaimed to backlog (a stale-claim
    sweep, or the card was cancelled), or has already landed. Read-only, no
    mutation. Device revocation is NOT checked here (the token itself stops
    resolving at the auth layer, so the worker's next call 404s regardless);
    this covers the case the token still works but the CARD moved."""
    t = _find(_load(), tid)
    if not t:
        return {"assigned": False, "reason": "card no longer exists"}
    exec_site = t.get("exec_site") or ""
    if exec_site != "local:" + device_id:
        return {"assigned": False, "reason": "card reassigned to another device or cleared"}
    if t.get("lane") != "working" or not t.get("claimed_at"):
        return {"assigned": False, "reason": "card no longer in your working queue (reclaimed/landed)"}
    return {"assigned": True, "reason": ""}


def record_remote_stream(tid, device_id, stream_events):
    """Fold a batch of a device turn's LIVE stream events into the card's
    timeline (ops/docs/backlog/remote-device-execution PLAN-hardening.md
    Phase H) - so the board shows a device turn AS IT HAPPENS, exactly like a
    local card. Reuses spine.agent.drivers.fold_timeline_event (the same
    function the local driver's own pump calls), NOT a fork - a device turn's
    events are the same Claude stream-json events. Only accepts events for a
    card that is STILL this device's own working card (same guard as
    device_card_status), so a stale/reassigned worker cannot keep writing to
    a card that moved. Best-effort per the feed-write discipline: a bad event
    is skipped, never raised - a broken stream must not fail the turn's real
    result, which lands via submit_remote_result regardless. Returns the
    number of events folded."""
    from spine.agent import drivers
    t = _find(_load(), tid)
    if not t:
        raise RuntimeError("no such card: %s" % tid)
    if t.get("exec_site") != "local:" + device_id or t.get("lane") != "working":
        raise RuntimeError("card %s is not this device's active card" % tid)
    run_dir = t.get("run_dir")
    if not run_dir:
        return 0
    n = 0
    for ev in (stream_events or []):
        if not isinstance(ev, dict):
            continue
        try:
            drivers.fold_timeline_event(run_dir, ev)
            n += 1
        except Exception:
            pass   # one malformed event never breaks the batch or the turn
    return n


def sweep_stale_device_claims(claim_ttl_s=None, last_seen_grace_s=180):
    """Return a claimed-but-abandoned card to backlog for the SAME device to
    re-claim (never cross-device - that is an explicit owner action,
    reassign_remote_task below). A claim counts as stale only when BOTH
    signals agree - never a blind clock:
      - claimed_at is older than the TTL (default 1800s), AND
      - the device's last_seen (touched on every queue poll) is older than
        `last_seen_grace_s` - a device still polling (blocked inside one
        long Bash call between polls, say) has NOT gone quiet, so its claim
        is left alone even past the TTL. Only a device that has stopped
        polling entirely gets its claim reclaimed.
    A device with no last_seen at all (never polled since claiming, or
    deleted/revoked) counts as quiet - fails closed toward reclaiming
    rather than leaving a card wedged on a device that may not exist
    anymore."""
    from spine.storage import events
    from spine.auth import devices
    from datetime import datetime
    try:
        ttl = float(claim_ttl_s if claim_ttl_s is not None else
                   ((events.settings().get("policy") or {}).get("device") or {}).get("claim_ttl_s", 1800))
    except (TypeError, ValueError):
        ttl = 1800.0
    now = datetime.strptime(time.strftime(_TS_FMT), _TS_FMT)
    reclaimed = []
    for t in _load():
        exec_site = t.get("exec_site") or ""
        if not exec_site.startswith("local:") or t.get("lane") != "working":
            continue
        claimed_at = t.get("claimed_at")
        if not claimed_at:
            continue   # pre-this-fix card, or already reclaimed once - nothing to judge by
        try:
            age = (now - datetime.strptime(claimed_at, _TS_FMT)).total_seconds()
        except ValueError:
            continue
        if age < ttl:
            continue
        device_id = exec_site[len("local:"):]
        d = devices.get_device(device_id)
        last_seen = (d or {}).get("last_seen")
        if last_seen:
            try:
                quiet = (now - datetime.strptime(last_seen, _TS_FMT)).total_seconds() > last_seen_grace_s
            except ValueError:
                quiet = True
        else:
            quiet = True
        if not quiet:
            continue
        def _release(tt):
            tt["lane"] = "backlog"; tt["status"] = "queued"
            tt.pop("claimed_at", None)
        cur = _mutate(t["id"], _release) or t
        events.emit("lane", cur["id"], frm="working", to="backlog")
        events.emit("remote_device", cur["id"], action="reclaimed", device=device_id)
        try:
            from spine.ops.actionlog import ActionLog
            ActionLog(cur["run_dir"]).log(
                "note", "Device %s war laenger nicht erreichbar - Karte zurueck in "
                        "Backlog, dasselbe Geraet kann sie beim naechsten Connect "
                        "wieder claimen." % device_id)
        except Exception:
            pass
        reclaimed.append(cur["id"])
    return reclaimed


def start_device_claim_sweeper(interval=60):
    """Continuous poller, same shape as lifecycle.start_zombie_reconciler:
    sweep_stale_device_claims is also useful one-shot (called at boot, next
    to sessions.sweep_worktrees), but a card claimed AFTER boot and then
    abandoned needs a running pass to ever be noticed. Idempotent to call
    once; sessions.start_engineer_lifecycle() is only invoked once per boot
    (cells.start_enabled()'s own contract), so no guard needed here beyond
    that."""
    import threading
    def _loop():
        while True:
            time.sleep(interval)
            try:
                reclaimed = sweep_stale_device_claims()
                if reclaimed:
                    print("DEVICE SWEEP: reclaimed %d stale claim(s): %s"
                         % (len(reclaimed), ", ".join(reclaimed)), flush=True)
            except Exception as e:
                print("device claim sweeper error: %s" % e, flush=True)
    threading.Thread(target=_loop, daemon=True).start()


def reassign_remote_task(tid, to_device_id, actor):
    """Owner/operator recovery action (Phase C): move a stuck card off a
    dead device onto a DIFFERENT one the SAME actor owns, or clear
    exec_site entirely (to_device_id falsy) to fall back to a normal
    dispatchable worktree card. Only meaningful while the card is still
    backlog/working with no worktree yet - once a worktree exists the card
    already landed real work through the gate and reassigning its
    executor after the fact would be nonsensical."""
    from spine.storage import events
    from spine.auth import devices
    t = _find(_load(), tid)
    if not t:
        raise RuntimeError("no such card: %s" % tid)
    if not (t.get("exec_site") or "").startswith("local:"):
        raise RuntimeError("card %s is not a remote-device card" % tid)
    if t.get("worktree"):
        raise RuntimeError("card %s already has a landed worktree - nothing to reassign" % tid)
    if to_device_id:
        d = devices.get_device(to_device_id)
        if not d or d.get("owner") != actor:
            raise RuntimeError("no such device of yours: %s" % to_device_id)
    def _reassign(tt):
        if to_device_id:
            tt["exec_site"] = "local:" + to_device_id
        else:
            tt.pop("exec_site", None)
        tt["lane"] = "backlog"; tt["status"] = "queued"
        tt.pop("claimed_at", None)
    cur = _mutate(tid, _reassign) or t
    events.emit("remote_device", tid, action="reassigned",
               to_device=to_device_id or None, actor=actor)
    return cur


def submit_remote_result(tid, bundle_path, actor, device_id=None, usage_meta=None):
    """A device reports a finished branch: import its bundle into the
    card's repo (spine.git.gitutil._import_bundle - verifies + refuses to
    clobber), materialize the now-existing branch as a real local worktree
    via the SAME _ensure_worktree every local card uses, then hand off to
    move_lane('review') UNMODIFIED - from here the card is gated exactly
    like one that was worked locally: _gate runs, GxP's accept_block_reason
    still applies at 'done', nothing about the merge path changes.

    device_id, when given, must match the card's OWN exec_site - a device
    may only submit against a card bound to itself, never another device's.

    Idempotent on the branch already existing: a lost HTTP response after a
    successful import must not turn a retry into a hard "already exists"
    error - _import_bundle's refuse-to-clobber is exactly right for a NEW
    branch colliding with unrelated history, but a re-submit of the SAME
    card's own already-landed branch is not that case. Economics
    (usage_meta) are folded ONLY on the fresh-landing path below, never on
    an idempotent retry - the branch already existing means a prior submit
    already recorded its cost once; recording it again would double-count.

    usage_meta ({"usage", "cost_usd", "models"}, PLAN-hardening.md Phase D):
    what the worker's own claude call reported. Folded via the SAME
    spine.turn.econ._record_econ a local card's turn uses, tagged
    external=True unless the device's own billing_scope is "shared" - see
    _record_econ's docstring for why that tag matters (plan_calibration
    would otherwise divide by an account quota this spend never drew on)."""
    from spine.storage import events
    t = _find(_load(), tid)
    if not t:
        raise RuntimeError("no such card: %s" % tid)
    exec_site = t.get("exec_site", "")
    if not exec_site.startswith("local:"):
        raise RuntimeError("card %s was not filed for remote device execution" % tid)
    if device_id and exec_site != "local:" + device_id:
        # A late submit from a device the card was reassigned AWAY from while
        # it was mid-turn (Phase E). Log it as a named outcome, not just a bare
        # 400 to the caller - an operator watching the card sees WHY a stale
        # result was dropped, not a mystery error.
        events.emit("remote_device", tid, action="stale_submit_rejected",
                   from_device=exec_site[len("local:"):], by_device=device_id)
        raise RuntimeError("card %s is bound to a different device" % tid)
    if not _branch_exists(t["repo"], t["branch"]):
        from spine.git.gitutil import _import_bundle
        _import_bundle(t["repo"], bundle_path, t["branch"])
    elif t.get("lane") in ("review", "done"):
        events.emit("remote_device", tid, action="submit_retry_idempotent", actor=actor)
        return t
    # else: branch already imported but the card never advanced past
    # 'working' (e.g. the daemon restarted between import and move_lane) -
    # fall through and finish the landing without re-importing.
    wt = _ensure_worktree(t)
    external = True
    if usage_meta:
        from spine.auth import devices as _devices
        d = _devices.get_device(exec_site[len("local:"):])
        external = (d or {}).get("billing_scope", "external") != "shared"
    def _land(tt):
        tt["worktree"] = wt
        tt.pop("claimed_at", None)
        if usage_meta:
            from spine.turn.econ import _record_econ
            _record_econ(tt, usage_meta, external=external)
    t = _mutate(tid, _land) or t
    events.emit("remote_device", tid, action="submitted", actor=actor)
    return move_lane(tid, "review", actor=actor)


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
    if t.get("direct") and not t.get("ship_kind"):
        # something DID land in a repo for a direct card - whether it ships is
        # Henry's judgement now (owner decree 2026-09-01), same as every path.
        # EXCLUDES a ship card itself (t["ship_kind"] set, new_ship_task) -
        # without this guard a ship card accepting itself would emit ANOTHER
        # ship-decision escalation, which Henry would judge, which would spawn
        # ANOTHER ship card, forever (owner decree 2026-09-09, 18:04
        # correction introduced ship cards; this card's own existence IS
        # already the answer to "should this ship").
        from cells.engineer.cards.lanemachine import request_ship_decision
        request_ship_decision(t, "direct-accept")
    _say_card(t, _i18n.t("say.machineAccepted"))
    from spine.comms import notify
    notify.card_event(t, "done")
    try:
        from cells.copilot.planning import pm
        pm.on_card_done(t["id"])   # re-judge the golden triangle at event time
    except Exception:
        pass
    return t
