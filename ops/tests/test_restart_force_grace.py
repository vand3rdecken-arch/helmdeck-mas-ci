# -*- coding: utf-8 -*-
"""`restart_daemon.py --force` must reach the NEW daemon's takeover grace.

2026-09-25 13:30, owner: "Jetzt neustarten". --force skipped the tool's own
wait, but the spawned daemon still waited up to HELMDECK_RESTART_GRACE
(600 s) for the live card turn before evicting the swamped old daemon; the
tool gave up after 90 s ("did not come back healthy") and the phone stayed
dead. The fix hands HELMDECK_RESTART_GRACE=0 to the new daemon on --force.

Popen is intercepted - no daemon is started, nothing is killed (the lesson
of the test that fired the real restart, 2a3a7675).

    py -3.12 ops/tests/test_restart_force_grace.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
import restart_daemon as rd

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Spawned(Exception):
    pass


def spawn_env(argv):
    seen = {}

    def fake_popen(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        raise Spawned()

    real = (rd.subprocess.Popen, rd.busy, rd.background, sys.argv)
    rd.subprocess.Popen = fake_popen
    rd.busy = lambda: ([], [])              # quiet, so the non-force path reaches the spawn too
    rd.background = lambda: {}
    sys.argv = ["restart_daemon.py"] + argv
    try:
        rd.main()
    except Spawned:
        pass
    finally:
        rd.subprocess.Popen, rd.busy, rd.background, sys.argv = real
    return seen


def main():
    forced = spawn_env(["--force"])
    env = forced.get("env") or {}
    check("--takeover" in (forced.get("cmd") or []), "the restart spawns a --takeover daemon")
    check(env.get("HELMDECK_RESTART_GRACE") == "0",
          "--force hands HELMDECK_RESTART_GRACE=0 to the new daemon (got %r)" % env.get("HELMDECK_RESTART_GRACE"))
    normal = spawn_env([])
    nenv = normal.get("env")
    check(nenv is None or nenv.get("HELMDECK_RESTART_GRACE") == os.environ.get("HELMDECK_RESTART_GRACE"),
          "a normal restart keeps the grace (live turns are waited for)")
    print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
