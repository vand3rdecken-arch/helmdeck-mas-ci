# -*- coding: utf-8 -*-
"""The chat transcript is an EVENT, not a thing you look at on a clock.

Owner decree 2026-08-30: "einheitlich wie Paseo mit PC und mobile. Kein polling
sondern verschluesselter transport." Before this, /stream/wait watched only
db._version, which no chat write ever moved (the transcript is a JSON file, not
a table) - so every surface fell back to a fixed interval: phone 8s
(chat.tsx refetchInterval), watch 15s (HenryScreen ticker).

What must hold, and what this replays:
  1. copilot._append_log - the single writer of the log - moves the chat cursor.
  2. A waiter blocked in db.wait_any WAKES ON THE WRITE, not on the timeout.
     This is the whole claim: measured latency, not a shorter poll.
  3. The board cursor and the chat cursor are INDEPENDENT: a chat line must not
     invalidate the board (that would be a broadcast, not a fix), and a board
     write must not be mistaken for a chat line.
  4. The bump happens AFTER the file is durable, so a woken client that reads
     immediately always sees the new line - never an empty wake.

SELF-SANDBOXING, and not as a formality: _append_log writes copilot.CHATLOG,
which in a normal process IS the owner's live transcript. This test rebinds that
module global to a temp file and asserts at the end that the real one was never
touched. The recordings-wipe incident (bb516c6) came from exactly this shape of
test reaching live data through an unsandboxed module global.

Manual replay tool, like every other file here - the gate stays LIGHT
(decree 9dcde19+d5bd7af): py -3.12 ops/tests/test_chat_stream_cursor.py
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

FAILS = []


def ok(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


def main():
    from spine.storage import db
    from cells.copilot import copilot

    # --- sandbox the ONE global that reaches live data ------------------------
    real_log = copilot.CHATLOG
    real_before = None
    if os.path.exists(real_log):
        with open(real_log, "rb") as f:
            real_before = f.read()

    tmpdir = tempfile.mkdtemp(prefix="hd-chatcursor-")
    copilot.CHATLOG = os.path.join(tmpdir, "copilot_log.json")
    try:
        # 1. the single writer publishes the cursor ---------------------------
        c0 = db.current_chat_version()
        copilot._append_log("owner", [{"cls": "bot", "text": "erste", "ts": "09:00"}])
        c1 = db.current_chat_version()
        ok(c1 == c0 + 1, "_append_log bumps the chat cursor exactly once (%d -> %d)" % (c0, c1))

        # 2. a waiter wakes ON THE WRITE, not on the timeout ------------------
        # The distinction is the entire point: a 5s timeout with a write at
        # ~0.15s proves an event woke it. A poll would have returned at 5s.
        got = {}

        def waiter():
            t0 = time.time()
            v, c = db.wait_any(db.current_version(), c1, timeout=5.0)
            got["elapsed"] = time.time() - t0
            got["c"] = c
            # Read the log the instant we wake - claim 4.
            got["seen"] = copilot._log().get("owner", [])

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.15)                      # let it actually block
        copilot._append_log("owner", [{"cls": "bot", "text": "zweite", "ts": "09:01"}])
        t.join(timeout=10)

        ok(not t.is_alive(), "the waiter returned")
        ok(got.get("elapsed", 99) < 1.5,
           "woken by the WRITE, not the timeout (%.3fs, timeout was 5s)" % got.get("elapsed", -1))
        ok(got.get("c") == c1 + 1,
           "the waiter is handed the new chat cursor (%s)" % got.get("c"))

        # 4. bump AFTER durability: the wake must never precede the content.
        texts = [e.get("text") for e in got.get("seen", [])]
        ok("zweite" in texts,
           "a client woken by the cursor reads the new line immediately (%s)" % texts)

        # 3. the two cursors are independent ---------------------------------
        v0 = db.current_version()
        c2 = db.current_chat_version()
        copilot._append_log("owner", [{"cls": "bot", "text": "dritte", "ts": "09:02"}])
        ok(db.current_version() == v0,
           "a chat line does NOT move the board cursor (no board-wide invalidate)")
        ok(db.current_chat_version() == c2 + 1, "...but does move the chat cursor")

        db.bump()
        ok(db.current_chat_version() == c2 + 1,
           "a board write does NOT move the chat cursor")
        ok(db.current_version() == v0 + 1, "...but does move the board cursor")

        # A waiter already level with both cursors must BLOCK, not spin. This is
        # the regression that would turn the stream into a hot loop.
        t0 = time.time()
        db.wait_any(db.current_version(), db.current_chat_version(), timeout=0.5)
        ok(time.time() - t0 >= 0.4,
           "a caller level with both cursors blocks instead of spinning")
    finally:
        copilot.CHATLOG = real_log

    # --- the sandbox held ----------------------------------------------------
    if real_before is None:
        ok(not os.path.exists(real_log),
           "the live transcript was never created by this test")
    else:
        with open(real_log, "rb") as f:
            ok(f.read() == real_before, "the live transcript is byte-identical after the test")

    print("")
    if FAILS:
        print("FAIL (%d)" % len(FAILS))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
