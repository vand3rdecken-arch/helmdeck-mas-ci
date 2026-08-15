# -*- coding: utf-8 -*-
"""Pins `_repo_hook`'s streaming rewrite (2026-08-15).

Live incident: a native APK build hook ran silently for ~10-15 minutes -
the OLD `_repo_hook` buffered all output via `subprocess.run(capture_output=
True)` and only logged the final tail once the process exited, so the chat
showed nothing at all in between. From the owner's phone that looked
identical to a genuinely stuck card (which had ALSO happened earlier that
same day for an unrelated reason), so a perfectly healthy long build kept
getting mistaken for a hang.

Fix: `_repo_hook` now streams stdout line-by-line via a pump thread + queue
(so a real wall-clock deadline can be enforced even when the child produces
sparse output - a blocking `for line in proc.stdout` can't do that on its
own), and any line prefixed `HOOK-NOTE:` is logged to the actionlog THE
MOMENT it's read, not just folded into the final tail. `deploy/ship.sh` is
expected to emit these at its own decision points (native vs JS-only, "APK
build running, ~10-15 min") - this test only pins `_repo_hook`'s own
contract: the mechanism, not that specific script's prompts.

Not mocked - `_repo_hook` always shells out for real, so this test spawns
REAL child processes. Each hook body is a real .py FILE (not a `-c`
one-liner) invoked as `"<python.exe>" script.py` - cmd.exe (shell=True on
Windows) mangles both an unquoted exe path containing spaces (this box's
own username has one) and embedded newlines inside a `-c` argument, so a
script file sidesteps both traps cleanly. ActionLog is real too (writes
into a tempdir), so the notes are read back to assert on. Nothing touches
the actual repo/board.

Run: py -3.12 daemon/test_repo_hook_streaming.py
"""
import json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import events, sessions


def _notes(run_dir):
    p = os.path.join(run_dir, "actions.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("kind") == "note":
                out.append(d.get("detail") or "")
    return out


def _write_script(tmp, name, body):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


def _hook_cmd(script_path):
    # quote BOTH paths - the python.exe path and the script path can each
    # contain spaces (this box's own username does)
    return '"%s" "%s"' % (sys.executable, script_path)


def main():
    real_settings, real_timeout = events.settings, sessions._HOOK_TIMEOUT
    tmp = tempfile.mkdtemp(prefix="helmdeck-test-")
    try:
        # -- HOOK-NOTE lines are logged live, final summary reflects success --
        run_dir = os.path.join(tmp, "run-ok")
        os.makedirs(run_dir)
        ok_script = _write_script(tmp, "ok_hook.py", (
            'import time\n'
            'print("HOOK-NOTE: native change -> APK build laeuft (~10-15 Min)", flush=True)\n'
            'time.sleep(0.05)\n'
            'print("some other build chatter line", flush=True)\n'
            'print("HOOK-NOTE: done, uploading", flush=True)\n'
        ))
        events.settings = lambda: {"repo_hooks": {tmp: {"deploy": _hook_cmd(ok_script)}}}
        t = {"repo": tmp, "worktree": tmp, "run_dir": run_dir}
        ok = sessions._repo_hook(t, "deploy")
        assert ok is True, "expected a clean-exit hook to report ok=True, got %r\ntail=%s" % (
            ok, t.get("deploy_hook", {}).get("tail"))
        assert t["deploy_hook"]["ok"] is True
        notes = _notes(run_dir)
        # the live-streamed notes are everything EXCEPT the opening "HOOK:"
        # announcement and the closing "HOOK OK/FAILED:" summary (which
        # legitimately repeats the whole tail, chatter line included) -
        # isolate those to check what actually streamed live, not the summary.
        live = [n for n in notes if not n.startswith(("DEPLOY HOOK:", "DEPLOY HOOK OK:",
                                                        "DEPLOY HOOK FAILED:"))]
        assert live == ["native change -> APK build laeuft (~10-15 Min)", "done, uploading"], \
            "live-streamed notes don't match exactly the two HOOK-NOTE lines: %r" % live
        print("PASS: HOOK-NOTE lines are logged live as their own actionlog notes; "
              "non-prefixed output stays out of the live stream (only in the final summary)")

        # -- a real failure still reports ok=False with the tail captured -----
        run_dir2 = os.path.join(tmp, "run-fail")
        os.makedirs(run_dir2)
        fail_script = _write_script(tmp, "fail_hook.py",
            'import sys\nprint("boom")\nsys.exit(1)\n')
        events.settings = lambda: {"repo_hooks": {tmp: {"deploy": _hook_cmd(fail_script)}}}
        t2 = {"repo": tmp, "worktree": tmp, "run_dir": run_dir2}
        ok2 = sessions._repo_hook(t2, "deploy")
        assert ok2 is False, "expected a nonzero-exit hook to report ok=False, got %r" % ok2
        assert "boom" in t2["deploy_hook"]["tail"]
        print("PASS: a failing hook still reports ok=False with output captured")

        # -- a wall-clock deadline is enforced even with NO output at all -----
        run_dir3 = os.path.join(tmp, "run-timeout")
        os.makedirs(run_dir3)
        sessions._HOOK_TIMEOUT = 0.3   # real deadline, no monkeypatched clock needed
        hang_script = _write_script(tmp, "hang_hook.py",
            'import time\ntime.sleep(5)\n')   # silent AND slow
        events.settings = lambda: {"repo_hooks": {tmp: {"deploy": _hook_cmd(hang_script)}}}
        t3 = {"repo": tmp, "worktree": tmp, "run_dir": run_dir3}
        ok3 = sessions._repo_hook(t3, "deploy")
        assert ok3 is False, "a hook stuck past the deadline must report ok=False, got %r" % ok3
        assert "timed out" in t3["deploy_hook"]["tail"]
        print("PASS: a wall-clock deadline is enforced even when the child produces "
              "zero output (the old blocking-readline shape couldn't do this)")

        print("ALL PASS")
    finally:
        events.settings, sessions._HOOK_TIMEOUT = real_settings, real_timeout


if __name__ == "__main__":
    main()
