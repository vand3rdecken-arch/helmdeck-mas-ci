# -*- coding: utf-8 -*-
"""PRESENCE - is the owner actually looking, and at WHAT? (Paseo adoption 2.1/2.2)

The rule this exists to enforce: never buzz the owner's phone about a card he
is already staring at. HelmDeck pushed on every turn end, so working on the
board meant being notified about your own work - which is how a notification
channel trains you to ignore it.

Three levels, and the distinction between the first two is the whole point:
  connected  - a socket/poll exists. Proves NOTHING; a forgotten browser tab is
               connected forever.
  present    - a client reported real USER ACTIVITY within FRESH_S. Presence is
               derived from the human, not from the transport.
  focused    - present AND the app is in the foreground AND the card it is
               showing is the card we are about to notify about.

  focused -> silent   (he is looking at it; a push would be noise)
  present -> in-app   (he is here but elsewhere; the app can surface it quietly)
  absent  -> push     (only now is a phone buzz the right instrument)

HelmDeck used to have exactly ONE push recipient by construction. Since W2d
(2026-08-28) it can have several - the phone in settings.push.fcm_token plus any
device that registered its own key in settings.push.devices (the watch). Paseo's
"pick one of N devices" problem STILL does not arise, but for a different
reason than before: this module does not pick at all. It decides WHETHER to
push; notify.recipients() then delivers to every paired device, because the
owner's wrist and his pocket are the same person and both should buzz.

Unchanged: several CLIENTS (phone, desktop, browser) can report presence, and
any one of them being focused is enough to stay silent.

State is in memory on purpose: a restarted daemon knows nothing about presence
and therefore falls back to pushing, which is the safe direction to be wrong in
(a missed push is worse than an extra one). A live client re-announces within
one heartbeat interval anyway.
"""
import threading, time

# A client heartbeats every ~15s; 3 minutes tolerates ~11 dropped beats before
# we declare it absent (the card specifies 3-min freshness).
FRESH_S = 180.0

_clients = {}          # key -> {"focused","visible","activity","device","user"}
_lock = threading.Lock()

# The Henry CHAT is a focus target like a card (2026-08-30). `focused` is only
# ever compared for equality, so a screen that is not a card needs nothing but a
# name no card id can collide with - every card id begins with its YYYYMMDD-
# filing date. Without a name for it notify.chat_reply could not ask "is he
# reading the answer right now" and fell back to "is any window open anywhere",
# which suppressed every chat push for a day (see chat_reply's header).
CHAT = "chat"

# Everything below is bounded because every field arrives from a client. The
# store is a dict keyed on client-supplied strings, so without these a buggy
# (or hostile) client that rotates its `device` on every beat would grow the
# daemon's memory without limit - and it heartbeats every 15s.
_MAX_FIELD = 200       # device / focused-card id length
_MAX_CLIENTS = 64      # far above any real fleet; prevents unbounded growth


def _clip(v, n=_MAX_FIELD):
    if v is None:
        return None
    s = str(v)
    return s[:n] if s else None


def record(user, device, focused_card=None, app_visible=True, activity_at=None):
    """One heartbeat. `key` is per user+device so a phone and a desktop are two
    independent presences, not one overwriting the other."""
    key = "%s/%s" % (_clip(user) or "?", _clip(device) or "?")
    now = time.time()
    try:
        at = float(activity_at) if activity_at is not None else now
    except (TypeError, ValueError):
        # a malformed timestamp must not 500 the heartbeat - treat it as "now"
        # and let the freshness window do its job
        at = now
    # Clamp a client clock running ahead of us: otherwise a skewed device would
    # look present forever (Paseo does the same).
    at = min(at, now)
    with _lock:
        _clients[key] = {"user": _clip(user), "device": _clip(device),
                         "focused": _clip(focused_card),
                         "visible": bool(app_visible), "activity": at}
        # drop everything long past the freshness window; it can never make a
        # notification decision again, it can only consume memory
        for k in [k for k, c in _clients.items() if now - c["activity"] > FRESH_S * 4]:
            if k != key:
                del _clients[k]
        # hard cap as the last line of defence: evict least-recently-active
        if len(_clients) > _MAX_CLIENTS:
            for k, _c in sorted(_clients.items(), key=lambda kv: kv[1]["activity"])[
                    :len(_clients) - _MAX_CLIENTS]:
                if k != key:
                    del _clients[k]
    return {"ok": True, "fresh_s": FRESH_S}


def _live(now=None):
    now = now or time.time()
    with _lock:
        return [c for c in _clients.values() if now - c["activity"] <= FRESH_S]


def plan(card_id, now=None):
    """What to do about an event on `card_id`: "silent" | "inapp" | "push"."""
    # A backgrounded client is not a place the owner can SEE an in-app cue -
    # only clients with the app actually visible can absorb "inapp" or
    # "silent". Without this filter, a client backgrounded up to FRESH_S ago
    # still counted as "live" and downgraded a push to "inapp", which then
    # showed nowhere: not on the phone (no push sent) and not in-app (nothing
    # open to show it). Measured 2026-08-24: a card kept asking questions
    # overnight and none of them buzzed the phone.
    live = [c for c in _live(now) if c["visible"]]
    if not live:
        return "push"
    if card_id and any(c["focused"] == card_id for c in live):
        return "silent"
    return "inapp"


def snapshot(now=None):
    """Debug/diagnostic view - who does the daemon think is here."""
    now = now or time.time()
    return {"fresh_s": FRESH_S,
            "clients": [{"user": c["user"], "device": c["device"],
                         "focused": c["focused"], "visible": c["visible"],
                         "idle_s": round(now - c["activity"], 1)}
                        for c in _live(now)]}


def clear():
    """Test hook."""
    with _lock:
        _clients.clear()
