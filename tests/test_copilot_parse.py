# -*- coding: utf-8 -*-
"""The board copilot's reply/action contract must stay parseable while it also
STREAMS (one chat surface with the card). New format: prose reply + an optional
trailing ```actions [..]``` block; the legacy {"reply","actions"} JSON blob must
still parse (backward-compat). The live-strip must hide the action tail so only
prose streams. Load-bearing: actions drive moves/merges/machine tasks/deploys."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "daemon"))
import copilot as c

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# 1) new contract: prose + fenced actions
r, a = c._parse_reply_actions(
    'Klar, ich lege die Karte an.\n\n```actions\n[{"type":"file_card","task":"X"}]\n```')
check(r == "Klar, ich lege die Karte an." and a == [{"type": "file_card", "task": "X"}],
      "prose + ```actions -> prose reply + parsed actions")

# 2) prose only, no actions
r, a = c._parse_reply_actions("Alles gruen, nichts zu tun.")
check(r == "Alles gruen, nichts zu tun." and a == [], "prose only -> no actions")

# 3) legacy JSON blob still parses (backward-compat)
r, a = c._parse_reply_actions('{"reply":"hi","actions":[{"type":"move","card":"c1","lane":"done"}]}')
check(r == "hi" and a == [{"type": "move", "card": "c1", "lane": "done"}],
      "legacy {reply,actions} blob still parses")

# 4) malformed actions -> keep the prose, drop the actions (never crash)
r, a = c._parse_reply_actions("Mach ich.\n```actions\n[not json\n```")
check(r == "Mach ich." and a == [], "malformed actions -> prose kept, actions empty")

# 5) live-strip: hide the action tail, show only prose while streaming
check(c._strip_actions_live("Ich lege an\n```actions") == "Ich lege an", "strip hides ```actions tail")
check(c._strip_actions_live('{"reply":"hi') == "", "strip hides a leading raw-JSON blob")
check(c._strip_actions_live("Ich denke nach") == "Ich denke nach", "strip leaves plain prose")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("copilot-parse: all pinned - PASS")
