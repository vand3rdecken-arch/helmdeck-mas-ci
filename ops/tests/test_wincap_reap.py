# -*- coding: utf-8 -*-
"""wincap's orphan-reaping (drivers.reap_orphans' pattern, applied to screen
recorders). Real incident (2026-08-14): a SINGLETON eviction's taskkill /T
does not reliably cascade to a grandchild ffmpeg subprocess - one recorder
outlived its daemon and recorded the desktop unsupervised for ~90 minutes,
while also holding a handle inside its card's worktree (blocked deletion
until found and killed by hand). Pinned here:
  - start() records the pid + OS-reported spawn time; stop() forgets it
  - reap_orphans() kills a recorded pid that is STILL the same process (spawn
    time matches) and clears the pidfile
  - a stale pid that no longer exists, or one the OS reports as un-matching
    (a different process reusing the number), is left alone
Self-sandboxing: a real short-lived subprocess stands in for ffmpeg (start()
itself is untestable without a real ffmpeg binary - this exercises the
pidfile bookkeeping + reap logic directly, which is where the bug was)."""
import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

from spine.media import wincap

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


wincap._PIDFILE = os.path.join(tempfile.mkdtemp(), "recorder_pids.json")


def _spawn_dummy():
    """A real, short-lived process to stand in for ffmpeg."""
    if os.name == "nt":
        return subprocess.Popen(["ping", "-n", "30", "127.0.0.1"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.Popen(["sleep", "30"])


def test_start_stop_bookkeeping():
    p = _spawn_dummy()
    from spine.agent import drivers
    with wincap._pid_lock:
        pids = wincap._read_pids()
        pids[str(p.pid)] = drivers._proc_start_epoch(p.pid)
        wincap._write_pids(pids)
    check(str(p.pid) in wincap._read_pids(), "start-equivalent recorded the pid")
    wincap.stop(p)
    check(str(p.pid) not in wincap._read_pids(), "stop() forgot the pid")
    check(p.poll() is not None, "the process actually exited")


def test_reap_kills_a_real_orphan():
    p = _spawn_dummy()
    time.sleep(0.3)   # let the OS start-time stamp settle
    from spine.agent import drivers
    with wincap._pid_lock:
        pids = wincap._read_pids()
        pids[str(p.pid)] = drivers._proc_start_epoch(p.pid)
        wincap._write_pids(pids)

    killed = wincap.reap_orphans()
    check(killed == 1, "reap_orphans killed exactly the recorded orphan (got %d)" % killed)
    time.sleep(0.5)
    check(p.poll() is not None, "the orphaned process is actually dead")
    check(wincap._read_pids() == {}, "pidfile cleared after reaping")


def test_reap_ignores_a_pid_that_moved_on():
    """A recorded pid whose OS start-time no longer matches (process exited,
    number reused by something else) must NOT be touched - pid-reuse safety."""
    fake_pid = 999999   # essentially guaranteed not to be a live process
    with wincap._pid_lock:
        wincap._write_pids({str(fake_pid): 12345.0})   # a spawn time that can't match anything real

    killed = wincap.reap_orphans()
    check(killed == 0, "a dead/mismatched pid is never counted as reaped (got %d)" % killed)


if __name__ == "__main__":
    test_start_stop_bookkeeping()
    test_reap_kills_a_real_orphan()
    test_reap_ignores_a_pid_that_moved_on()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - wincap orphan-reaping holds")
