# -*- coding: utf-8 -*-
"""GET /sessions/claude must stay cheap (measured 2026-10-18: 31 request threads re-reading 2,983 transcripts
starved the daemon's GIL and the Henry chat's /chat/history hung for 90 s+).

  1. a transcript with no user message is NOT read to its end (hard line/byte bound);
  2. a second scan opens no unchanged file (per-file cache on mtime+size); a changed file is re-read once;
  3. ten concurrent callers cause ONE scan, not ten.

Throw-away ~/.claude/projects tree; the real one is never read.
Run: py -3.12 ops/tests/test_claude_sessions_scan_cost.py
"""
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.agent import claude_sessions as cs                 # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    root = tempfile.mkdtemp(prefix="hd-cs-")
    cs.PROJECTS = root
    proj = os.path.join(root, "C--work-proj")
    os.makedirs(proj)
    for i in range(30):
        with open(os.path.join(proj, "s%02d.jsonl" % i), "w", encoding="utf-8") as f:
            f.write(json.dumps({"cwd": "C:/work/proj"}) + "\n")
            f.write(json.dumps({"message": {"role": "user", "content": "task %d" % i}}) + "\n")
            f.write(("x" * 300 + "\n") * 5)
    # a big transcript with NO user message: the old _peek read all of it
    big = os.path.join(proj, "big.jsonl")
    with open(big, "w", encoding="utf-8") as f:
        f.write(json.dumps({"cwd": "C:/work/proj"}) + "\n")
        for _ in range(20000):
            f.write(json.dumps({"type": "tool", "data": "y" * 200}) + "\n")

    lines = [0]
    real_open = open

    class Counting:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.fh.close()

        def __iter__(self):
            for line in self.fh:
                lines[0] += 1
                yield line
    cs.open = lambda p, *a, **k: Counting(real_open(p, *a, **k))
    cs._peek(big)
    check(lines[0] <= cs.PEEK_MAX_LINES + 1, "a transcript without a user message stops at the bound (%d of 20001 lines read)" % lines[0])

    peeks = [0]
    real_peek = cs._peek

    def counting(p):
        peeks[0] += 1
        return real_peek(p)
    cs._peek = counting
    cs._peek_cache.clear()
    cs._last_scan.update(at=0, out=None)
    a = cs.list_sessions()
    first = peeks[0]
    check(first == 31 and len(a) == 31, "first scan peeks every transcript once (%d)" % first)
    cs._last_scan["at"] = 0
    b = cs.list_sessions()
    check(peeks[0] == first and [x["id"] for x in a] == [x["id"] for x in b], "a second scan opens NO unchanged file")
    time.sleep(0.05)
    with open(os.path.join(proj, "s05.jsonl"), "a", encoding="utf-8") as f:
        f.write("\n" + "z" * 10 + "\n")
    cs._last_scan["at"] = 0
    cs.list_sessions()
    check(peeks[0] == first + 1, "a changed transcript is re-read exactly once (%d)" % (peeks[0] - first))

    cs._last_scan["at"] = 0
    scans = [0]
    real_list = cs._list_sessions

    def counting_list(limit):
        scans[0] += 1
        time.sleep(0.3)                  # a slow scan, so the callers really overlap
        return real_list(limit)
    cs._list_sessions = counting_list
    ts = [threading.Thread(target=cs.list_sessions) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check(scans[0] == 1, "ten concurrent callers share ONE scan (%d)" % scans[0])
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("claude sessions scan cost: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
