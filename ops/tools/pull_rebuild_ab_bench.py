# -*- coding: utf-8 -*-
"""A/B for the "voller Umbau" rebuild (card chat-henry-kontext-pruning, part
3, 2026-09-15): does Henry actually PULL board/inbox state when the push is
gone, or does he silently answer stale (the exact risk registered as debt
'henry-context-pull-is-prompt-enforced')?

Real model, real brief, real turn-assembly code (_snapshot/_pm_plan_digest/
copilot_memory.digest/_inbox_since - the SAME functions chat() itself used
before the rebuild and still exports) - NOT fabricated. Two axes:

  A (OLD, pre-rebuild brief + pushed turn)  - board-copilot.md at commit
      8fc24a1b (the last commit before this rebuild), rendered fresh via
      harness.brief() the same way chat() always did, PLUS a turn built the
      old way (board snapshot + PM plan + memory digest + chat-since,
      whatever this worktree's real state actually is - if a read fails,
      that failure is reported AS PART OF the pushed text, not hidden).
  B (NEW, current brief + bare turn) - today's real chat()-shaped turn:
      just the user's question, nothing else, run with the REAL cwd
      (DAEMON_ROOT) and REAL settings so a tool call, if attempted, hits
      this worktree's REAL (imperfectly migrated) local state.

Two questions per side: one that NEEDS current board/inbox state, one that
does not (a plain arithmetic control - proves NEW isn't just tool-happy
regardless of relevance). --output-format stream-json --verbose so every
tool_use attempt is visible even if the CALL itself then errors.

The BRIEF FILE is swapped to the old content and back, tightly scoped with a
try/finally and the ORIGINAL text captured in memory FIRST - never a git
operation, never touches anything gitignored/secret (helmdeck.db, users.json
are never read or written here).

    py -3.12 ops/tools/pull_rebuild_ab_bench.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from daemon.paths import DAEMON_ROOT, REPO_ROOT       # noqa: E402
from spine.agent import drivers                      # noqa: E402
from spine.agent.agentcli import CLAUDE               # noqa: E402
from spine.agent.spawnenv import tool_path            # noqa: E402
from spine.registry import harness                    # noqa: E402
from cells.copilot.chat import copilot                # noqa: E402
from cells.copilot.chat import copilot_memory         # noqa: E402

ROOT = DAEMON_ROOT            # the real cwd every board turn runs from (NOT harness.ROOT - that's REPO_ROOT)
BRIEF_PATH = os.path.join(REPO_ROOT, "cells", "copilot", "harness", "agents", "board-copilot.md")
OLD_COMMIT = "8fc24a1b"       # last commit before this rebuild
OWNER = "tien"

STATUS_Q = "Und, ist die Karte von vorhin fertig geworden?"
CONTROL_Q = "Was ist 47 plus 55? Antworte nur mit der Zahl."


def _old_brief_text():
    r = subprocess.run(["git", "show", "%s:cells/copilot/harness/agents/board-copilot.md" % OLD_COMMIT],
                       cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError("git show failed: " + r.stderr[:300])
    return r.stdout


def _render_with(md_text):
    """harness.brief() reads the file fresh each call - swap it, render,
    restore, ALWAYS (finally), even on exception. Original bytes captured
    RAW (no text-mode newline translation) so the restore is byte-exact -
    a text-mode round-trip normalized CRLF -> LF once and left `git status`
    seeing a change that `git diff` couldn't even show (caught by this
    script's own dry run before ever touching a real spawn)."""
    with open(BRIEF_PATH, "rb") as f:
        current = f.read()
    try:
        with open(BRIEF_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write(md_text)
        return harness.brief("board-copilot")
    finally:
        with open(BRIEF_PATH, "wb") as f:
            f.write(current)


def _old_turn(question):
    """EXACTLY the pre-rebuild shape (see git diff 8fc24a1b..HEAD), built
    from the still-existing functions - never fabricated. A read that fails
    in THIS worktree's real (partially migrated) local state is reported
    honestly, inline, the way a production failure would have looked."""
    try:
        board = copilot._snapshot()
    except Exception as e:                                    # noqa: BLE001
        board = "[Fehler beim Lesen des Boards: %s]" % str(e)[:150]
    try:
        plan = copilot._pm_plan_digest()
    except Exception as e:                                    # noqa: BLE001
        plan = ""
    try:
        mem = copilot_memory.digest()
    except Exception:                                        # noqa: BLE001
        mem = ""
    try:
        since = copilot._inbox_since(OWNER)
    except Exception:                                        # noqa: BLE001
        since = ""
    import time
    snap = ("BOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M")
            + board + (("\n\n" + plan) if plan else "") + mem)
    since_block = ("\n\nCHAT-VERLAUF DIREKT VOR DIESER NACHRICHT (in Reihenfolge, so hat der "
                  "Owner es gelesen - 'es'/'das' meint meist die letzte Zeile):\n" + since) if since else ""
    return (snap + since_block
            + "\n\nUSER (%s): %s" % (OWNER, question)
            + "\n\n(Falls du gleich Tools nutzt: erst EIN kurzer Prosa-Satz an "
              "den Owner - was du siehst oder was du pruefst -, DANN der erste "
              "Tool-Call. Antwortest du ohne Tools, einfach direkt antworten.)")


def _new_turn(question):
    """EXACTLY today's chat() shape for a board turn: nothing but the
    question and the same first-word reminder."""
    return ("\n\nUSER (%s): %s" % (OWNER, question)
            + "\n\n(Falls du gleich Tools nutzt: erst EIN kurzer Prosa-Satz an "
              "den Owner - was du siehst oder was du pruefst -, DANN der erste "
              "Tool-Call. Antwortest du ohne Tools, einfach direkt antworten.)")


def _run(system_text, turn_text, label, pmode=None):
    # --append-system-prompt-file, NEVER the raw arg: the OLD brief alone is
    # ~34.8k chars, past what a Windows command line safely carries (measured
    # 2026-09-04, board-copilot.md's own history - WinError 206, invisible
    # because stderr was DEVNULL). copilot._brief_file is the ONE owner of
    # this temp-file dance; reuse it, don't re-invent it.
    brief_path = copilot._brief_file(system_text)
    argv = [CLAUDE, "-p", "--output-format", "stream-json", "--include-partial-messages",
            "--verbose", "--permission-mode", pmode or copilot.henry_pmode(),
            "--model", "haiku", "--append-system-prompt-file", brief_path]
    argv += harness.cli_args("board-copilot")
    argv += copilot._lean_mcp_args()
    # HELMDECK_WORKTREE stripped: this SCRIPT is itself running inside a
    # worker card's worktree, so it inherits that var from ITS OWN spawn
    # env - but Henry's real board-chat spawn (_persist_get -> tool_path())
    # never sets it at all. Leaving it set here would test a shape that
    # never happens in production and (found while building this bench,
    # see the debt entry) trips a real card_tool_guard.py bug: it resolves
    # a relative arg against the worktree ROOT, not the tool's actual cwd
    # (daemon/, one level down) - so board_state.py's OWN pre-approved
    # `../ops/tools/...` form gets misread as escaping whenever this var
    # happens to be set for a daemon/-cwd spawn.
    env = tool_path()
    env.pop("HELMDECK_WORKTREE", None)
    p = subprocess.run(drivers._cmd_line(argv), cwd=ROOT, input=turn_text,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=180)
    tool_calls, result_text, denials = [], "", []
    for line in p.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "assistant":
            for blk in (d.get("message") or {}).get("content") or []:
                if blk.get("type") == "tool_use":
                    tool_calls.append(str((blk.get("input") or {}).get("command", blk.get("name", "")))[:90])
        elif d.get("type") == "result":
            result_text = str(d.get("result") or "")
            denials = d.get("permission_denials") or []
    print("-- %s -- rc=%s" % (label, p.returncode))
    if p.stderr.strip():
        print("   stderr:", p.stderr.strip()[:200])
    print("   tool calls: %s" % (tool_calls or "(none)"))
    if denials:
        print("   permission denials:", [x.get("tool_name") for x in denials])
    print("   answer: %s" % result_text[:400].replace("\n", " "))
    return tool_calls, result_text


def main():
    print("== building briefs ==")
    old_system = _render_with(_old_brief_text())
    new_system = harness.brief("board-copilot")
    print("old brief: %d chars | new brief: %d chars" % (len(old_system), len(new_system)))

    print("\n== STATUS question (needs current board/inbox state) ==")
    old_tools, old_ans = _run(old_system, _old_turn(STATUS_Q), "A (old, pushed)")
    new_tools, new_ans = _run(new_system, _new_turn(STATUS_Q), "B (new, pull)")

    print("\n== CONTROL question (no board dependency) ==")
    _, _ = _run(old_system, _old_turn(CONTROL_Q), "A (old, pushed) - control")
    ctrl_tools, ctrl_ans = _run(new_system, _new_turn(CONTROL_Q), "B (new, pull) - control")

    print("\n== verdict ==")
    v = {
        "OLD made zero tool calls on the status question (it already had the answer)": len(old_tools) == 0,
        "NEW attempted a board_state.py/henry_inbox.py call on the status question": any(
            "board_state" in c or "henry_inbox" in c for c in new_tools),
        "NEW made NO tool call on the unrelated control question (not tool-happy)": len(ctrl_tools) == 0,
        "NEW's control answer is still correct (102)": "102" in ctrl_ans,
    }
    for k, ok in v.items():
        print(("  ok   " if ok else "  FAIL ") + k)
    return 0 if all(v.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
