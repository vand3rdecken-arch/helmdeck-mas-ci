# -*- coding: utf-8 -*-
"""The lane/gate/merge machine - THE crown-jewel SERVICE, extracted from
sessions.py. move_lane is the state machine every accept/bounce/deploy path
runs through; _gate/_merge_to_main/_autocommit/_repo_hook are its gate and
merge pipeline. Imports the already-extracted services directly (trackstore,
gitutil, blockers, outcomes, worktrees). Four names still live in sessions.py
(LANES, _start, _accept_machine, steer - the dispatch/machine/steer paths not
yet extracted) and are reached via a lazy `import sessions` inside the two
functions that need them, so there is no import cycle. sessions.py re-imports
the public names; the tests that patch sessions._gate/_merge_to_main/
_autocommit/_repo_hook now patch lanemachine.* (moved with the cluster - same
technique proven on trackstore._db).
"""
import os
import re
import subprocess
import time

from spine.storage.trackstore import _find, _load, _mutate, _slug
from spine.auth import gxp
from spine.git.gitutil import _git, _git_try, is_git_repo, AGENT_IDENT
from spine.turn.blockers import blocker
from spine.turn.outcomes import _record_outcome
from spine.git.worktrees import reclaim_worktree


_GATE_PASS_RE = re.compile(r"gate: (PASS \(\d+ checks\)|nothing to run on this branch - PASS)")


def _run_streamed(cmd, cwd, env, idle, hard, note_cb=None, tail_n=400):
    """Run `cmd` bounded by SILENCE, not wall-clock - the shared execution
    shape behind both _gate's own command and _repo_hook (which discovered
    this the hard way: a fixed 1800s cap killed a healthy deploy build mid-
    run - see the _repo_hook docstring). ANY output line resets the clock;
    only total silence for `idle` seconds (or, if `hard` is set, wall time
    past it) kills the process TREE (taskkill /T - a shell parent alone would
    orphan gradle/java/node still holding file locks). note_cb(line), if
    given, is called for every raw line AS IT ARRIVES (repo hooks narrate
    their own long phases through HOOK-NOTE: lines this way).

    Returns (returncode, tail_text, why): why is "" on a normal exit, else
    the kill reason ("no output for Ns" / "exceeded hard cap Ns"); returncode
    is None when killed or when the process never started."""
    import collections, threading
    lines = collections.deque(maxlen=tail_n)
    last = [time.time()]
    proc, why, rc = None, "", None
    try:
        proc = subprocess.Popen(cmd, cwd=cwd or ".", shell=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                bufsize=1, env=env)

        def _pump():
            try:
                for line in proc.stdout:
                    stripped = line.rstrip("\n")
                    lines.append(stripped)
                    last[0] = time.time()      # ANY output = still alive
                    if note_cb:
                        note_cb(stripped)
            except Exception:
                pass
        pump = threading.Thread(target=_pump, daemon=True)
        pump.start()
        start = time.time()
        poll = min(5.0, max(0.5, idle / 4.0))
        while True:
            try:
                proc.wait(timeout=poll)
                break                        # exited on its own
            except subprocess.TimeoutExpired:
                pass
            now = time.time()
            if now - last[0] > idle:
                why = "no output for %ds" % int(idle)
                break
            if hard and now - start > hard:
                why = "exceeded hard cap %ss" % int(hard)
                break
        if why:
            _hook_kill_tree(proc)
        else:
            pump.join(timeout=5)
            rc = proc.returncode
    except Exception as e:
        _hook_kill_tree(proc)               # never leak the tree on an error path
        lines.append(str(e))
        why = why or "exception"
    return rc, "\n".join(lines).strip(), why


def _admit_heavy(t, kind, log=None):
    """LOAD-AWARE ADMISSION (ops/docs/backlog/load-aware-admission) - the desktop
    lock's pattern generalized from mutual EXCLUSION to mutual AWARENESS: a
    heavy op (gate run / build+emulator deploy hook / preview hook) admits
    immediately while OBSERVED CPU load stays under policy.load_admission's
    threshold, sampled fresh here (spine.ops.resources), never a
    stored "busy" flag. Over threshold it QUEUES - polling, with a visible
    NAMED-holder note in the card's own chat the first time it waits, exactly
    like the desktop lock's wait note - up to wait_s, then ADMITS ANYWAY:
    this defers the start of a heavy op, it does not throttle a running one
    and must never brick a card by refusing forever.

    Registers itself as a named holder for the CALLER to release (via
    locks._release_heavy) once its op finishes, so a card queued behind THIS
    one can say what it is waiting for. Returns the release token."""
    from spine.storage import events
    from spine.ops import resources
    from spine.git.locks import _register_heavy, _heavy_holder_desc
    pol = (events.settings().get("policy") or {}).get("load_admission") or {}
    if pol.get("enabled", True):
        cpu_max = float(pol.get("cpu_max_pct") or 85)
        wait_cap = float(pol.get("wait_s") or 1800)
        poll_s = max(1.0, float(pol.get("poll_s") or 5))
        start = time.time()
        noted = False
        while True:
            cpu = resources.cpu_percent(interval=0.2)
            if cpu is None or cpu < cpu_max:
                break
            if time.time() - start > wait_cap:
                if log:
                    log.log("note", "Box weiterhin ausgelastet (CPU %.0f%%) - starte "
                                    "trotzdem nach %ds Wartezeit" % (cpu, int(wait_cap)))
                events.emit("load_wait", t.get("id"), op=kind, cpu_pct=cpu,
                            wait_s=wait_cap, gave_up=True)
                # Load that outlasts the whole wait window is no longer a
                # scheduling detail - it is an EXCEPTION, and judging it (is
                # this an external hog worth telling the owner about, or our
                # own build queue clearing itself?) is Henry's job, not a
                # threshold's (the engineer cell reports facts, never
                # decides). Deduped here because the channel does not: one
                # open load-contention escalation at a time.
                try:
                    from spine.registry import escalations
                    if not any(e.get("kind") == "load-contention"
                               for e in escalations.list_open()):
                        escalations.emit(
                            "load-contention", card=t.get("id"),
                            detail="Box ueber der Admissions-Schwelle (CPU %.0f%% > %.0f%%) "
                                   "laenger als die Wartezeit (%ds) - %s fuer Karte %s startet "
                                   "trotzdem. Bekannte HelmDeck-Holder: %s"
                                   % (cpu, cpu_max, int(wait_cap), kind, t.get("id"),
                                      _heavy_holder_desc()))
                except Exception:
                    pass          # the escalation is a courtesy, never a blocker
                break
            if not noted:
                who = _heavy_holder_desc()
                if log:
                    log.log("note", "wartet: Box ausgelastet durch %s (CPU %.0f%%) - "
                                    "warte bis zu %ds" % (who, cpu, int(wait_cap)))
                events.emit("load_wait", t.get("id"), op=kind, cpu_pct=cpu, wait_s=wait_cap)
                noted = True
            time.sleep(poll_s)
    token = "%s:%s:%f" % (t.get("id"), kind, time.time())
    _register_heavy(token, kind, t.get("id"))
    return token


def _gate(t):
    """Quality gate run when a card is submitted for review. Checks: (1) the
    worktree exists and its work is committed; (2) if the repo declares its own
    gate (a `helmdeck.gate` file holding a shell command - the harness's
    standard), it must exit 0. Returns (ok, problems)."""
    problems = []
    wt = t.get("worktree")
    if not wt or not os.path.exists(wt):
        return False, ["never dispatched - nothing to submit"]
    # A RECLAIMED worktree leaves the directory behind but empty and unlinked
    # from git: reclaim_worktree deletes the contents, and on Windows the
    # now-empty dir often survives because a shell still holds it open ("WORKTREE
    # nicht entfernbar (gesperrt?)"). os.path.exists then still says yes, so
    # without this check the gate command runs inside an empty dir and reports
    # "can't open file ...: No such file or directory" once per test - a punch
    # list that reads like a catastrophic code failure but only means the tree
    # is gone. Say what actually happened.
    if not os.path.exists(os.path.join(wt, ".git")):
        return False, ["worktree reclaimed (no .git at %s) - nothing to gate. A card "
                       "whose work already landed needs no re-accept; otherwise "
                       "re-dispatch it so the tree is rebuilt from the branch." % wt]
    try:
        dirty = _git(wt, "status", "--porcelain")
        if dirty:
            problems.append("uncommitted changes:\n" + dirty[:400])
    except Exception as e:
        problems.append("git status failed: %s" % e)
    # WHERE THE GATE COMMAND COMES FROM - falling authority, first hit wins:
    #   1. `helmdeck.gate` in the REPO (main) - authoritative, so EVERY card is
    #      verified with the CURRENT gate even on an old branch.
    #   2. `helmdeck.gate` in the worktree - the branch's own, if main has none.
    #   3. the repo's TEMPLATE, provisioned per repo into repo_hooks[<repo>].gate
    #      by projects.apply_template().
    # A repo that ships its own file always beats the preset: the file is the
    # repo DECLARING its check, the preset is HelmDeck filling in for a repo that
    # never declared one. Either way the command is run by the DAEMON (full
    # command access), so the agent's permission mode never blocks the checks.
    #
    # Before (3) existed, a freshly cloned repo resolved NOTHING here: the whole
    # block was skipped and the card passed the gate station having run zero
    # checks, with nothing anywhere saying so. That silence is the bug this
    # resolution order and the else-branch below close.
    from spine.storage import events
    cmd, cmd_src = "", ""
    gate_file = os.path.join(t.get("repo") or wt, "helmdeck.gate")
    if not os.path.exists(gate_file):
        gate_file = os.path.join(wt, "helmdeck.gate")
    if os.path.exists(gate_file):
        with open(gate_file, encoding="utf-8") as f:
            cmd = f.read().strip()
        cmd_src = gate_file
    if not cmd:
        _hooks = (events.settings().get("repo_hooks") or {}).get(t.get("repo") or "", {})
        cmd = ((_hooks or {}).get("gate") or "").strip()
        if cmd:
            cmd_src = "Repo-Vorlage (repo_hooks.gate)"
    if cmd:
        from spine.git.locks import _gate_lock_for, _release_heavy
        from spine.ops.actionlog import ActionLog
        # run_dir is absent on a few synthetic test fixtures (no real card
        # was dispatched) - the admission wait note is a courtesy, not a
        # contract, so degrade to no log rather than KeyError on those.
        log = ActionLog(t["run_dir"]) if t.get("run_dir") else None
        st = events.settings()
        # SILENCE-bounded, not the old fixed 600s wall-clock cap: the LIGHT
        # gate (ops/tools/run_gate.py, debt gate-light) normally finishes in
        # seconds, but under box contention it can legitimately run 3-5x
        # slower (measured, ops/docs/backlog/load-aware-admission) - a wall-clock cap
        # then reds a gate that never actually stalled. gate_idle_s is total
        # OUTPUT silence (same shape as _repo_hook's hook_idle_s); an
        # optional gate_hard_s stays available for a runaway custom gate.
        def _num(key, default):
            try:
                return float(st.get(key) or 0) or default
            except Exception:
                return default
        idle = _num("gate_idle_s", 300.0)
        hard = _num("gate_hard_s", 0.0)
        # Which of the three sources won is worth one line on the timeline: a
        # gate that behaves unexpectedly is almost always the wrong SOURCE
        # (a stale helmdeck.gate on the branch beating the repo's preset), and
        # without this the owner sees only the command, never where it came from.
        if log:
            log.log("note", "GATE (%s): %s" % (cmd_src, cmd[:200]))
        # GATE SINGLETON (measured 2026-08-20, Display-Glasses card, debt
        # item in ops/docs/backlog/load-aware-admission): a second gate on the SAME
        # tree blocks here instead of racing the first for the box's CPU.
        with _gate_lock_for(wt):
            # Run in the worktree (cwd = the code under test), but expose the
            # MAIN checkout as %HELMDECK_REPO% so the gate can invoke the
            # CURRENT gate script from main - old branches don't carry
            # ops/tools/run_gate.py.
            #
            # %HELMDECK_HOME% is a SECOND, different root: HelmDeck's own
            # install. For HelmDeck's own cards the two are equal, which is why
            # one variable sufficed until now - but a FOREIGN repo's gate has to
            # reach ops/tools/repo_gate.py, which lives in HelmDeck, not in the
            # graded repo. Derived from the running code's own location
            # (daemon.paths.REPO_ROOT), never from a stored path that could go
            # stale after a move.
            from daemon.paths import REPO_ROOT as _HD_HOME
            genv = dict(os.environ, HELMDECK_REPO=t.get("repo") or wt,
                        HELMDECK_HOME=_HD_HOME)
            token = _admit_heavy(t, "gate", log)
            try:
                rc, out, why = _run_streamed(cmd, wt, genv, idle, hard)
            finally:
                _release_heavy(token)
        if why:
            problems.append("gate killed (%s):\n%s\n\n(gate command: %s)"
                            % (why, out[-1200:], cmd[:120]))
        # Observed on the live board (card 20260812-164257): a `py -3.12`
        # gate run via shell=True on Windows can come back with a nonzero
        # r.returncode while its OWN stdout is a clean ops/tools/run_gate.py
        # verdict - every check "ok", ending "gate: PASS (34 checks)" - a
        # shell/launcher exit-code hiccup downstream of the script's own
        # sys.exit(0), not a real failure. Root cause not pinned (no
        # AutoRun hook, reproduces clean when replayed by hand) - see debt
        # [gate-exit-code-vs-stdout-verdict]. run_gate.py's own verdict
        # line is a REAL signal (the process that printed it did finish
        # its checks), so prefer it over a returncode that contradicts it;
        # still hard-fail whenever the verdict itself is missing or red.
        elif rc != 0 and (_GATE_PASS_RE.search(out) and "=== GATE FAILED (" not in out):
            print("GATE: returncode %s disagreed with the script's own PASS verdict for %s "
                  "- trusting the verdict (see debt gate-exit-code-vs-stdout-verdict)"
                  % (rc, t.get("id")))
        elif rc != 0:
            # Lead with the ACTUAL error, not the command - the command alone
            # (truncated on mobile) is the "ominous, unresolvable" message. An
            # empty output means the command couldn't even start (missing
            # interpreter/tool); say so with the exit code instead of nothing.
            detail = out[-1200:] if out else "(no output - command could not run; exit %s)" % rc
            problems.append("gate FAILED:\n%s\n\n(gate command: %s)" % (detail, cmd[:120]))
    else:
        # NO gate command resolved at all. Deliberately NOT a failure: repos
        # onboarded before templates existed have no gate file and no preset,
        # and reddening every one of their cards would be a migration disguised
        # as a check. But it must not stay SILENT either - "the gate ran and was
        # happy" and "there was no gate" are different claims, and only the
        # second was ever true here. Naming it on the card's own timeline is
        # what makes it fixable (choose a repo type, or drop in a helmdeck.gate).
        note = ("gate: dieses Repo deklariert keinen Gate-Befehl - es wurde NICHTS "
                "geprueft. Repo-Typ waehlen (Mehr > Repo) oder eine helmdeck.gate "
                "ins Repo legen.")
        print("GATE: no command for %s (%s) - nothing checked"
              % (t.get("id"), t.get("repo")), flush=True)
        try:
            from spine.ops.actionlog import ActionLog
            if t.get("run_dir"):
                ActionLog(t["run_dir"]).log("note", note)
        except Exception as e:                                   # noqa: BLE001
            print("GATE: could not log the no-gate note: %s" % e, flush=True)
    return (not problems), problems

def _merge_to_main(t):
    """Land an accepted card: CLASSIFY it, then merge its branch into the repo's
    MAIN checkout. Runs in t['repo'] (the daemon's checkout, which holds the
    secrets the worktree never sees), NOT in the agent's worktree.

    Returns (accept_ok, kind, message):
      accept_ok True  -> the card may be accepted/closed:
        already_merged        - branch's work is already fully in main (redundant
                                / superseded); nothing to land.
        redundant_uncommitted - same, but the worktree still holds uncommitted
                                changes that were therefore NOT included (warned).
        merged                - real commits landed on main.
      accept_ok False -> the card is bounced with a clear reason:
        conflict              - branch conflicts with main; the conflicting files
                                and a resolve path are reported. Main is left
                                exactly as found (merge --abort).
        blocked               - can't even attempt (no repo / detached / on branch).

    A dirty tree is NOT pre-refused: real project repos keep tracked runtime output
    perpetually 'modified' and git merges into them fine unless the merge touches
    those files - so we let git decide."""
    repo = t.get("repo"); branch = t.get("branch"); wt = t.get("worktree")
    if not repo or not os.path.isdir(repo):
        return False, "blocked", "card has no repo checkout to merge into"
    if not branch:
        return False, "blocked", "card has no branch"
    try:
        cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception as e:
        return False, "blocked", "repo is not a git checkout: %s" % e
    if cur == "HEAD":
        return False, "blocked", "main checkout is in detached HEAD - checkout the base branch first"
    if cur == branch:
        return False, "blocked", "main checkout is ON the card branch (%s) - switch it to the base branch" % branch
    # how many committed commits does the branch add that main lacks?
    try:
        ahead = int(_git(repo, "rev-list", "--count", "HEAD..%s" % branch) or "0")
    except Exception as e:
        return False, "blocked", "cannot compare branch to main: %s" % e
    if ahead == 0:
        # branch content already in main -> nothing to land (redundant/superseded)
        dirty = ""
        if wt and os.path.isdir(wt):
            try:
                dirty = _git(wt, "status", "--porcelain")
            except Exception:
                dirty = ""
        if dirty:
            n = len(dirty.splitlines())
            return True, "redundant_uncommitted", (
                "Redundant: der Branch bringt nichts Neues nach main - die Arbeit ist "
                "bereits enthalten. %d uncommittete Worktree-Aenderung(en) wurden NICHT "
                "uebernommen (nie committet); falls noch gebraucht: committen und neu "
                "einreichen:\n%s" % (n, dirty[:200]))
        return True, "already_merged", (
            "Redundant/erledigt: die Arbeit ist bereits vollstaendig in main - nichts zu mergen.")
    # real work to land
    try:
        _git(repo, "merge", "--no-ff", branch, "-m",
             "HelmDeck accept: %s (%s)" % (branch, t.get("id", "")))
        return True, "merged", "%d Commit(s) sauber nach main (%s) gemergt." % (ahead, cur)
    except Exception as e:
        conflicts = ""
        try:
            conflicts = _git(repo, "diff", "--name-only", "--diff-filter=U")
        except Exception:
            pass
        try:
            _git(repo, "merge", "--abort")   # leave main exactly as found
        except Exception:
            pass
        files = conflicts or (str(e)[:200])
        return False, "conflict", (
            "Merge-Konflikt mit main - main hat sich weiterbewegt und aendert dieselben "
            "Stellen. Konfliktdateien:\n%s\nAufloesen: steuere den Agenten mit "
            "\"merge main in deinen Branch und loese die Konflikte, dann committen\" und "
            "reiche neu ein (der Worktree bleibt die sichere Sandbox)." % files)




# -- WORKTREE RECLAMATION (the second half of the isolation law) --------------
# HelmDeck's charter gives every card its own git worktree+branch so parallel
# cards never collide - a real edge over Paseo, which runs one agent in one
# shared directory. But isolation with no RECLAIM just piles up dead trees:
# accepted/archived cards left 25 orphaned worktrees behind ("System too full").
# Paseo stays clean only because it never makes worktrees at all. So we close the
# loop: when a card reaches a terminal state its tree goes back to the pool.



def _autocommit(t):
    """Clean up + commit uncommitted worktree work on the card's OWN branch (also
    COMPLETES a conflict merge the harness set up), so finishing never dead-ends on
    'uncommitted changes'. `git add -A` respects .gitignore. Returns:
      True     - committed
      False    - nothing to commit
      "markers"- unresolved conflict markers remain; caller must bounce."""
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt):
        return False
    merging = _git_try(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0
    rc, dirty, _ = _git_try(wt, "status", "--porcelain")
    if rc != 0 or (not dirty and not merging):
        return False
    if _git_try(wt, "add", "-A")[0] != 0:
        return False
    # refuse to commit if conflict markers are still in the staged content
    chk = subprocess.run(["git", "-C", wt, "diff", "--cached", "--check"],
                         capture_output=True, text=True)
    if "conflict marker" in (chk.stdout or "").lower():
        return "markers"
    if _git_try(wt, *AGENT_IDENT, "commit",
                "-m", "HelmDeck: finalize %s" % t.get("id", ""))[0] != 0:
        return False
    return True


def _pull_main_into_branch(t):
    """Harness-side conflict resolution: merge main INTO the card's branch, in the
    card's worktree (the daemon has full git access; the agent never runs a merge).
    Either git auto-resolves it, or it leaves standard conflict MARKERS in the
    worktree files - which the agent/owner then resolves by plain EDITING (allowed
    in acceptEdits), never a git-merge. Returns "resolved" | "markers:<files>" |
    "error:<msg>"."""
    wt = t.get("worktree"); repo = t.get("repo")
    if not wt or not os.path.isdir(wt) or not repo:
        return "error:no worktree"
    rc, mainbranch, err = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return "error:%s" % err
    rc, _out, _err = _git_try(wt, "merge", mainbranch, "--no-edit")
    if rc == 0:
        return "resolved"
    files = _git_try(wt, "diff", "--name-only", "--diff-filter=U")[1]
    return "markers:" + (files or _err[:150])


def _base_branch(t):
    """The branch this card must be gated AGAINST, DERIVED and VERIFIED - never
    taken on faith from the stored field. Order:
      1. the base recorded at branch creation (dispatch._record_base_branch) -
         the only moment the fork point is a fact;
      2. its LOCAL twin when the record names a remote ref (`origin/main` ->
         `main`): _base_ref may fork a card from origin, but the accept merges
         into the LOCAL checkout, so the local branch is the code the card will
         actually land beside;
      3. the repo checkout's current branch - the fallback for cards dispatched
         before the field existed, and exactly what _pull_main_into_branch has
         always used.
    Every candidate must resolve to a commit IN THE WORKTREE (a card branch is
    the only place the merge will run) before it is returned; a name that no
    longer exists falls through instead of being merged blindly. Returns the
    ref name or None when nothing verifiable is left."""
    wt = t.get("worktree"); repo = t.get("repo")

    def _resolves(ref):
        return bool(ref) and _git_try(wt, "rev-parse", "--verify", "-q",
                                      ref + "^{commit}")[0] == 0

    rec = t.get("base_branch")
    if rec:
        local = rec.split("/", 1)[1] if rec.startswith("origin/") else None
        if _resolves(local):
            return local
        if _resolves(rec):
            return rec
    rc, cur, _err = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0 or not cur or cur == "HEAD" or cur == t.get("branch"):
        return None                      # detached, unborn, or parked ON the card branch
    return cur if _resolves(cur) else None


def _sync_base(t):
    """Merge the card's BASE into the card's branch BEFORE the gate runs.

    A worktree is isolated from base drift for the card's ENTIRE open lifetime,
    and move_lane never merged the base back in while the card was open - so a
    card gated the code it forked from, not the code it will land beside. When
    base changes a shared behaviour and its test in separate commits, the card
    reds for code it never touched (debt gate-base-lag; hit live on
    proc-20260816-s2, reddened by a 56-file base-only test-wiring fix). The gate
    is only meaningful against the CURRENT base, so sync first, then gate.

    A conflict is left as editable MARKERS in the worktree - the same
    resolve-by-editing loop _pull_main_into_branch built (the agent never runs a
    git merge; the next submit's _autocommit completes it). Returns:
      "uptodate"          - the branch already contains the base
      "synced:<n>"        - n base commit(s) merged in
      "conflict:<files>"  - markers left in the worktree; caller must bounce
      "skip:<why>"        - not a worktree card / no tree to sync
      "error:<msg>"       - the merge could not run; caller gates as-is (a
                            sync failure must never block an otherwise green
                            card - it only degrades to the old behaviour)"""
    wt = t.get("worktree"); repo = t.get("repo")
    if t.get("machine") or not t.get("branch"):
        return "skip:no card branch"
    if not wt or not repo or not os.path.isdir(wt):
        return "skip:no worktree"
    # FAST-TRACK / direct cards edit the LIVE tree (worktree == repo, debt
    # fast-track-no-gate): there is no copy to drift, and merging the base into
    # itself would be a no-op at best and a surprise commit in the owner's own
    # checkout at worst.
    if os.path.normcase(os.path.abspath(wt)) == os.path.normcase(os.path.abspath(repo)):
        return "skip:card edits the live tree"
    if not os.path.exists(os.path.join(wt, ".git")):
        return "skip:worktree reclaimed"     # _gate says this properly, with the repair path
    if _git_try(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0:
        # _autocommit runs first and completes any resolved merge, so a MERGE_HEAD
        # still standing here means unresolved work - report it as the conflict it is
        # rather than letting `git merge` fail with "already merging".
        files = (_git_try(wt, "diff", "--name-only", "--diff-filter=U")[1] or "").strip()
        return "conflict:" + (files or "(merge in progress)")
    base = _base_branch(t)
    if not base:
        return "error:no verifiable base branch for this card"
    rc, behind, err = _git_try(wt, "rev-list", "--count", "HEAD..%s" % base)
    if rc != 0:
        return "error:cannot compare against %s: %s" % (base, err[:120])
    if int(behind or "0") == 0:
        return "uptodate"
    rc, _out, err = _git_try(wt, "merge", base, "--no-edit", "-m",
                             "HelmDeck base-sync: %s into %s" % (base, t.get("branch")))
    if rc == 0:
        return "synced:%s" % behind
    files = (_git_try(wt, "diff", "--name-only", "--diff-filter=U")[1] or "").strip()
    if files:
        return "conflict:" + files          # markers left in place, on purpose
    # The merge never started (dirty tree it would clobber, index lock, ...) -
    # nothing to abort, nothing resolved. Degrade to gating the branch as-is.
    _git_try(wt, "merge", "--abort")
    return "error:%s" % (err[:200] or "merge failed with no conflicting files")


def dispatch_conflict_resolution(card_id, actor="board copilot", background=True):
    from cells.engineer import sessions  # lazy: steer() still lives in sessions.py
    """Hand a REAL <<<<<<< merge conflict to the card's OWN worker as an edit-only
    task - the chat itself never edits code, but it can dispatch the card's agent.
    Sets up (or reuses) conflict markers in the worker's worktree via
    _pull_main_into_branch, then steers the worker to merge the markers by plain
    EDITING (never a git merge). On the next move to done, _autocommit completes
    the merge and the gate runs. Returns a human-readable status string.

    background=False runs the steer synchronously (the PM coordinator uses this
    to chain delegate -> re-submit on its own thread; the chat keeps True)."""
    t = _find(_load(), card_id)
    if not t:
        return "no card '%s'" % card_id
    if t.get("machine"):
        return ("'%s' ist eine Maschinen-Aufgabe (Ordner %s) ohne Branch - es gibt keinen "
                "Merge-Konflikt. Steuere sie einfach weiter."
                % (card_id, t.get("worktree") or "?"))
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt):
        return "%s has no worktree - dispatch/start the card first" % t.get("branch", card_id)
    # already mid-merge with markers (from a prior Done attempt)? reuse it - a
    # second `git merge` would abort with "already merging". Otherwise set one up.
    merging = _git_try(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0
    if not merging:
        res = _pull_main_into_branch(t)
        if res == "resolved":
            return ("%s: main merged cleanly into the branch - no markers, nothing to "
                    "resolve. Move it to done to land it." % t.get("branch", card_id))
        if res.startswith("error"):
            return "%s: could not set up resolution (%s)" % (t.get("branch", card_id), res[6:])
    files = (_git_try(wt, "diff", "--name-only", "--diff-filter=U")[1] or "").strip()
    if not files:
        if merging:
            # mid-merge but nothing unmerged -> the markers are already resolved and
            # staged; the harness finalizes on the next move to done.
            return ("%s: Konflikte sind bereits aufgeloest (keine Markierungen mehr offen). "
                    "Schieb die Karte auf Done - der Harness committet + merged dann selbst."
                    % t.get("branch", card_id))
        return ("%s: no conflict markers in the worktree - if it still won't merge it is "
                "likely a dirty shared checkout (use resolve_blocker)." % t.get("branch", card_id))
    flist = ", ".join(files.split("\n"))
    instr = ("Es stehen Git-Konfliktmarkierungen (<<<<<<< / ======= / >>>>>>>) in diesen "
             "Dateien: %s. Oeffne jede Datei, fuehre beide Seiten inhaltlich sinnvoll "
             "zusammen und ENTFERNE alle Markierungen restlos. Nur editieren - kein git, "
             "kein merge oder commit. Wenn keine Markierung mehr uebrig ist, bist du fertig; "
             "der Harness committet und merged dann selbst." % flist)
    if not background:
        sessions.steer(t["id"], instr, actor=actor, source="conflict-resolution")
        return ("Konfliktaufloesung durch den Worker von %s gelaufen (Dateien: %s) - "
                "jetzt neu einreichen, dann committet+merged der Harness." % (t.get("branch", card_id), flist))
    import threading
    threading.Thread(target=sessions.steer, args=(t["id"], instr),
                     kwargs={"actor": actor, "source": "conflict-resolution"}, daemon=True).start()
    return ("Konfliktaufloesung an %s geschickt (Dateien: %s). Der Worker merged die "
            "Markierungen im Hintergrund - danach die Karte auf Done schieben, dann "
            "committet+merged der Harness." % (t.get("branch", card_id), flist))


def _classify_merge(t):
    """DRY-RUN of the merge - what a Done WOULD do, without landing anything. Used
    by Review to rest the card on the board with a verdict. Returns (kind, message):
      already_merged / redundant_uncommitted - nothing to land (redundant)
      mergeable  - N commits merge cleanly
      conflict   - would conflict with main (names the files)
      blocked    - detached / on the card branch / no repo
    Leaves the main checkout exactly as found."""
    repo = t.get("repo"); branch = t.get("branch"); wt = t.get("worktree")
    if not repo or not os.path.isdir(repo):
        return "blocked", "kein Repo-Checkout zum Mergen"
    if not branch:
        return "blocked", "keine Branch"
    rc, cur, err = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return "blocked", "kein git-Checkout: %s" % err
    if cur == "HEAD":
        return "blocked", "main-Checkout ist detached"
    if cur == branch:
        return "blocked", "main-Checkout steht auf dem Karten-Branch (%s)" % branch
    rc, ahead, _ = _git_try(repo, "rev-list", "--count", "HEAD..%s" % branch)
    ahead = int(ahead or "0") if rc == 0 else 0
    if ahead == 0:
        dirty = _git_try(wt, "status", "--porcelain")[1] if wt and os.path.isdir(wt) else ""
        if dirty:
            return "redundant_uncommitted", ("Redundant: committet nichts Neues (schon in main); "
                                             "%d uncommittete Aenderung(en) wuerden beim Abschluss committet." % len(dirty.splitlines()))
        return "already_merged", "Redundant: die Arbeit ist bereits vollstaendig in main."
    # dry-run the merge, then undo it (main left exactly as found)
    rc, _o, _e = _git_try(repo, "merge", "--no-commit", "--no-ff", branch)
    conflicts = _git_try(repo, "diff", "--name-only", "--diff-filter=U")[1]
    _git_try(repo, "merge", "--abort")
    if rc == 0:
        return "mergeable", "Bereit: %d Commit(s) mergen sauber nach main." % ahead
    return "conflict", ("Konflikt mit main - dieselben Stellen geaendert. Dateien:\n%s\n"
                        "Beim Abschluss holt der Harness main in den Branch; loese die "
                        "Markierungen (editieren)." % (conflicts or _e[:150]))


def _hook_kill_tree(proc):
    """Force the hook's whole process tree down. The hook is a SHELL, so
    terminating it alone orphans the real workers (gradle/java/node keep the
    build running and holding file locks). taskkill /T walks the tree at kill
    time, so kill the parent forcefully in ONE call rather than politely first
    (which would blind /T to the children)."""
    import subprocess
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        else:
            proc.kill()
        proc.wait(timeout=10)
    except Exception:
        pass


def _repo_hook(t, kind, extra_env=None):
    """Owner-defined per-repo hook, policy in settings:
      "repo_hooks": {"<repo path>": {"preview": "<cmd>", "deploy": "<cmd>"}}
    preview runs in the WORKTREE when a card reaches Review (try it before
    merging); deploy runs in the MAIN REPO after accept - by the daemon, which
    is the only party holding secrets. Output lands on the card (last_reply
    stays the agent's - hooks log to the actionlog + a hook field).

    `extra_env` overlays the hook's environment for THIS run. The ship
    decision rides in here (SHIP_KIND=none|ota|native, decided by Henry at
    event time, executed by ship.sh) - an env var and never a file, exactly
    as the ship-advisor brief demands: a decision file would be the stored
    flag the advisor exists to replace.

    Bounded by SILENCE, not by wall-clock. A fixed 1800s cap killed the deploy
    hook mid-build: the NATIVE ship path (npm ci -> gradle assembleRelease ->
    emulator smoke -> scp the APK -> two expo exports -> two more uploads)
    legitimately runs past 30 minutes, so the ceiling fired on a HEALTHY build
    and left main merged with nothing shipped. Same defect the turn watchdog
    already fixed (drivers.run_turn): a build that is still printing is
    working. The window has to be generous because scp of a ~100MB APK over a
    pipe prints NOTHING while it uploads - silence, not duration, is what
    separates wedged from busy. `hook_max_s` is an optional absolute ceiling
    (0/unset = none) for a hook that dribbles output forever.

    STREAMS live: any output line prefixed `HOOK-NOTE:` is logged to the
    actionlog THE MOMENT it's read (ship.sh/build_apk.sh narrate their own
    long phases through it - "npm ci starting", "gradle running, ~10-15
    min", "APK built") - without this a healthy 15-20 min build looked from
    the owner's phone identical to a genuinely stuck card.

    LOAD-AWARE ADMISSION (ops/docs/backlog/load-aware-admission): before starting, this
    waits for OBSERVED CPU load to clear policy.load_admission's threshold -
    the deploy hook IS the APK/Gradle build + emulator boot, so gating its
    start is what keeps a build from launching straight into a box already at
    100% from a gate or another build. See _admit_heavy."""
    from spine.storage import events
    from spine.git.locks import _release_heavy
    st = events.settings()
    hooks = (st.get("repo_hooks") or {}).get(t.get("repo") or "", {})
    cmd = (hooks or {}).get(kind, "").strip()
    if not cmd:
        return None
    def _num(key, default):
        try:
            return float(st.get(key) or 0) or default
        except Exception:
            return default
    idle = _num("hook_idle_s", 900.0)       # 15 min of TOTAL silence = wedged
    hard = _num("hook_max_s", 0.0)          # optional absolute cap; default none
    cwd = t.get("worktree") if kind == "preview" else t.get("repo")
    from spine.ops.actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "%s HOOK: %s" % (kind.upper(), cmd))

    def _note(line):
        # live progress narration: a hook script can announce its own long
        # phases instead of the owner watching dead silence
        s = line.strip()
        if s.startswith("HOOK-NOTE:"):
            log.log("note", s[len("HOOK-NOTE:"):].strip())

    token = _admit_heavy(t, "build" if kind == "deploy" else "preview", log)
    # A hook that says plain `bash` means GIT-bash, never WSL. _run_streamed
    # runs shell=True -> cmd.exe -> PATH, and since the daemon's PATH
    # hydration appends the Windows dirs, `bash` can resolve to
    # System32\bash.exe (WSL) - measured 2026-09-03: Henry's first executed
    # ship-decision (ota) died on "Windows Subsystem for Linux must be
    # updated". Same trap the native-stale fingerprint already hit (debt
    # register: "plain bash=WSL, use git-bash path"); signkeys.py resolves
    # the identical candidates for gpg.
    if os.name == "nt" and (cmd == "bash" or cmd.startswith("bash ")):
        for _cand in (r"C:\Program Files\Git\bin\bash.exe",
                      r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if os.path.exists(_cand):
                cmd = '"%s"%s' % (_cand, cmd[4:])
                break
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        rc, out, why = _run_streamed(cmd, cwd, env, idle, hard, note_cb=_note)
    finally:
        _release_heavy(token)
    if why:
        out = (out + "\n[hook killed: %s]" % why).strip()
    ok = (rc == 0) and not why
    log.log("note", "%s HOOK %s: %s" % (kind.upper(), "OK" if ok else "FAILED", out[-800:]))
    t[kind + "_hook"] = {"ok": ok, "tail": out[-1500:]}
    return ok


def request_ship_decision(t, origin):
    """Hand the SHIP DECISION to Henry instead of firing the deploy hook
    (owner decree 2026-09-01: "not a process after done anymore but something
    Henry needs to decide whether it makes sense" - measured cost of the old
    reflex that same day: a mechanical post-accept ship, a manual build and a
    daemon-restart eviction collided for hours, and no agent was anywhere in
    the loop to notice or stop it).

    This is the EMIT half only (the engineer cell reports facts, never
    decides - the broker docstring's split): one escalation per landed
    change, judged by Henry with the full system snapshot he already carries
    (build locks, box load, live build processes - exactly the context the
    collisions above needed). Henry answers with the `ship` verb
    (kind none|ota|native); the broker executes ota/native through
    _repo_hook with SHIP_KIND so ship.sh runs the DECISION, not the legacy
    hash fallback (pays debt ship-decision-not-wired).

    Facts are deliberately NOT pre-collected here: the advisor brief's own
    rule is "decide at the moment of shipping, from facts read at that
    moment", and Henry's judgement turn runs ops/tools/ship_facts.py itself,
    fresh, minutes later when the decision actually happens.

    DEDUP by (open ship-decision, same card): fast-track finishes a turn
    every few minutes and each one used to deploy - under judgement, a still
    -open decision already covers the newer landing, because Henry reads the
    tree fresh when he gets to it. Returns the escalation id, or None when
    nothing was emitted (no deploy hook configured = repo ships some other
    way, or an open decision already pending)."""
    from spine.storage import events
    from spine.registry import escalations
    st = events.settings()
    hooks = (st.get("repo_hooks") or {}).get(t.get("repo") or "", {})
    from spine.ops.actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    if not (hooks or {}).get("deploy", "").strip():
        # NEVER silent (measured 2026-09-03: a flaky settings read returned no
        # repo_hooks, this branch returned None without a trace, and two
        # accepted UI cards shipped nowhere - nobody could see why). A repo
        # that genuinely ships some other way reads this note once per accept;
        # a broken settings read becomes visible the moment it costs something.
        log.log("note", "SHIP: kein deploy-Hook fuer repo %r (settings.repo_hooks)"
                        " - keine Ship-Entscheidung emittiert (%s)."
                        % (t.get("repo") or "", origin))
        return None
    try:
        if any(e.get("kind") == "ship-decision" and e.get("card") == t["id"]
               for e in escalations.list_open()):
            log.log("note", "SHIP: Entscheidung liegt bereits bei Henry (offen) - "
                            "keine zweite Eskalation fuer diese Landung (%s)." % origin)
            return None
    except Exception:
        pass                            # a fold failure must not block the emit
    eid = escalations.emit(
        "ship-decision", card=t["id"],
        detail=("Aenderung gelandet (%s, Karte %s). Entscheide, ob JETZT geshippt "
                "wird - kein Automatismus mehr (Owner-Dekret 2026-09-01).\n"
                "Brief: ops/harness/agents/ship-advisor.md. Evidenz IMMER frisch "
                "holen: py -3.12 ops/tools/ship_facts.py\n"
                "Antworte mit action \"ship\" und kind none|ota|native "
                "(none = nichts zu shippen, kurz begruenden). Der Harness fuehrt "
                "ota/native selbst ueber den Deploy-Hook aus (SHIP_KIND an "
                "ship.sh, silence-bounded) - baue NIE selbst im Judgement-Turn, "
                "ein nativer Build sprengt dessen Timeout."
                % (origin, t["id"])))
    log.log("note", "SHIP: Entscheidung an Henry uebergeben (%s) - kein "
                    "automatischer Deploy mehr." % origin)
    return eid


from spine.registry import i18n as _i18n  # owner-facing prose only; the audit trail stays English


def _say_card(t, text, kind=None):
    """Report a lane OUTCOME in the owner's board chat, in plain language.

    The lane pipeline is otherwise mute toward the chat: it writes the flight
    recorder, the event log and a push, none of which is the surface the owner
    actually reads. A drag to Done could run the gate, hit a conflict and
    bounce with nothing to show for it. Best-effort by design - reporting an
    outcome must never break the work that produced it.

    Routed through card_mirror.say_card since 2026-08-29 so a lane outcome is
    the SAME kind of object as a mirrored question or turn end - labelled with
    the card's short name, bound to its id, and visible on the watch. It used
    to be a bare cls="pm" line, which meant the two halves of the same inbox
    looked and behaved differently: a turn end was answerable and reached the
    wrist, an accept or a red gate was neither. This function stays the ONE
    owner of lane-outcome messages (card_mirror.REASONS deliberately omits
    done/bounced) - the mirror is where it writes, not a second voice.

    `kind` splits the outcomes that STOP the card (red gate, conflict, drift,
    failed landing) from the ones that merely report progress. Both are lane
    outcomes; only the first is a blocker, and the owner filters his inbox on
    exactly that difference."""
    try:
        from cells.copilot import card_mirror
        card_mirror.say_card(t, kind or card_mirror.KIND_RESULT, text)
    except Exception:
        pass


_LANE_LIVE = {}   # tid -> re-entry depth of a move_lane pipeline on a live thread in
                  # THIS process. Written by exactly ONE owner (the move_lane wrapper
                  # below), at event time, try/finally-paired - never persisted.


def lane_active(tid):
    """A move_lane pipeline for this card is on a live thread's stack in THIS
    process - lifecycle as an OBSERVATION (drivers.turn_active's pattern), not a
    stored flag or a duration guess. The zombie reconciler consults this before
    reaping a status='gating' card: the gate/merge/deploy pipeline is a
    synchronous subprocess chain that legitimately runs for many minutes while
    the card's run_dir stays silent, so any idle-clock bound on "a real gate's
    runtime" starts reaping LIVE gates the day the suite outgrows the guess
    (measured 2026-08-20: the ~5min suite got card req-worktree-base-sync
    bounced at ~2min mid-gate with a phantom 'daemon restarted' note). Liveness
    is the runtime's own signal; the gate subprocess timeout (600s) stays the
    real bound on a runaway gate."""
    return _LANE_LIVE.get(tid, 0) > 0


def _sod_block_reason(actor, t):
    """Why `actor` may not accept THIS card under Separation of Duties, or None.

    Off by default (policy.sod_accept) - a one-person shop cannot dispatch AND
    approve as two different people, same reasoning as gxp.four_eyes(). On,
    per ops/docs/backlog/rbac-gxp: acceptance requires the `quality` role AND
    actor != the card's own dispatched_by - stricter than four-eyes (any other
    human), because SoD is specifically the approver-role separation, not just
    "someone else looked at it"."""
    from spine.auth import policy
    if not policy.get_policies().get("sod_accept", False):
        return None
    from spine.auth import auth
    u = auth.get_user(actor)
    role = (u or {}).get("role")
    if role != "quality":
        return ("SoD: accepting requires the quality role (actor '%s' is %s)"
                % (actor, role or "not a real account"))
    if t.get("dispatched_by") == actor:
        return "SoD: %s dispatched this card and may not also accept it" % actor
    return None


def move_lane(tid, lane, actor="owner", _autopark=True):
    """The board move is the workflow verb: ->working dispatches, ->review submits
    (GATED: the card bounces back with a punch list unless its work is green),
    ->done accepts (records the acceptance economics).

    Registration wrapper: the pipeline is registered in _LANE_LIVE BEFORE the
    body publishes status='gating' (its first mutate), so no observer can ever
    see 'gating' without also seeing the live registration - the reconciler's
    load-then-check has no race window. A DEPTH counter, not a flag:
    park_and_retry_merge re-enters move_lane('review') from inside a 'done'
    pipeline, and the outer pipeline must stay observable when the inner one
    unwinds."""
    _LANE_LIVE[tid] = _LANE_LIVE.get(tid, 0) + 1
    try:
        return _move_lane(tid, lane, actor=actor, _autopark=_autopark)
    finally:
        _depth = _LANE_LIVE.get(tid, 1) - 1
        if _depth > 0:
            _LANE_LIVE[tid] = _depth
        else:
            _LANE_LIVE.pop(tid, None)


def _move_lane(tid, lane, actor="owner", _autopark=True):
    from cells.engineer import sessions  # lazy: LANES/_start/_accept_machine still live in sessions.py
    from spine.storage import events
    if lane not in sessions.LANES:
        raise RuntimeError("bad lane: " + lane)
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    prev = t.get("lane")
    # ---- EXAMPLE CARD: never dispatches -----------------------------------
    # The onboarding guide card seeded at setup (accounts-boards-prd phase 3,
    # `example: true`) has no repo worth an agent's time and must stay inert
    # by CONSTRUCTION, not by every caller remembering to check first - this
    # is the one chokepoint every lane move arrives at (see the GxP comment
    # below), so blocking it here closes the board drag, the chat verb, the
    # PM's autonomous dispatch and any future caller in one place. Refused,
    # not silently ignored, so a curious owner sees why nothing happened.
    if t.get("example") and lane != "backlog":
        events.emit("example", tid, outcome="move_refused", actor=actor,
                    lane_from=prev, lane_to=lane)
        return dict(t, example_refused="this is the onboarding example card - "
                    "it never runs an agent; delete it if you don't need it")
    # ---- GxP: THE chokepoint -------------------------------------------
    # Every accept path in the daemon arrives here - the board route, Henry's
    # `move`, the policy auto-accept, the chat verb, the PM - and fast-track and
    # machine cards branch off further down, still inside this function. So one
    # question asked once closes all of them, and no agent needs a special case:
    # they simply are not accounts (spine/auth/gxp.py is_human).
    #
    # Scoped per card, not globally: only cards aimed at a regulated repo (or
    # flagged into scope) are affected, everything else keeps working exactly as
    # before. Placed BEFORE the idempotency short-circuit below, so an already
    # -'accepted' card cannot be walked through either.
    if lane == "done":
        _blocked = gxp.accept_block_reason(actor, t)
        if _blocked:
            events.emit("gxp", tid, outcome="accept_refused", actor=actor,
                        lane_from=prev, reason=_blocked)
            if t.get("run_dir"):
                from spine.ops.actionlog import ActionLog as _AL
                _AL(t["run_dir"]).log("note", "GxP: Abnahme abgelehnt - " + _blocked)
            return dict(t, gxp_refused=_blocked)
        # ---- SoD: separate chokepoint, same shape (card 3) -----------------
        # policy.sod_accept, default OFF (solo-owner operation unchanged): when
        # on, only the `quality` role may accept, and never the card's own
        # dispatcher (t["dispatched_by"], captured at intake in dispatch.py's
        # new_track - the same field ops/docs/gxp-mode-design.md's four-eyes
        # design already relies on). A separate check from gxp's, on purpose:
        # a repo can be GxP-regulated without SoD, or run SoD without GxP.
        _sod = _sod_block_reason(actor, t)
        if _sod:
            events.emit("sod", tid, outcome="accept_refused", actor=actor,
                        lane_from=prev, reason=_sod)
            if t.get("run_dir"):
                from spine.ops.actionlog import ActionLog as _AL
                _AL(t["run_dir"]).log("note", "SoD: Abnahme abgelehnt - " + _sod)
            return dict(t, sod_refused=_sod)
    # record the human's board move in the card's own feed (chat), so a drag to
    # Review/Done/Working/Backlog reads alongside the agent's work, not just in the
    # global event log. The lane-specific handlers below add the outcome detail.
    if t.get("run_dir") and prev != lane:
        from spine.ops.actionlog import ActionLog as _AL
        _lane_label = {"backlog": "Backlog", "working": "In Arbeit", "review": "Review", "done": "Done"}
        _AL(t["run_dir"]).log("note", "→ verschoben nach %s von %s"
                              % (_lane_label.get(lane, lane), actor))
    if lane == "working":
        # pulling a card back OUT of review is a human bounce - the reject touch
        if prev == "review":
            events.emit("touch", tid, touch="bounce", actor=actor)
            from spine.ops.actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "BOUNCED by owner - back to Working")

            def _bounce(tt):
                tt["status"] = "bounced"; tt["lane"] = "working"
            t = _mutate(tid, _bounce) or t
            _say_card(t, _i18n.t("say.bouncedToWorking"))
            return t
        return sessions._start(tid)   # idempotent: resumes position if already started
    from spine.ops.actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    # ALREADY LANDED - an accept is IDEMPOTENT. status='accepted' is only ever
    # set after a successful merge, so a repeat move to Review/Done has nothing
    # left to gate or land. Re-running the cycle is not merely wasteful, it is
    # destructive: the first accept's reclaim_worktree has (correctly) emptied
    # the worktree, so the second run's gate finds no test files and BOUNCES a
    # card that already shipped.
    #
    # Observed live on card 20260812-164257: Done at 17:32:45 gated green,
    # merged 2 commits and ran the deploy hook; because lane='done' is written
    # only AFTER that ~22s hook, the card still read lane=review, so a second
    # Done at 17:34:32 started a concurrent cycle whose gate (17:34:53) hit the
    # just-reclaimed tree and bounced the card with a bogus "No such file or
    # directory" punch list. Accepting twice must never un-land a card.
    if t.get("status") == "accepted" and lane in ("review", "done"):
        log.log("note", "ALREADY LANDED - accept is a no-op (no re-gate, no re-merge)")

        def _settle(tt):
            tt["lane"] = "done"
            tt.pop("gate_report", None); tt.pop("merge_report", None)
        return _mutate(tid, _settle) or t
    if t.get("machine") and lane in ("review", "done"):
        # no branch, no merge - the owner's accept IS the gate (see _accept_machine)
        return sessions._accept_machine(t, lane, actor, log)
    if lane == "done":
        # A LIVE turn writes to this same track (session_id, last_reply, status)
        # the instant it ends, on its own thread, racing whatever this call is
        # about to do. Measured 2026-08-28 (chat-wear-os-integration-phas): the
        # merge landed on main at 11:35:47 while a worker turn begun at 11:27:50
        # was still in flight; that turn's own _finish_turn then overwrote the
        # just-accepted track back to status=needs_you/lane=review at 11:36:54 -
        # the merge was real (git proves it) but the BOARD forgot it happened.
        # turn_active() is the runtime's own signal (Paseo: never a stored
        # flag), so this bounces on ground truth, not a guess. REVIEW's preview
        # branch below is read-only (classify, no merge) and stays safe to run
        # even mid-turn.
        from spine.agent import drivers as _drivers_ta
        # inflight, not active: a turn QUEUED on the desktop/direct lock will
        # write session_id/last_reply/status exactly the same way once it
        # spawns, so the accept race is identical - it must wait for that too.
        if _drivers_ta.turn_inflight(tid):
            log.log("note", "Karte hat noch einen laufenden Turn - Abnahme wartet, "
                    "bis er fertig ist (sonst ueberschreibt der Turn-Abschluss den "
                    "gerade gelandeten Merge).")
            return _find(_load(), tid) or dict(t)
    if lane in ("review", "done"):
        # Two verbs sharing one prep: clean up + commit, then the gate. REVIEW then
        # CLASSIFIES the merge (dry-run) and RESTS on Review showing the verdict -
        # a deliberate drag to DONE actually merges + deploys. gate-before-merge LAW
        # kept. Any problem keeps the card on Review with a clear reason.
        #
        # Publish "gating" FIRST: the gate is a real subprocess (up to 600s) and
        # the merge + deploy hook follow it, so without this the card looked
        # untouched for minutes while the work ran. Every poller now sees the
        # card is busy; each terminal branch below overwrites this status.
        # No chat line here on purpose - the card's own status covers "started",
        # and chains/policy auto-accept through this path too. The chat carries
        # OUTCOMES (what was missing), not progress chatter.
        def _gating(tt):
            tt["status"] = "gating"
        t = _mutate(tid, _gating) or t
        ac = _autocommit(t)
        if ac == "markers":
            msg = ("Konfliktmarkierungen sind noch im Worktree offen. Steuere den Agenten: "
                   "'loese die Konfliktmarkierungen (<<<<<<< / >>>>>>>) in den Dateien' - "
                   "nur editieren - und reiche dann neu ein.")
            log.log("note", "CONFLICT MARKERS OPEN - stays on Review to resolve: " + msg[:200])

            def _markers(tt):
                tt["status"] = "bounced"; tt["lane"] = "review"   # stay on Review, not back to Working
                tt.pop("gate_report", None)                       # the CURRENT blocker is the conflict
                tt["merge_report"] = msg; tt["merge_kind"] = "conflict"
            t = _mutate(tid, _markers) or t
            from spine.comms import notify
            notify.card_event(t, "bounced")
            _say_card(t, _i18n.t("say.conflictMarkers", detail=msg), kind="blocker")
            t = dict(t); t["merge_failed"] = True; t["merge_kind"] = "conflict"
            return t
        if ac is True:
            log.log("note", "COMMITTED worktree changes on the branch before merge")
        # BASE-SYNC before the gate (debt gate-base-lag). The card's worktree was
        # isolated from the base the whole time it was open, so gating it as-is
        # asks "was this green against the code we forked from?" when the only
        # question that matters is "is it green against the code it will land
        # beside?". Merge the base in first - AFTER _autocommit (so the card's own
        # work is committed and cannot be clobbered) and BEFORE _gate.
        sync = _sync_base(t)
        if sync.startswith("conflict"):
            files = sync.split(":", 1)[1]
            msg = ("Die Basis hat sich weiterbewegt und kollidiert mit dieser Karte. Der "
                   "Harness hat die Basis in deinen Branch geholt - die Konflikte stehen "
                   "jetzt als Markierungen (<<<<<<< / >>>>>>>) im Worktree:\n%s\n"
                   "Steuere den Agenten: 'loese die Konfliktmarkierungen in diesen Dateien' "
                   "(nur editieren, kein git) und reiche neu ein - dann committet der "
                   "Harness und gatet gegen die aktuelle Basis." % files[:400])
            log.log("note", "BASE-SYNC CONFLICT - stays on Review to resolve: " + files[:300])
            events.emit("merge", tid, ok=False, outcome="conflict",
                        detail="base-sync: " + files[:200])

            def _basefail(tt):
                tt["status"] = "bounced"; tt["lane"] = "review"   # stay on Review, not back to Working
                tt.pop("gate_report", None)                       # the CURRENT blocker is the conflict
                tt["merge_report"] = msg; tt["merge_kind"] = "conflict"
            t = _mutate(tid, _basefail) or t
            from spine.comms import notify
            notify.card_event(t, "bounced")
            _say_card(t, _i18n.t("say.baseDrifted", detail=msg), kind="blocker")
            t = dict(t); t["merge_failed"] = True; t["merge_kind"] = "conflict"
            return t
        if sync.startswith("synced"):
            log.log("note", "BASE-SYNC: merged %s base commit(s) into the branch - gating "
                            "against the CURRENT base" % sync.split(":", 1)[1])
        elif sync.startswith("error"):
            # Never block a card on a failed sync: say so, then gate as before.
            log.log("note", "BASE-SYNC skipped (%s) - gating the branch as-is" % sync[6:])
        # the repo's own quality gate (helmdeck.gate command). The committed
        # check now trivially passes because we just committed. Say it in the CARD
        # chat first: the gate runs daemon-side (outside the agent session), so
        # without this the card just spins "In Arbeit"/"Gate laeuft" with nothing in
        # the chat and the owner cannot see WHAT is happening. NB: use the actionlog
        # (log.log note), NOT _say_card - _say_card -> copilot.say lands in the BOARD-
        # Agent chat, but the owner reads the card's WORKER chat, which weaves in
        # these notes (that is why the other lane notes show but _say_card did not).
        log.log("note", _i18n.t("say.gateRunning"))
        ok, problems = _gate(t)
        events.emit("gate", tid, ok=ok, problems=problems)
        if not ok:
            punch = " | ".join(p.split("\n")[0] for p in problems)
            log.log("note", "GATE FAILED - stays on Review to fix: " + punch[:400])

            def _gatefail(tt):
                tt["status"] = "bounced"; tt["lane"] = "review"; tt["gate_report"] = problems   # stay on Review
                tt.pop("merge_report", None); tt.pop("merge_kind", None)   # the CURRENT blocker is the gate
            t = _mutate(tid, _gatefail) or t
            from spine.comms import notify
            notify.card_event(t, "bounced")
            # The chat gets the FULL problem text, not the one-line `punch`:
            # a gate failure's actual output (which test, which assertion) lives
            # on the lines after the header, and the chat is where the owner
            # reads the reason. `punch` stays for the card's compact report.
            _say_card(t, _i18n.t("say.gateRed", detail="\n".join(problems)[:800]), kind="blocker")
            t = dict(t); t["gate_failed"] = True
            return t
        t.pop("gate_report", None)
        log.log("note", _i18n.t("say.gateGreen"))
        if lane == "review":
            # PREVIEW ONLY: say what a Done would do; the card RESTS on Review.
            kind, msg = _classify_merge(t)
            # AUTO-DELEGATION: a "conflict" that is really an uncommitted (dirty)
            # shared checkout, not <<<<<< markers, is an out-of-worktree blocker
            # the sandboxed worker can't fix. Hand it to the board-Agent capability
            # automatically - park the dirty tree on a wip-* branch (nothing lost)
            # and retry, ONCE (_autopark guards recursion).
            if _autopark and kind == "conflict" and _is_dirty_block(msg):
                # actionlog note (shows in the WORKER chat), not _say_card
                log.log("note", _i18n.t("say.mergeBlockedDirty"))
                summary = park_and_retry_merge(tid, actor="board-Agent (auto)")
                log.log("note", _i18n.t("say.mergeUnblocked", detail=summary[:300]))
                return _find(_load(), tid) or dict(t)
            events.emit("merge", tid, ok=(kind not in ("conflict", "blocked")),
                        outcome=kind, detail="preview: " + msg[:200])
            # FAST-TRACK (per-card, SCOPED): a card flagged `fast_track` with a
            # GREEN gate (already checked above) and a clean merge LANDS
            # immediately - no human accept. Only for flagged cards; every other
            # card rests on Review for your accept. The gate still guards (a red
            # gate already bounced above), so this is auto-accept, not skip-gate.
            _clean = kind in ("mergeable", "already_merged", "redundant_uncommitted")
            _fast = bool(t.get("fast_track")) and _clean
            # GxP: fast-track is the one path that turns a Review INTO a landing
            # without a second call, so the chokepoint at the top of this
            # function never sees it as a 'done'. Refused here instead, by
            # demoting it to an ordinary review - the card then rests for a human
            # like every other card.
            #
            # ONLY for a card in the regulated scope. Fast-track is not a flaw to
            # be removed, it is the product working; it stays fully alive on
            # every card that is not aimed at a validated artefact.
            if _fast and gxp.in_scope(t) and gxp.disabled("fast_track"):
                events.emit("gxp", tid, outcome="fast_track_refused", actor=actor)
                log.log("note", "GxP: Fast-Track ist abgeschaltet - die Karte wartet auf Freigabe.")
                _fast = False
            if not _fast:
                log.log("note", "REVIEW-Vorschau (%s): %s" % (kind, msg[:200]))

                def _submit(tt):
                    tt.pop("merge_report", None)
                    tt.pop("gate_report", None)          # gate just ran green
                    tt["merge_kind"] = kind; tt["review_report"] = msg
                    tt["status"] = "submitted"; tt["lane"] = "review"
                t = _mutate(tid, _submit) or t
                _VERDICT = {"mergeable": "verdict.mergeable",
                            "already_merged": "verdict.alreadyMerged",
                            "redundant_uncommitted": "verdict.alreadyMerged",
                            "conflict": "verdict.conflict"}
                _verdict = (_i18n.t(_VERDICT[kind]) if kind in _VERDICT
                            else _i18n.t("verdict.other", detail=msg[:200]))
                _say_card(t, _i18n.t("say.reviewChecked", verdict=_verdict))
                return dict(t, review_preview=True, merge_kind=kind)
            log.log("note", "FAST-TRACK %s: gruenes Gate + sauberer Merge -> lande + deploye ohne Abnahme"
                    % t.get("branch", ""))
        # lane == "done" (or a fast-tracked review): LAND it
        _repo_hook(t, "preview")   # best-effort try-it surface before it lands
        # classify + merge to main - conflict/blocked bounces with the resolve path
        accept_ok, kind, mergemsg = _merge_to_main(t)
        if not accept_ok and kind == "conflict":
            # HARNESS-side resolve: pull main INTO the card's branch so resolving is
            # an EDIT task, not an (impossible) agent merge. Auto-resolved -> retry
            # the landing; otherwise leave editable markers + a clear instruction.
            res = _pull_main_into_branch(t)
            if res == "resolved":
                log.log("note", "AUTO-RESOLVED: merged main into the branch, retrying")
                accept_ok, kind, mergemsg = _merge_to_main(t)
            elif res.startswith("markers"):
                files = res.split(":", 1)[1]
                mergemsg = ("Der Harness hat main in deinen Branch geholt - die Konflikte "
                            "stehen jetzt als Markierungen im Worktree (%s). Steuere den Agenten: "
                            "'loese die Konfliktmarkierungen in diesen Dateien' (nur editieren). "
                            "Danach neu auf Review - der Harness committet und mergt dann selbst." % files)
        events.emit("merge", tid, ok=accept_ok, outcome=kind, detail=mergemsg[:300])
        if not accept_ok:
            log.log("note", "MERGE %s - stays on Review to resolve: %s" % (kind.upper(), mergemsg[:400]))

            def _mergefail(tt):
                tt["status"] = "bounced"; tt["lane"] = "review"   # stay on Review, not back to Working
                tt["merge_report"] = mergemsg; tt["merge_kind"] = kind
                tt.pop("gate_report", None)          # gate ran green before the merge
            t = _mutate(tid, _mergefail) or t
            from spine.comms import notify
            notify.card_event(t, "bounced")
            # NB the two `kind=` here are different things: the inner one is the
            # merge outcome the message interpolates, the outer one is this
            # message's INBOX class. A failed landing stops the card.
            _say_card(t, _i18n.t("say.cannotLand", kind=kind, detail=mergemsg[:400]),
                      kind="blocker")
            t = dict(t); t["merge_failed"] = True; t["merge_kind"] = kind
            return t
        _NOTE = {"merged": "MERGED -> main", "already_merged": "REDUNDANT (bereits in main) - geschlossen",
                 "redundant_uncommitted": "REDUNDANT (bereits in main; uncommittete Aenderungen ignoriert) - geschlossen"}
        log.log("note", "%s: %s" % (_NOTE.get(kind, "ACCEPTED"), mergemsg[:280]))
        # GxP: burn the signature that authorised THIS landing. A record left
        # open would still read as "approved" against a merged card and could
        # authorise a second landing after the branch moved on. Records the
        # merge it was spent on, so the audit joins signature -> commit.
        if gxp.in_scope(t):
            from spine.auth import signatures as _sigs
            _spent = _sigs.valid_open(t)
            if _spent:
                _merge_sha = _git_try(t.get("repo") or ".", "rev-parse", "HEAD")[1]

                def _burn(tt):
                    for s in tt.get("signatures") or []:
                        if s.get("seq") == _spent.get("seq"):
                            s["consumed_by"] = {"lane": "done", "at": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                            s.setdefault("git", {})["merge_sha"] = _merge_sha
                t = _mutate(tid, _burn) or t
                events.emit("signature", tid, op="consumed", seq=_spent.get("seq"),
                            actor=_spent.get("actor"), merge_sha=_merge_sha)
        events.emit("touch", tid, touch="review", actor=actor)
        te = [e for e in events.read_events() if e.get("track") == tid]
        mode = events._completion_mode(te, t.get("turns"))
        events.emit("done", tid, mode=mode, ai_cost=t.get("ai_cost", 0.0),
                    value=t.get("value"), models=t.get("models", []),
                    tokens_in=t.get("tokens_in", 0), tokens_out=t.get("tokens_out", 0))
        log.log("note", "ACCEPTED (%s) - AI $%.4f, value %s" %
                (mode, t.get("ai_cost", 0.0), t.get("value")))

        def _accepted(tt):
            tt.pop("merge_report", None); tt.pop("gate_report", None)
            tt["merge_kind"] = kind
            tt["status"] = "accepted"; tt["mode"] = mode
            _record_outcome(tt)
        t = _mutate(tid, _accepted) or t
        # Owner decree 2026-09-01: the deploy hook does NOT fire here anymore.
        # A landing hands the SHIP DECISION to Henry (request_ship_decision);
        # he judges from the live snapshot (locks, box load, what changed) and
        # the broker executes his kind through _repo_hook + SHIP_KIND. The old
        # deploy-red emit for a failed post-accept deploy moved with the
        # execution: a red ship now keeps its ship-decision escalation open,
        # which IS the agentic retry (2-attempt cap, then the owner).
        _ship_eid = request_ship_decision(t, "accept")
        # A landing was the QUIETEST outcome of all: no push (card_event was only
        # ever called for bounces) and no chat line. Report it like any other.
        _LANDED = {"merged": "say.landed.merged",
                   "already_merged": "say.landed.redundant",
                   "redundant_uncommitted": "say.landed.redundant"}
        _say_card(t, _i18n.t(_LANDED.get(kind, "say.landed.plain")) + (
            _i18n.t("say.shipHenry") if _ship_eid else ""))
        from spine.comms import notify
        notify.card_event(t, "done")
        try:
            from cells.copilot import pm
            pm.on_card_done(tid)   # re-judge the golden triangle at event time
        except Exception:
            pass
        if t.get("connector"):
            from cells.engineer import connectors
            from spine.ops import checkpoints
            checkpoints.create(actor=actor, reason="connector install: " + t.get("connector", ""))
            try:
                inst = connectors.install_from_worktree(t)
                if inst:
                    log.log("note", "CONNECTOR INSTALLED: " + ", ".join(inst))
                    events.emit("connector", tid, action="installed", files=inst)
            except RuntimeError as e:
                log.log("note", str(e)[:400])
                events.emit("connector", tid, action="charter_blocked", detail=str(e)[:300])
        reclaim_worktree(t, log)   # isolation reclaimed: the work is in main now
        lane = "done"   # Review == Abnahme: a finished card lands in Done
    elif lane == "backlog":
        # Re-queueing a card IS the "run it again" instruction, so the
        # auto-dispatchers' one-shot stamps must not survive it (a re-queued
        # autopilot card otherwise keeps autopilot=true but never dispatches
        # again). status=queued + the stamp clearing happen in the _land
        # mutate below - one writer, no local-copy drift.
        # the chain keeps its OWN stamps on the step (processes.json), which the
        # loop above cannot reach - without this the card came back clean but
        # its step stayed "already dispatched" and never ran again.
        try:
            from cells.engineer import processes
            processes.clear_step_stamps(tid)
        except Exception as e:      # a board move must not fail on the chain store
            print("clear_step_stamps failed for %s: %s" % (tid, e))
    events.emit("lane", tid, frm=prev, to=lane)
    _hooks = {k: t[k] for k in ("preview_hook", "deploy_hook") if k in t}

    def _land(tt):
        tt["lane"] = lane
        if lane == "backlog":
            tt["status"] = "queued"
            for k in ("autopilot_dispatched", "autopilot_accepted",
                      "autopilot_alerted", "autopilot_ts", "priority_dispatched"):
                tt.pop(k, None)
        # the repo hooks ran on the local copy (they are subprocesses and must
        # stay outside the mutation lock) - persist their outcome here.
        tt.update(_hooks)
    t = _mutate(tid, _land) or t
    return t



def _is_dirty_block(msg):
    """True when a 'conflict' is really git refusing to merge over an uncommitted
    (dirty) checkout - NOT real <<<<<< markers. That's an out-of-worktree blocker
    the sandboxed worker can't fix, so the board-Agent parks + retries."""
    m = (msg or "").lower()
    return "<<<<<<<" not in (msg or "") and (
        "would be overwritten by merge" in m
        or "local changes to the following" in m
        or "commit your changes or stash" in m)


def park_and_retry_merge(tid, actor="owner"):
    """Unblock a card whose review/merge is blocked by an uncommitted (dirty)
    working tree in its repo - NOT a real <<<<<< conflict, but git refusing to
    merge over local changes ("your local changes ... would be overwritten").

    Park ALL uncommitted work (tracked + untracked) onto a wip-<branch>-<ts>
    branch - nothing lost, the checkout goes clean - then re-run the review
    check. NON-DESTRUCTIVE (only ever adds a branch/commit; never discards).

    This is the board-Agent's job, not the sandboxed card worker's: the worker
    is confined to its worktree and cannot reach the shared main checkout by
    design, so this cross-cutting unblock belongs to the board-wide agent, gated
    by the owner's explicit instruction. Returns a human summary."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if t.get("machine"):
        # its "repo" is a folder on the owner's PC - never run branch surgery there
        return ("'%s' ist eine Maschinen-Aufgabe (Ordner %s), kein Branch - da gibt es "
                "nichts zu parken. Steuere sie einfach weiter."
                % (tid, t.get("worktree") or "?"))
    repo = t.get("repo")
    if not repo or not is_git_repo(repo):
        return "cannot park: card '%s' has no git repo" % tid
    status = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                            capture_output=True, text=True).stdout.strip()
    parked = ""
    if status.strip():
        cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        wip = "wip-%s-%s" % (_slug(cur), time.strftime("%Y%m%d-%H%M%S"))
        _git(repo, "checkout", "-b", wip)
        _git(repo, "add", "-A")
        _git(repo, *AGENT_IDENT, "commit", "-m",
             "wip: park uncommitted %s work so card %s could merge (by %s)" % (cur, t["branch"], actor))
        _git(repo, "checkout", cur)     # back on the original branch, now clean
        parked = wip
        from spine.storage import events
        events.log("merge", "parked dirty tree of %s onto %s to unblock %s (%s)"
                   % (cur, wip, t["branch"], actor))
    # tree is clean now -> re-run the review/merge check (no auto-park recursion)
    r = move_lane(tid, "review", actor=actor, _autopark=False)
    if r.get("gate_failed"):
        return "parked onto '%s', but the gate is red: %s" % (parked or "-", " | ".join(r.get("gate_report") or [])[:200])
    if r.get("merge_failed"):
        return "parked onto '%s', but the card still can't merge: %s" % (parked or "-", (r.get("merge_report") or "")[:200])
    head = ("Parked the uncommitted work onto branch '%s' (nothing lost) - " % parked) if parked else "The tree was already clean - "
    return head + "the review check now passes. Move the card to Done to land it."


