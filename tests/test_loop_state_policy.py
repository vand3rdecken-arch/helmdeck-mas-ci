# -*- coding: utf-8 -*-
"""Self-sandboxing test for tools/loop_state.py's _build_loop_enabled() - the
REAL enable flag for Cell #6 (cells.py "buildloop"). This is the ONE
test in the whole daemon suite where the md5-before/after check on
daemon/policy_live.json is not optional: this function reads that exact file
to decide whether to silence the Stop hook currently governing THIS agent's
own session, so a test that accidentally touched the real file would be a
real, not hypothetical, incident.

Sandboxing: loop_state._POLICY_ROOT is a module-level override (see
loop_state.py's own docstring on it) pointed at a tempfile.mkdtemp() BEFORE
any read - never the real daemon/ directory.

Run: py -3.12 test_loop_state_policy.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    real_live = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy_live.json")
    with open(real_live, "rb") as f:
        import hashlib
        before_hash = hashlib.md5(f.read()).hexdigest()

    import loop_state

    tmp = tempfile.mkdtemp(prefix="helmdeck-loopstate-test-")
    loop_state._POLICY_ROOT = tmp   # NEVER the real daemon/ dir

    # -- no files at all: fail-open ------------------------------------------
    ok(loop_state._build_loop_enabled() is True,
       "no policy files at all: fails OPEN (True) - never silently disables the safety net")

    # -- seed says true, no live yet (matches real production TODAY: live -----
    # predates this flag entirely) --------------------------------------------
    with open(os.path.join(tmp, "policy_seed.json"), "w", encoding="utf-8") as f:
        json.dump({"policies": {"buildLoopEnabled": True}}, f)
    ok(loop_state._build_loop_enabled() is True, "seed=true, no live file: True")

    # -- live exists but doesn't have the key (the EXACT real-world condition -
    # confirmed by reading the real policy_live.json: it predates all 6 Cell
    # flags, not just this one) - must default True via dict.get(), not fall
    # through to seed (there's no exception, live parses fine) ---------------
    with open(os.path.join(tmp, "policy_live.json"), "w", encoding="utf-8") as f:
        json.dump({"policies": {"gateBeforeReview": True}}, f)
    ok(loop_state._build_loop_enabled() is True,
       "live exists but lacks buildLoopEnabled entirely: defaults True (dict.get default)")

    # -- live explicitly says false: the ONE case that actually silences the --
    # Stop hook ----------------------------------------------------------------
    with open(os.path.join(tmp, "policy_live.json"), "w", encoding="utf-8") as f:
        json.dump({"policies": {"buildLoopEnabled": False}}, f)
    ok(loop_state._build_loop_enabled() is False, "live=false: correctly returns False")

    # -- corrupt live file: falls through to seed (True), never crashes, ------
    # never silently disables -------------------------------------------------
    with open(os.path.join(tmp, "policy_live.json"), "w", encoding="utf-8") as f:
        f.write("{not valid json")
    ok(loop_state._build_loop_enabled() is True,
       "corrupt live file: falls through to seed (True), fails open")

    # -- stop_hook() itself: with buildLoopEnabled=False it must print NOTHING -
    # and exit cleanly, even mid-loop (dirty tree + no workorder = the ALIGN --
    # block that would normally fire) ------------------------------------------
    with open(os.path.join(tmp, "policy_live.json"), "w", encoding="utf-8") as f:
        json.dump({"policies": {"buildLoopEnabled": False}}, f)
    import io, contextlib
    buf_out, buf_in = io.StringIO(), io.StringIO("{}")
    old_stdin = sys.stdin
    sys.stdin = buf_in
    try:
        with contextlib.redirect_stdout(buf_out):
            loop_state.stop_hook()
    finally:
        sys.stdin = old_stdin
    ok(buf_out.getvalue() == "", "stop_hook() with buildLoopEnabled=false prints nothing (no block, ever)")

    # -- real repo, read-only: matches the live md5 check below anyway, but ---
    # also assert the REAL policy state resolves True (it does today) --------
    loop_state._POLICY_ROOT = loop_state.DAEMON
    ok(loop_state._build_loop_enabled() is True,
       "real repo (untouched): buildLoopEnabled resolves True")

    with open(real_live, "rb") as f:
        import hashlib
        after_hash = hashlib.md5(f.read()).hexdigest()
    ok(before_hash == after_hash,
       "daemon/policy_live.json byte-identical before/after - NOT optional for this test")

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
