# -*- coding: utf-8 -*-
"""Pins for the "voller Umbau" rebuild (card chat-henry-kontext-pruning,
2026-09-15): the board snapshot, PM plan digest, memory digest and
"what happened since my last reply" block used to ride EVERY board turn
unconditionally (Paseo parity gap - real Paseo source, packages/server/
.../claude/agent.ts, sends only `content.push({type:"text", text: prompt})`).
They are now pull-only, fetched by Henry himself via board_state.py /
henry_inbox.py / henry_memory_get.py, never auto-injected.

What is pinned here is the part a passing gate can't see on its own: that
_inbox_since() (the ONE remaining owner of the removed inline block) still
produces the EXACT text/ordering/filtering the old inline code did, and that
chat()'s turn text genuinely stopped carrying board/plan/memory/chat-since
for a BOARD chat while a CARD chat (unaffected by this rebuild) keeps its
own context block.

Self-sandboxing: temp db, no daemon, no network, no model call - inspects
the ASSEMBLED TURN TEXT copilot.chat() would send, not a live spawn.

Run: py -3.12 ops/tests/test_inbox_since.py
"""
import inspect
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-inbox-")
from spine.storage import db                                      # noqa: E402
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events                                  # noqa: E402
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot                             # noqa: E402

OWNER = "tien"
fails = []


def ok(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        fails.append(what)


print("_inbox_since")
ok(copilot._inbox_since(OWNER) == "", "no chat history at all -> empty, not an exception")

db.chat_append(OWNER, [
    {"cls": "you", "text": "frage 1"},
    {"cls": "bot", "text": "antwort 1"},
    {"cls": "pm", "text": "Broker: Play-Console-Review durch"},
    {"cls": "card", "text": "Karte fertig", "card": "abc12345", "cardName": "abc12345 UI-Fix"},
    {"cls": "act", "text": "Karte angelegt: xyz"},
    {"cls": "error", "text": "direct_task: kein git repo"},
    {"cls": "you", "text": "frage 2 - noch unbeantwortet"},
])
out = copilot._inbox_since(OWNER)
lines = out.split("\n")
ok(len(lines) == 4, "exactly the 4 non-bot/non-you entries after the last bot row (got %d)" % len(lines))
ok(lines[0] == "System/Broker: Broker: Play-Console-Review durch", "pm -> 'System/Broker', text verbatim")
ok(lines[1] == "Karte abc12345 UI-Fix: Karte fertig", "card -> 'Karte <cardName>', falls back to id only if no name")
ok(lines[2] == "Aktion: Karte angelegt: xyz", "act -> 'Aktion'")
ok(lines[3] == "Fehler: direct_task: kein git repo", "error -> 'Fehler'")
ok("frage 2" not in out, "the owner's own un-answered message is not itself an inbox entry")

db.chat_append(OWNER, [{"cls": "bot", "text": "antwort 2"}])
ok(copilot._inbox_since(OWNER) == "", "after Henry answers, the SAME entries are not repeated next call")

many = [{"cls": "pm", "text": "Broker Report Nr %d" % i} for i in range(12)]
db.chat_append(OWNER, many)
out2 = copilot._inbox_since(OWNER, limit=3)
ok(out2.count("\n") == 2 and out2.endswith("Nr 11"), "limit=3 keeps only the LAST 3, most recent last (%r)" % out2[-40:])

print("\nchat() turn assembly - board vs card")
src = inspect.getsource(copilot.chat)
ok("chat_since =" not in src and "+ chat_since" not in src,
   "chat() no longer builds or assembles a chat_since variable (a comment MAY still name the old block historically)")
ok("_mem_due" not in src and "_mem_marker" not in src, "the memory-digest push variables are gone")
ok('snapshot_block = ""' in src, "the board branch sets snapshot_block to the empty string outright")
ok("_pm_plan_digest()" not in src, "the board turn no longer calls the PM-plan digest directly")
ok('turn = (action_report + snapshot_block + focus' in src,
   "the turn assembly line dropped chat_since (still has action_report/snapshot_block/focus for the card path)")

import re
m = re.search(r'if card:\n(.*?)\n    else:\n(.*?)\n    # DELTA', src, re.S)
ok(bool(m), "the card-vs-board branch that sets snapshot_block/_snap_body is still shaped as an if/else")
if m:
    card_branch, board_branch = m.group(1), m.group(2)
    ok("_card_context(card)" in card_branch, "CARD chats still build their own context block (out of scope for this rebuild)")
    ok("_snapshot()" not in board_branch and "_pm_plan_digest" not in board_branch,
       "the BOARD branch calls neither _snapshot() nor _pm_plan_digest() anymore")

print("\nno second implementation")
ok("from cells.copilot.chat.copilot import _inbox_since" in
   open(os.path.join(ROOT, "ops", "tools", "henry_inbox.py"), encoding="utf-8").read(),
   "henry_inbox.py pulls the SAME _inbox_since chat() used to call inline")
ok("_pm_plan_digest" in open(os.path.join(ROOT, "ops", "tools", "board_state.py"), encoding="utf-8").read(),
   "board_state.py --plan pulls the SAME _pm_plan_digest chat() used to call inline")

print("\n" + ("FAIL (%d)" % len(fails) if fails else "inbox-since: all pinned - PASS"))
sys.exit(1 if fails else 0)
