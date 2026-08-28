# -*- coding: utf-8 -*-
"""IDEMPOTENCY for POST /chat - one owner message runs exactly one turn.

MEASURED, not assumed (owner report 2026-08-28, transcript
b085da2d-166b-41a1-b3e0-7ae3ff527027.jsonl): three separate owner messages were
each enqueued TWICE into the persistent chat process, ~98s / ~142s / ~176s
apart, and each produced its own full turn and its own `you` + `bot` pair in
copilot_log.json:

    20:51:34 + 20:53:12  "Nein .ache direkt hier"
    07:00:57 + 07:03:19  "Nein erstmal nur privat nicht auf Google jetzt"
    07:04:52 + 07:07:48  "Warum kommen meine Nachrichten ... doppelt an"  (+ the
                         SAME attachment file both times)

Two facts pin the cause:
  * the second copy is BYTE-IDENTICAL - same text, same base64 attachment. A
    human re-typing a sentence and re-picking the same screenshot is not a
    plausible reading of that; a lower transport layer replaying an unacked
    POST is (RN/OkHttp retries a failed connection, the relay gives up on the
    daemon after REPLY_TIMEOUT=120s, the daemon's own _local() urlopen after
    115s, the LAN fetch after its own timeout).
  * the third pair's second enqueue landed 43ms after the first turn's last
    assistant message - i.e. the re-delivery had ALREADY arrived and was
    blocked on copilot._turn_lock while turn one was still running. It was
    never a decision anyone made; it was a queued replay.

Nothing between the phone and copilot.chat() carried a request identity, so the
daemon could not tell a replay from a new message and answered both.

THE RULE (evaluated at ACCEPTANCE time - routes_copilot.chat_post - before any
turn work, which is the earliest point the daemon can honestly say "I have
this"):
  * `mid` (client message id, minted per api.chat() call in
    surfaces/app/src/data/client.ts) is the PRIMARY key. A transport replay
    resends the same bytes, so it carries the same mid; a genuine second send
    is a new call and mints a new one. This is the only key that separates
    "replay" from "the owner really did say that twice".
  * NO mid (an app one OTA behind) falls back to sha256(user|card|text|
    attachment names+sizes) inside WINDOW - coarser, and it will swallow a
    deliberate repeat of the same short prompt ("Weiter?") inside 10 minutes.
    That is the trade the owner asked for explicitly, and it only applies to
    clients that cannot say who they are.
  * IN-FLIGHT identical content is a duplicate even WITH a fresh mid: while a
    turn is literally still running, a second copy of the same text to the same
    user is a replay in every case observed and none of the intended ones.

A duplicate never runs a turn and never appends a second `you` entry. It waits
(bounded) for the ORIGINAL turn's result and returns that, so the client that
replayed still gets its answer instead of an error - which is the whole reason
it replayed.

STATE IS IN MEMORY, ON PURPOSE - and registered as debt
(`chat-dedupe-window-in-memory` in spine/registry/debt.py). A daemon restart
forgets the window; the cost of that is one duplicated message across a restart
that happens to land inside 10 minutes of the original, and the alternative
(another on-disk file fsync'd on the hot chat path) buys little for it."""
import hashlib
import threading
import time

# How long a settled message stays deduplicable. The owner asked for "at least
# 10 minutes": a replay was measured up to 176s out, and the layer that decides
# to replay (relay 120s, urlopen 115s) can chain, so the window has to be an
# order of magnitude above the observed gap, not a hair above it.
WINDOW = 600

# Bounded wait a duplicate spends on the original turn before giving up and
# telling the client "duplicate, no reply here - poll the history". Sits under
# the relay's REPLY_TIMEOUT (120s) so the duplicate's own connection is never
# the thing that times out and triggers yet another replay.
WAIT = 110

_lock = threading.Lock()
_entries = []          # newest last; small by construction (one per message)


def content_key(user, text, card, attachments):
    """Identity of the MESSAGE, independent of who sent it or how often. Folds
    the attachment names+sizes in: two photos under the same caption are two
    different messages, and comparing base64 blobs here would mean hashing
    megabytes on the request thread."""
    h = hashlib.sha256()
    h.update(("%s\x00%s\x00%s" % (user or "", card or "", (text or "").strip())).encode("utf-8", "replace"))
    for a in (attachments or []):
        if not isinstance(a, dict):
            continue
        h.update(("\x00%s:%d" % (a.get("name") or "", len(a.get("data") or ""))).encode("utf-8", "replace"))
    return h.hexdigest()


def _gc(now):
    # Called under _lock. Drop settled entries past the window. An entry that is
    # still running is never dropped, however long it takes - forgetting it is
    # exactly how the second turn got started in the first place.
    keep = [e for e in _entries
            if not e["done"].is_set() or now - e["settled"] <= WINDOW]
    if len(keep) != len(_entries):
        _entries[:] = keep


def claim(user, text, card, attachments, mid=""):
    """(entry, original) - `original` is None when this message is NEW and the
    caller owns the turn (and MUST call settle() or fail() exactly once).
    Otherwise `original` is the entry this one duplicates and the caller must
    NOT run a turn."""
    now = time.time()
    key = content_key(user, text, card, attachments)
    mid = (mid or "").strip()[:200]
    with _lock:
        _gc(now)
        for e in reversed(_entries):
            if e["user"] != user:
                continue
            # PRIMARY: same client message id = the same send, replayed.
            if mid and e["mid"] == mid:
                return e, e
            if e["key"] != key:
                continue
            # Same content, turn still running: a replay in every case measured.
            if not e["done"].is_set():
                return e, e
            # Same content, already answered. Only the id-less client falls
            # back to time here; a client that minted a fresh mid is telling us
            # this is a new send and is believed.
            if not mid and now - e["settled"] <= WINDOW:
                return e, e
        entry = {"user": user, "key": key, "mid": mid, "started": now,
                 "settled": 0.0, "done": threading.Event(), "result": None}
        _entries.append(entry)
        return entry, None


def settle(entry, result):
    """The owning turn finished. Its result becomes the answer every replay of
    this message gets."""
    entry["result"] = result
    entry["settled"] = time.time()
    entry["done"].set()


def fail(entry):
    """The owning turn blew up. Forget the claim outright rather than settling
    it: the message was never answered, so a retry SHOULD be allowed to run a
    real turn instead of being handed a hole for the next 10 minutes.

    A SETTLED claim is never dropped, whatever the caller thinks went wrong.
    The route settles before it writes the HTTP response, and writing that
    response is allowed to fail - a client that gave up on a long turn has
    closed its socket, so `self._send` raises a broken pipe and lands in the
    same `except` as a failed turn. That is the one moment a replay is MOST
    likely to be on its way (the client did not get its answer, which is why it
    replays); dropping the claim there would hand it a second real turn and
    reinstate the exact bug. The turn ran, the answer exists, the claim stands."""
    if entry["done"].is_set():
        return
    with _lock:
        try:
            _entries.remove(entry)
        except ValueError:
            pass
    entry["done"].set()          # release anyone waiting on it


def await_result(entry, timeout=WAIT):
    """The original turn's reply for a duplicate to return, or None if it is
    still running when the bounded wait runs out."""
    entry["done"].wait(timeout)
    return entry["result"]


def _reset_for_tests():
    with _lock:
        _entries[:] = []
