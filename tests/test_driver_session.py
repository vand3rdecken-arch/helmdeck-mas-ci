# -*- coding: utf-8 -*-
"""Headless tests for the persistent stream-json driver session (drivers.py).

Proves the three contracts the Paseo port must hold, without the real CLI:
  1. reuse   - two turns run through ONE persistent process (pid stable).
  2. bounded - a hung turn is killed at the timeout and run_turn RETURNS
               (raises) instead of blocking forever - the old deadlock.
  3. cancel  - Stop unblocks the turn cleanly and tree-kills the session.

Uses the fake_claude.cmd stand-in via the drivers.CLAUDE seam. Self-sandboxing:
its own pid-file + temp run dirs, no daemon, no board state."""
import os, sys, time, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)

import drivers

# Generate the fake-CLI wrapper with the ABSOLUTE python path (the bare `py`
# launcher isn't guaranteed on a spawned process's PATH). The driver's
# cmd /s /c wrapping handles the spaces in this path.
_WRAP = os.path.join(tempfile.mkdtemp(), "fake_claude.cmd")
with open(_WRAP, "w", encoding="utf-8") as _f:
    _f.write('@echo off\r\n"%s" "%s" %%*\r\n'
             % (sys.executable, os.path.join(HERE, "fake_claude.py")))
drivers.CLAUDE = _WRAP
drivers._PIDFILE = os.path.join(tempfile.mkdtemp(), "driver_pids.json")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _track(tid):
    return {"id": tid, "worktree": os.getcwd(),
            "run_dir": tempfile.mkdtemp(), "session_id": None}


def test_reuse():
    cfg = {"type": "claude", "timeout": 15}
    t = _track("t-reuse")
    s = drivers._get_session(cfg, t)
    sid, res, meta = s.run_turn("hello", t["run_dir"])
    check(res == "echo:hello", "turn 1 echoes input (got %r)" % res)
    check(sid == "fake-session-123", "session_id captured from init")
    check(meta.get("cost_usd") == 0.001, "economics parsed from result event")
    pid1 = s.proc.pid
    sid2, res2, meta2 = s.run_turn("again", t["run_dir"])
    check(res2 == "echo:again", "turn 2 echoes input (got %r)" % res2)
    check(s.proc.pid == pid1, "SAME process served both turns (persistent session)")
    drivers.cancel("t-reuse")
    check(not s.alive(), "session dead after cancel")


def test_timeout_is_bounded():
    os.environ["FAKE_HANG"] = "1"
    try:
        cfg = {"type": "claude", "timeout": 2}
        t = _track("t-hang")
        s = drivers._get_session(cfg, t)
        start = time.time()
        raised = ""
        try:
            s.run_turn("hang", t["run_dir"])
        except RuntimeError as e:
            raised = str(e)
        elapsed = time.time() - start
        check("exceeded" in raised, "hung turn raised a timeout (got %r)" % raised[:60])
        check(elapsed < 8, "run_turn RETURNED near the 2s timeout (%.1fs) - no deadlock" % elapsed)
        check(not s.alive(), "session tree-killed after timeout")
    finally:
        os.environ.pop("FAKE_HANG", None)


def test_cancel_clean():
    cfg = {"type": "claude", "timeout": 15}
    t = _track("t-cancel")
    s = drivers._get_session(cfg, t)
    # run one turn so a live session exists, then cancel returns clean state
    s.run_turn("hi", t["run_dir"])
    drivers._cancelled.discard("t-cancel")
    # a cancelled in-flight turn returns the sentinel, not an exception
    import threading
    result = {}

    def go():
        try:
            os.environ["FAKE_HANG"] = "1"
            s2 = drivers._get_session({"type": "claude", "timeout": 30},
                                      {"id": "t-cancel2", "worktree": os.getcwd(),
                                       "run_dir": tempfile.mkdtemp(), "session_id": None})
            result["r"] = s2.run_turn("hang", tempfile.mkdtemp())
        except Exception as e:
            result["err"] = str(e)

    th = threading.Thread(target=go)
    th.start()
    time.sleep(2)
    drivers.cancel("t-cancel2")
    th.join(timeout=10)
    os.environ.pop("FAKE_HANG", None)
    check(not th.is_alive(), "cancel unblocked the waiting turn")
    r = result.get("r")
    check(bool(r) and r[1] == "(turn cancelled by you)",
          "cancelled turn returns clean sentinel (got %r)" % (r[1] if r else result.get("err")))


def test_idle_eviction_and_resume():
    cfg = {"type": "claude", "timeout": 15}
    t = {"id": "t-idle", "worktree": os.getcwd(),
         "run_dir": tempfile.mkdtemp(), "session_id": None}
    s = drivers._get_session(cfg, t)
    sid, _, _ = s.run_turn("hi", t["run_dir"])
    pid1 = s.proc.pid
    # sweep with ttl 0 -> the idle session is reaped and killed
    gone = drivers.sweep_idle(ttl=0)
    check("t-idle" in gone, "idle session reaped by sweep")
    check("t-idle" not in drivers._sessions, "reaped session removed from registry")
    check(not s.alive(), "reaped session's process tree killed")
    # next steer transparently respawns + resumes the SAME conversation id
    t["session_id"] = sid                    # the track persists the session id
    s2 = drivers._get_session(cfg, t)
    sid2, res2, _ = s2.run_turn("again", t["run_dir"])
    check(sid2 == sid, "resumed the same session id after eviction (%s)" % (sid2 == sid))
    check(res2 == "echo:again", "post-evict turn works")
    check(s2.proc.pid != pid1, "post-evict turn is a NEW process (respawned)")
    drivers.cancel("t-idle")


def test_inflight_not_evicted():
    os.environ["FAKE_HANG"] = "1"
    try:
        import threading
        cfg = {"type": "claude", "timeout": 30}
        t = {"id": "t-busy", "worktree": os.getcwd(),
             "run_dir": tempfile.mkdtemp(), "session_id": None}
        s = drivers._get_session(cfg, t)
        th = threading.Thread(target=lambda: s.run_turn("hang", t["run_dir"]).__str__(),
                              daemon=True)
        th.start()
        time.sleep(2)                        # let the turn be in flight
        gone = drivers.sweep_idle(ttl=0)     # aggressive ttl - must STILL skip a busy session
        check("t-busy" not in gone, "in-flight turn is NOT evicted despite ttl=0")
        check("t-busy" in drivers._sessions, "busy session stays in the registry")
    finally:
        os.environ.pop("FAKE_HANG", None)
        drivers.cancel("t-busy")


def test_live_opts_change_no_respawn():
    t = {"id": "t-opts", "worktree": os.getcwd(),
         "run_dir": tempfile.mkdtemp(), "session_id": None}
    s = drivers._get_session({"type": "claude", "timeout": 15, "model": "claude-a"}, t)
    s.run_turn("hi", t["run_dir"])
    pid1 = s.proc.pid
    # steer with a DIFFERENT model + mode -> applied live via control plane
    s2 = drivers._get_session({"type": "claude", "timeout": 15, "model": "claude-b",
                               "perm": "plan"}, t)
    check(s2 is s, "same session object kept across a model/mode change")
    check(s2.proc.pid == pid1, "model/mode change applied LIVE - no respawn")
    check(s2.sig[1] == "claude-b" and s2.sig[0] == "plan", "session sig updated to new opts")
    r = s2.run_turn("again", t["run_dir"])
    check(r[1] == "echo:again", "turn works after live opts change")
    drivers.cancel("t-opts")


def test_tool_grant_forces_respawn():
    t = {"id": "t-tools", "worktree": os.getcwd(),
         "run_dir": tempfile.mkdtemp(), "session_id": None}
    s = drivers._get_session({"type": "claude", "timeout": 15}, t)
    s.run_turn("hi", t["run_dir"])
    pid1 = s.proc.pid
    # a tool-grant change cannot be applied live -> must respawn
    s2 = drivers._get_session({"type": "claude", "timeout": 15,
                               "allowed_tools": ["mcp__x__*"]}, t)
    check(s2.proc.pid != pid1, "allowed-tools change forces a respawn (new process)")
    drivers.cancel("t-tools")


def test_structured_error_and_nightshift():
    import sys as _sys
    dmn = os.path.join(os.path.dirname(HERE), "daemon")
    if dmn not in _sys.path:
        _sys.path.insert(0, dmn)
    t = {"id": "t-err", "worktree": os.getcwd(),
         "run_dir": tempfile.mkdtemp(), "session_id": None}
    s = drivers._get_session({"type": "claude", "timeout": 15}, t)
    sid, res, meta = s.run_turn("__ERR__", t["run_dir"])
    check(meta.get("is_error") is True, "result is_error surfaced in meta")
    check(meta.get("subtype") == "error_during_execution", "result subtype surfaced")
    check("usage limit" in (meta.get("error") or ""), "structured error string surfaced")
    # _limit_hit moved to pm.py when nightshift.py was absorbed there (the old
    # `import nightshift` kept "working" as a namespace package - the
    # daemon/nightshift/ REPORTS folder - and then failed on the attribute)
    import pm
    track = {"last_subtype": meta.get("subtype"), "last_error": meta.get("error"),
             "last_reply": "all fine here"}   # reply is clean; only structured field flags it
    check(pm._limit_hit(track), "night shift detects limit from STRUCTURED field, not prose")
    drivers.cancel("t-err")


def test_cancel_interrupt_keeps_alive():
    import threading
    t = {"id": "t-keep", "worktree": os.getcwd(),
         "run_dir": tempfile.mkdtemp(), "session_id": None}
    s = drivers._get_session({"type": "claude", "timeout": 30}, t)
    res = {}
    # __HANG__ makes THIS turn hang (per-message, not env) so the process can run
    # a normal turn afterwards - the point of keep-alive.
    th = threading.Thread(target=lambda: res.__setitem__("r", s.run_turn("__HANG__", t["run_dir"])),
                          daemon=True)
    th.start()
    time.sleep(2)
    pid1 = s.proc.pid
    s.cancel()                          # soft interrupt -> fake ends the turn, process lives
    th.join(timeout=10)
    check(res.get("r") and res["r"][1] == "(turn cancelled by you)", "soft-cancel returns sentinel")
    check(s.alive(), "process STAYS ALIVE after soft interrupt (not tree-killed)")
    check(s.proc.pid == pid1, "same process reused after interrupt")
    r2 = s.run_turn("after", t["run_dir"])
    check(r2[1] == "echo:after", "next turn works on the interrupted-but-alive session")
    drivers.cancel("t-keep")


if __name__ == "__main__":
    test_reuse()
    test_timeout_is_bounded()
    test_cancel_clean()
    test_idle_eviction_and_resume()
    test_inflight_not_evicted()
    test_live_opts_change_no_respawn()
    test_tool_grant_forces_respawn()
    test_structured_error_and_nightshift()
    test_cancel_interrupt_keeps_alive()
    print("OK" if not _fails else "FAILED: %d" % len(_fails))
    sys.exit(1 if _fails else 0)
