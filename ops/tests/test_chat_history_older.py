# -*- coding: utf-8 -*-
"""The Henry chat's history beyond the 80-entry live window (owner 2026-10-18: "Henry chat auf Desktop ist
begrenzt kann nicht nach oben scrollen").

  1. db.chat_range pages backwards: the newest `limit` rows below `before`, oldest first, seq attached;
  2. paging until the start reaches every row exactly once, and `more` turns false at the beginning;
  3. `after` fetches exactly a gap (the live window slid forward while older pages were loaded);
  4. other accounts' rows never appear;
  5. the route answers through the real HTTP server shape (handler + GET table), 403 for a restricted user.

Sandboxed db, no daemon.  Run: py -3.12 ops/tests/test_chat_history_older.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.storage import db                                  # noqa: E402

db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-chat-older-"), "test.db")
db.init()
from cells.copilot.chat import copilot                        # noqa: E402
from cells.copilot.routes import routes_copilot               # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    for i in range(200):
        db.chat_append("owner", [{"role": "user", "kind": "text", "text": "m%d" % i, "ts": "10:00",
                                  "date": "2026-10-%02d" % (1 + i // 20)}])
    db.chat_append("other", [{"role": "user", "kind": "text", "text": "fremd", "ts": "10:00"}])
    tail = db.chat_tail("owner", 80)
    check([e["text"] for e in tail] == ["m%d" % i for i in range(120, 200)], "the live window is the newest 80")

    page = db.chat_range("owner", tail[0]["seq"], limit=80)
    check([e["text"] for e in page] == ["m%d" % i for i in range(40, 120)], "one page up: the 80 before the window, oldest first")
    check(all("seq" in e for e in page), "every row carries its seq (the next cursor)")

    seen, before, pages = [], tail[0]["seq"], 0
    while True:
        h = copilot.history_older("owner", before, limit=80)
        pages += 1
        seen = [m["text"] for m in h["messages"]] + seen
        if not h["more"]:
            break
        before = h["messages"][0]["seq"]
    check(seen == ["m%d" % i for i in range(0, 120)] and pages == 2,
          "paging to the start reaches every older row exactly once and 'more' ends it (%d pages)" % pages)
    check("fremd" not in seen, "another account's row never appears")

    gap = db.chat_range("owner", tail[10]["seq"], after=tail[4]["seq"], limit=500)
    check([e["text"] for e in gap] == ["m%d" % i for i in range(125, 130)], "`after` returns exactly the gap")

    # the route, through its handler with a fake request object
    class Req:
        def __init__(self, path):
            self.path, self.sent = path, None

        def _send(self, code, body):
            self.sent = (code, json.loads(body))
    check("/chat/history/older" in routes_copilot.GET_ROUTES, "the route is registered for GET")
    r = Req("/chat/history/older?before=%d&limit=5" % tail[0]["seq"])
    routes_copilot.chat_history_older_get(r, {"name": "owner", "role": "owner"})
    check(r.sent[0] == 200 and [m["text"] for m in r.sent[1]["messages"]] == ["m%d" % i for i in range(115, 120)]
          and r.sent[1]["more"] is True, "GET returns the page and more=true")
    r = Req("/chat/history/older?before=x")
    routes_copilot.chat_history_older_get(r, {"name": "owner", "role": "owner"})
    check(r.sent[0] == 400, "a non-numeric cursor is a 400")
    r = Req("/chat/history/older?before=10")
    routes_copilot.chat_history_older_get(r, {"name": "c", "role": "client"})
    check(r.sent[0] == 403, "a restricted account gets 403, like /chat/history")
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("chat history older: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
