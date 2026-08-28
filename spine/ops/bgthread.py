# -*- coding: utf-8 -*-
"""ONE owner for "what happens when a fire-and-forget card-action thread
crashes" - factored out of spine/http/server.py's `_bg` (the original
choke point) so the same reporting reaches the OTHER bare `threading.Thread(
daemon=True).start()` call sites that never had it (cells/copilot/
henry_broker.py's "move" execution, cells/copilot/copilot_actions.py's
"steer" action). Before this, an uncaught exception in any of them printed
one stderr line to daemon.out.log and then simply vanished - no card note,
no escalation, nobody told (measured 2026-08-28: a TypeError in
_admit_heavy killed a move_lane thread mid-accept, twice, silently). A
crashed background action is a FACT the engineer/copilot cells report,
never judge here - Henry decides what (if anything) to do about it, same
discipline as aborted-by-restart/conflict-unresolved/deploy-red."""
import threading
import traceback

# name convention: "track:<verb>:<tid>" (steer/answer/dispatch/gate/move) -
# lets a crash be attributed to the right card without every call site
# having to thread a track object through just for this.
def _card_from_name(name):
    parts = (name or "").split(":", 2)
    return parts[2] if len(parts) == 3 and parts[0] == "track" else None


def _report_crash(name, exc):
    tb = traceback.format_exc()
    print("bg job '%s' crashed: %s" % (name, exc))
    try:
        from spine.registry import escalations
        escalations.emit("thread-died", card=_card_from_name(name),
                         detail="Hintergrund-Job '%s' ist mit einer Exception gestorben "
                                "(die Karte wurde dabei womoeglich nicht fertig bearbeitet):"
                                "\n%s" % (name, tb[-1200:]))
    except Exception:
        pass          # a broken reporter must never mask the original crash


def spawn(name, fn):
    """Fire-and-forget `fn` on a daemon thread, but never SILENTLY - any
    exception is printed (unchanged behaviour) AND reported as a
    'thread-died' escalation Henry can see. `name` follows the
    "track:<verb>:<tid>" convention so the escalation carries the card id."""
    def wrap():
        try:
            fn()
        except Exception as e:
            _report_crash(name, e)
    t = threading.Thread(target=wrap, daemon=True)
    t.start()
    return t
