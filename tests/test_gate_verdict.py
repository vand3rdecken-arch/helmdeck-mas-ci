# -*- coding: utf-8 -*-
"""Headless test for sessions._gate's exit-code-vs-stdout-verdict cross-check
(debt gate-exit-code-vs-stdout-verdict).

Card 20260812-164257 bounced with a gate_report of "gate FAILED:" wrapping a
body of 34 straight "ok" lines ending in tools/run_gate.py's own
"gate: PASS (34 checks)" - the shell-level returncode disagreed with the
script's own definitive verdict. _gate() now trusts run_gate.py's printed
verdict over a contradicting returncode, and still hard-fails when the
verdict itself is red or missing (a real crash/timeout must still bounce).

Self-sandboxing: a throwaway git repo + a hand-written helmdeck.gate command
that mimics each shape via a tiny inline Python script - no real
tools/run_gate.py invocation, no daemon, no network."""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)
import sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def clean_repo():
    """A committed worktree (git status --porcelain empty) so _gate() reaches
    the gate-command check instead of bouncing on 'uncommitted changes'."""
    d = tempfile.mkdtemp()
    git(d, "init")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")
    git(d, "config", "user.email", "t@t.t")
    git(d, "config", "user.name", "t")
    with open(os.path.join(d, "f.txt"), "w") as f:
        f.write("x\n")
    git(d, "add", "-A")
    git(d, "commit", "-m", "init")
    return d


def gate_track(repo, gate_body):
    """gate_body is a Python program's source, run via `%s -c "<body>"` so the
    test needs no extra script file - the .gate command IS the check. Commit
    it (not leave it untracked) - _gate() bounces on ANY dirty worktree, and
    that would mask the exit-code cross-check this test is actually about."""
    with open(os.path.join(repo, "helmdeck.gate"), "w", encoding="utf-8") as f:
        f.write('"%s" -c "%s"' % (sys.executable.replace("\\", "\\\\"),
                                   gate_body.replace('"', '\\"')))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "gate command")
    return {"repo": repo, "worktree": repo, "id": "t-gate"}


PRINT_PASS_EXIT_NONZERO = (
    "print('ok    fake_check.py'); "
    "print('gate: PASS (1 checks)'); "
    "import sys; sys.exit(1)"
)
PRINT_FAIL_EXIT_NONZERO = (
    "print('FAIL  fake_check.py'); "
    "print('=== GATE FAILED (1) ==='); "
    "import sys; sys.exit(1)"
)
CRASH_NO_VERDICT = "import sys; sys.stderr.write('boom, no verdict printed\\n'); sys.exit(3)"


def test_pass_verdict_overrides_nonzero_returncode():
    # the exact shape of the live incident: script prints a clean PASS verdict
    # but the OS-level returncode is nonzero - _gate() must NOT bounce this.
    repo = clean_repo()
    t = gate_track(repo, PRINT_PASS_EXIT_NONZERO)
    ok, problems = sessions._gate(t)
    check(ok and not problems,
          "a contradicting nonzero returncode does not bounce a card whose "
          "gate script printed its own PASS verdict (got ok=%r problems=%r)"
          % (ok, problems))


def test_real_failure_still_bounces():
    # a genuine red gate (verdict says FAILED) must still bounce - the
    # override only ever helps a PASS verdict, never masks a real FAIL.
    repo = clean_repo()
    t = gate_track(repo, PRINT_FAIL_EXIT_NONZERO)
    ok, problems = sessions._gate(t)
    check(not ok and problems,
          "a genuine GATE FAILED verdict still bounces the card")
    check(any("GATE FAILED" in p or "gate FAILED" in p for p in problems),
          "the failure detail reaches the card (not swallowed by the override)")


def test_crash_with_no_verdict_still_bounces():
    # a crash before the script ever prints ITS verdict must still bounce -
    # the override only fires when a PASS sentinel is actually present.
    repo = clean_repo()
    t = gate_track(repo, CRASH_NO_VERDICT)
    ok, problems = sessions._gate(t)
    check(not ok and problems,
          "no verdict printed at all (a crash) still bounces, never silently passes")


def test_reclaimed_worktree_reports_itself():
    # After a card lands, reclaim_worktree empties the tree; on Windows the
    # now-empty DIRECTORY often survives (a shell still holds it open), so
    # os.path.exists(wt) still says yes. The gate must recognise that instead
    # of running the suite in an empty dir and emitting one
    # "can't open file ...: No such file or directory" per test.
    wt = tempfile.mkdtemp()          # exists, but holds no .git and no files
    ok, problems = sessions._gate({"repo": wt, "worktree": wt, "id": "t-reclaimed"})
    check(not ok and problems, "a reclaimed worktree fails the gate (not a silent pass)")
    check(any("reclaimed" in p for p in problems),
          "the reason names the RECLAIMED TREE, not a wall of missing test files")
    check(not any("No such file or directory" in p for p in problems),
          "no misleading per-test 'No such file' spam in the punch list")


def test_clean_pass_returncode_zero_unaffected():
    # the ordinary green-gate path (matching returncode + verdict) is
    # untouched by the new cross-check.
    repo = clean_repo()
    t = gate_track(repo, "print('ok    fake_check.py'); print('gate: PASS (1 checks)')")
    ok, problems = sessions._gate(t)
    check(ok and not problems, "an ordinary clean pass (returncode 0) still passes")


if __name__ == "__main__":
    test_pass_verdict_overrides_nonzero_returncode()
    test_real_failure_still_bounces()
    test_crash_with_no_verdict_still_bounces()
    test_reclaimed_worktree_reports_itself()
    test_clean_pass_returncode_zero_unaffected()
    print("OK" if not _fails else "FAILED: %d" % len(_fails))
    sys.exit(1 if _fails else 0)
