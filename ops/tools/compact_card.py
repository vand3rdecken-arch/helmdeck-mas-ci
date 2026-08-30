# -*- coding: utf-8 -*-
"""Compact ONE card's session, by hand, from outside the daemon.

Why this exists. Compaction is normally automatic (sessions._maybe_compact at
the 80% brim) and, since the 2026-08-30 fix, re-queued by the reconciler when
it gets cut. But there is one case neither covers: a card whose session is
ALREADY over the brim in a daemon that latched _autocompact_supported=False
before the fix shipped. That flag is process state - only a restart clears it -
so the card would sit at 92% until the next deploy. This is the lever for that,
and for any "just compact this card now" the owner wants.

    py -3.12 ops/tools/compact_card.py <card-id-or-fragment>
    py -3.12 ops/tools/compact_card.py <fragment> --dry
    py -3.12 ops/tools/compact_card.py <fragment> --idle 900

--idle overrides how long the compaction may be SILENT before the driver's
watchdog kills it. Measured 2026-08-30: a 183k session emits nothing on the
stream for over three minutes while it is genuinely working, so the default is
generous (sessions._COMPACT_IDLE_S) - raise it further only if you watch the
session .jsonl still growing when it gets killed.

Safe to run against a LIVE daemon as long as the card has no turn in flight -
which is checked below and refused, because two `--resume` processes on one
session id is exactly the race the single-flight registry exists to prevent.
The daemon's own registry lives in its process, not ours, so the check here is
the card's persisted status plus a scan for a live worker on this session id.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from spine.storage.trackstore import _load                       # noqa: E402
from spine.ops.actionlog import ActionLog                        # noqa: E402
from cells.engineer import sessions                              # noqa: E402


def _pick(frag):
    hits = [t for t in _load() if frag in t["id"] or frag in (t.get("task") or "")]
    if not hits:
        sys.exit("no card matches %r" % frag)
    if len(hits) > 1:
        sys.exit("ambiguous - %d cards match:\n  %s"
                 % (len(hits), "\n  ".join(h["id"] for h in hits)))
    return hits[0]


def _live_worker_on(session_id):
    """Any claude process anywhere on this box already resuming that session?
    The daemon holds its worker registry in its OWN memory, so process evidence
    is the only cross-process signal available - and it is the one that
    actually matters (two resumes on one session id is the real hazard)."""
    try:
        import subprocess
        out = subprocess.run(
            ["wmic", "process", "where", "name='claude.exe'", "get", "commandline"],
            capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return False
    return session_id in (out or "")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    frag = sys.argv[1]
    dry = "--dry" in sys.argv
    idle = None
    if "--idle" in sys.argv:
        idle = int(sys.argv[sys.argv.index("--idle") + 1])
    t = _pick(frag)
    window = max(t.get("ctx_window") or 0, sessions._CTX_WINDOW)
    ctx = t.get("ctx_tokens", 0)
    print("card    : %s" % t["id"])
    print("session : %s" % t.get("session_id"))
    print("context : %d / %d  (%d%%)" % (ctx, window, round(ctx / window * 100)))
    print("status  : %s / lane %s" % (t.get("status"), t.get("lane")))
    if not t.get("session_id"):
        sys.exit("card has no session to compact")
    if t.get("status") == "running":
        sys.exit("a turn is in flight (status=running) - refuse, would race the session")
    if _live_worker_on(t["session_id"]):
        sys.exit("a live claude worker is already on this session id - refuse")
    if dry:
        return
    log = ActionLog(t["run_dir"])
    log.log("note", "Manuelle Verdichtung angestossen (ops/tools/compact_card.py).")
    out = sessions._maybe_compact(t, log, force=True, idle_timeout=idle)
    after = (out or t).get("ctx_tokens", ctx)
    print("--> context now: %d  (%d%%)  chain=%s"
          % (after, round(after / window * 100), (out or t).get("session_chain")))
    print("--> shrank" if after <= ctx * 0.75 else "--> NO shrink - see the card's log")


if __name__ == "__main__":
    main()
