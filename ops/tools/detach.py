# -*- coding: utf-8 -*-
"""Run a long job DETACHED and let the harness wake the card when it ends.

    py -3.12 ops/tools/detach.py <log> [--title T] -- <cmd...>

The job survives the worker and a daemon restart, writes stdout+stderr to <log>,
and is registered as a background task of the calling card (HELMDECK_CARD): the
daemon's background sweep watches pid+creation time, marks it completed/failed
when it is gone, and auto-continues the card with the log tail. No waiter, no
marker file, no monitor. Registration is a spool file the daemon ingests (one
owner mutates tracks - a second process must not write the card)."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.ops import procwatch  # noqa: E402

DETACHED = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS|NEW_PROCESS_GROUP|NO_WINDOW


def spool_dir():
    d = os.environ.get("HELMDECK_DETACH_DIR")
    if not d:
        from daemon.paths import DATA_ROOT
        d = os.path.join(DATA_ROOT, "state", "detached")
    os.makedirs(d, exist_ok=True)
    return d


def _run(exitfile, log, cmd):
    """The detached wrapper: run the job, record its exit code."""
    with open(log, "ab") as f:
        code = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    with open(exitfile, "w") as f:
        f.write(str(code))


def main(argv):
    if argv and argv[0] == "--run":
        return _run(argv[1], argv[2], argv[4:])
    if "--" not in argv or not argv or argv.index("--") < 1:
        print(__doc__)
        return 2
    i = argv.index("--")
    head, cmd = argv[:i], argv[i + 1:]
    log = os.path.abspath(head[0])
    title = head[head.index("--title") + 1] if "--title" in head else " ".join(cmd)[:80]
    os.makedirs(os.path.dirname(log), exist_ok=True)
    tag = "%s-%d" % (os.environ.get("HELMDECK_CARD", "manual"), os.getpid())
    exitfile = os.path.join(spool_dir(), tag + ".exit")
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--run", exitfile, log, "--"] + cmd,
                         creationflags=DETACHED, close_fds=True, cwd=os.getcwd(),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ct = procwatch.create_time(p.pid)
    rec = {"tid": os.environ.get("HELMDECK_CARD"), "pid": p.pid, "ctime": ct,
           "log": log, "title": title, "exit": exitfile}
    tmp = os.path.join(spool_dir(), tag + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, os.path.join(spool_dir(), tag + ".json"))
    print("detached pid %d, log %s%s" % (p.pid, log, "" if rec["tid"] else " (no HELMDECK_CARD: not watched)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
