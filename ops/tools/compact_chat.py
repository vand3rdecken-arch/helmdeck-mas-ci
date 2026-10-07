# -*- coding: utf-8 -*-
"""Compact Henry's CHAT session, by hand, from outside the daemon - the board
counterpart of compact_card.py, and for the same one reason.

Compaction is normally automatic (copilot._schedule_compact past the cost line).
The case neither that nor the fix covers is a session ALREADY over the line in a
RUNNING daemon that is still on old code or has an unproven attempt on record:
that state lives in the daemon's process, so the session would keep re-reading
its full context on every turn until the next restart. Measured 2026-10-07 on
the owner's board session: 953,876 of 1,000,000, ~1.4M input tokens per chat
turn, ~85% of the day's whole spend. This is the lever for that, and for any
"just compact my chat now".

    py -3.12 ops/tools/compact_chat.py <user>
    py -3.12 ops/tools/compact_chat.py <user> --dry

Safe against a LIVE daemon only in a LULL, which is why both of these are
checked and refused: a chat turn in flight (daemon/state/chat_turns.json, the
same witness restart_daemon.py waits on), and any claude process still resuming
this session id - two `--resume` processes on one session is the fork hazard
_maybe_compact's own comment describes. The daemon's WARM port is such a
process, and it is reaped first (copilot.reap_chat_ports, the on-disk witness):
nothing is lost but its warmth, the next chat turn respawns on the compacted
tip, exactly as after a crashed port.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cells.copilot.chat import copilot                              # noqa: E402
from cells.engineer.cards import sessions                           # noqa: E402


def _chat_turn_running():
    try:
        with open(os.path.join(ROOT, "daemon", "state", "chat_turns.json"),
                  encoding="utf-8") as f:
            return list((json.load(f) or {}).keys())
    except (OSError, ValueError):
        return []


def _live_worker_on(session_id):
    """Any claude process on this box still resuming that session id? Same
    cross-process evidence compact_card.py uses, for the same hazard."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
             "ForEach-Object { $_.CommandLine }"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception:                                    # noqa: BLE001
        return False
    return session_id in (out or "")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    user = sys.argv[1]
    st = copilot._stats().get(user) or {}
    skey = copilot._skey(user)
    sid = copilot._sessions().get(skey)
    ctx = st.get("ctx_tokens") or 0
    window = max(st.get("ctx_window") or 0, sessions._CTX_WINDOW)
    mark, why = copilot._compact_mark(st)
    print("user    : %s" % user)
    print("session : %s" % sid)
    print("context : %d / %d  (%d%%)   turns=%s  compacted_at_turn=%s"
          % (ctx, window, round(ctx / window * 100) if window else 0,
             st.get("turns"), st.get("compacted_at_turn")))
    print("mark    : %d (%s)%s" % (mark, why, "" if ctx >= mark else "  - BELOW the line"))
    if not sid:
        sys.exit("no chat session to compact")
    busy = _chat_turn_running()
    if busy:
        sys.exit("a chat turn is in flight (%s) - refuse, would race the session"
                 % ", ".join(busy))
    if sys.argv[2:] and "--dry" in sys.argv:
        return
    killed = copilot.reap_chat_ports()
    print("--> warm chat ports reaped: %d (the next turn respawns with --resume)" % killed)
    if _live_worker_on(sid):
        sys.exit("a claude process is STILL on this session id - refuse")
    marks0 = sessions._compact_marks(sid)
    note = copilot._maybe_compact(user)
    marks1 = sessions._compact_marks(copilot._sessions().get(skey) or sid)
    after = (copilot._stats().get(user) or {}).get("ctx_tokens") or 0
    print("--> compaction summaries in the transcript: %d -> %d" % (marks0, marks1))
    print("--> note: %s" % (note or "(none - nothing was proven)"))
    print("--> context now: %d  (%d%%)" % (after, round(after / window * 100) if window else 0))
    print("--> session now: %s" % copilot._sessions().get(skey))
    if note is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
