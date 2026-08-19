# -*- coding: utf-8 -*-
"""Card admin SERVICE - extracted from sessions.py. archive/delete/update_track,
attachments, checkpoints/rewind, fork_conversation/fork_track, history, and
apply_board_directives (the repo-data-applied-once import). Imports the
already-extracted services directly (trackstore, gitutil, worktrees). The one
still-trapped dependency (_maybe_fast_track_ship, the fast-track cluster) is
reached via a lazy `import sessions` inside update_track; get_track()'s trivial
body (_find(_load(), tid)) is inlined rather than back-referenced.
"""
import json
import os
import subprocess
import time

from runs import REC

import db as _db
from trackstore import _load, _save_track, _find, _slug, _unique_id, _mutate
from gitutil import _git, _branch_exists, _checkpoint, _worktree_for
from worktrees import reclaim_worktree

# same source-of-truth as sessions.{ROOT,DEFAULT_PERM} - process-idempotent,
# safe to read independently rather than importing sessions (would cycle).
from _subpaths import DAEMON_ROOT as ROOT
DEFAULT_PERM = os.environ.get("HELMDECK_PERM", "acceptEdits")


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
    import sessions  # lazy: _maybe_fast_track_ship still lives there
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
            sessions._maybe_fast_track_ship(t, log)   # lazy: fast-track cluster still in sessions.py
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
        t = _find(_load(), tid)
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
    src = _find(_load(), tid)
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
    src = _find(_load(), tid)
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
    t = _find(_load(), tid)
    if not t:
        return []
    return [r for r in read_timeline(t["run_dir"])
            if r.get("kind") in ("steer", "reply", "note", "turn")]

