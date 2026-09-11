# -*- coding: utf-8 -*-
"""sessions._maybe_compact - a compaction that gets CUT must teach nothing.

Regression for the 2026-08-30 incident (card 20260830-065545, actions.jsonl):
the harness started an auto-compaction at 92% context; 93s later the owner sent
a normal message; steer()'s interrupt-and-replace (a36d962) cancelled the
maintenance turn ("AbortError: Compaction canceled."); _maybe_compact then read
an UNCHANGED context and concluded "this CLI doesn't honor /compact", latching
the PROCESS-GLOBAL _autocompact_supported to False. Result: the 92% session was
never compacted again, and auto-compaction was dead for every other card too.

Pinned here:
  - an interrupted compaction leaves _autocompact_supported alone and RE-QUEUES
    (compact_pending) - it is not evidence about the CLI
  - a CLEAN turn that doesn't shrink still learns False (the original probe
    survives) and clears the re-queue
  - a real shrink learns True, clears the re-queue, chains a rotated session id
  - single flight: a second compaction on the same card never spawns a second
    /compact turn against the same session
  - await_compaction waits for the in-flight one instead of cancelling it

Also regression for card 20260910-134430 (token-burn-hardening Karte D,
2026-09-11): compact_pending re-queued for the 92%-interrupt reason above then
EVAPORATED on its own, with no compaction ever attempted - a later turn's
ctx_window re-derivation (the "[1m]"/proof-beyond-200k evidence in
spine/turn/econ.py, which can only grow the window) pushed ctx under the
freshly-recomputed 0.8x mark, and _maybe_compact's routine per-turn early
return cleared the flag right there - no idle gate, no re-read of the live
figure, same turn that caused the reclassification. That decision now belongs
to ONE owner, lifecycle.sweep_pending_compaction (idle-gated, re-reads the
live figure before dropping the flag) - _maybe_compact's early return leaves
compact_pending untouched.

And for the 2026-09-05 CI-watch livelock (steer()'s owner-vs-background-task
compaction wait): the owner-specific short 25s cut is gone. Paseo's
steerActiveTurn is simply unavailable while compacting - every steerer now
waits out the compaction's own idle patience (await_compaction's default),
and only a genuinely wedged compaction yields and re-queues.
"""
import inspect, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from cells.engineer.cards import sessions as S           # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


class _Log:
    def __init__(self):
        self.notes = []

    def log(self, kind, detail, **kw):
        self.notes.append("%s:%s" % (kind, detail))

    def saw(self, frag):
        return any(frag in n for n in self.notes)


CARD = {}


def _track(ctx=183450, sid="sess-old"):
    t = {"id": "t1", "run_dir": ".", "ctx_tokens": ctx, "ctx_window": 200000,
         "session_id": sid}
    CARD.clear()
    CARD.update(t)
    return dict(t)


def _fake_mutate(tid, fn):
    """Stands in for trackstore._mutate: apply fn to the one card and hand back
    a fresh copy, exactly like the real one does under its lock."""
    fn(CARD)
    return dict(CARD)


S._mutate = _fake_mutate
# The transcript-evidence probe: tests drive it explicitly (see MARKS below),
# so no test ever depends on a real ~/.claude/projects file being present.
MARKS = [0]
S._compact_marks = lambda sid: MARKS[0]
S._record_econ = lambda tt, meta: tt.update(meta.get("_ctx") and
                                            {"ctx_tokens": meta["_ctx"]} or {})

spawned = []


def _turn_returning(sid, out, new_ctx=None, delay=0.0):
    def _t(t, prompt, **kw):
        spawned.append(prompt)
        if delay:
            time.sleep(delay)
        return sid, out, {"_ctx": new_ctx} if new_ctx is not None else {}
    return _t


# 1) INTERRUPTED: the driver's clean cancel sentinel, context unchanged --------
S._autocompact_supported = None
S._turn = _turn_returning("sess-old", "(turn cancelled by you)")
t = _track()
lg = _Log()
del spawned[:]
S._maybe_compact(t, lg)
check(S._autocompact_supported is None,
      "interrupted compaction learns NOTHING (_autocompact_supported stays unprobed)")
check(CARD.get("compact_pending") is True, "interrupted compaction re-queues (compact_pending)")
check(lg.saw("unterbrochen"), "the card log says it was interrupted, not unsupported")
check(not lg.saw("honoriert /compact nicht"), "no false 'CLI doesn't honor /compact' verdict")
check(S.compacting("t1") is None, "registry released after the turn")

# 1b) the CLI's own wording for the same event --------------------------------
S._autocompact_supported = None
S._turn = _turn_returning("sess-old", "AbortError: Compaction canceled.")
t = _track()
S._maybe_compact(t, _Log())
check(S._autocompact_supported is None, "'AbortError: Compaction canceled.' also teaches nothing")

# 2) CLEAN but no shrink: the original self-verifying probe still works --------
S._autocompact_supported = None
S._turn = _turn_returning("sess-old", "done, nothing to compact", new_ctx=183450)
t = _track()
lg = _Log()
S._maybe_compact(t, lg)
check(S._autocompact_supported is False, "a CLEAN non-shrinking turn still learns False")
check(not CARD.get("compact_pending"), "learned-unsupported clears the re-queue (no retry loop)")
check(lg.saw("honoriert /compact nicht"), "unsupported verdict is still reported")

# 3) a learned False is bypassed by an explicit owner /compact (force) --------
del spawned[:]
S._turn = _turn_returning("sess-new", "compacted", new_ctx=40000)
t = _track()
S._maybe_compact(t, _Log())
check(not spawned, "learned-unsupported: auto path does NOT spawn a turn")
t = _track()
lg = _Log()
out = S._maybe_compact(t, lg, force=True)
check(len(spawned) == 1, "owner-forced /compact runs anyway")
check(S._autocompact_supported is True, "a real shrink re-learns True")
check(CARD.get("ctx_tokens") == 40000, "context figure updated from the turn")
check(CARD.get("session_chain") == ["sess-old"], "rotated session id is CHAINED, not dropped")
check(CARD.get("session_id") == "sess-new", "card points at the compacted tip")
check(not CARD.get("compact_pending"), "successful compaction clears the re-queue")

# 4) SINGLE FLIGHT + await: a second run never starts, a waiter waits ---------
S._autocompact_supported = None
S._turn = _turn_returning("sess-old", "compacted", new_ctx=40000, delay=1.2)
t = _track()
del spawned[:]
first = threading.Thread(target=lambda: S._maybe_compact(dict(t), _Log()))
first.start()
time.sleep(0.3)
check(S.compacting("t1") is not None, "registry shows the compaction in flight")
lg = _Log()
second = S._maybe_compact(dict(t), lg)
check(second is None and len(spawned) == 1,
      "a second compaction on the same card does NOT spawn a rival /compact turn")
check(lg.saw("laeuft bereits"), "the second caller is told one is already running")
waiter = _Log()
t0 = time.time()
cut = S.await_compaction("t1", waiter, timeout=10)
check(cut is False, "await_compaction waits for a healthy compaction instead of cutting it")
check(time.time() - t0 > 0.2, "the waiter actually blocked until the compaction finished")
check(waiter.saw("Verdichtung laeuft"), "the owner is told why his message starts a moment later")
first.join(10)
check(S.compacting("t1") is None, "registry clean afterwards")

# 5) a wedged compaction still yields to the owner, and re-queues -------------
S._autocompact_supported = None
S._turn = _turn_returning("sess-old", "(turn cancelled by you)", delay=1.5)
t = _track()
th = threading.Thread(target=lambda: S._maybe_compact(dict(t), _Log()))
th.start()
time.sleep(0.3)
cut = S.await_compaction("t1", _Log(), timeout=0.2)
check(cut is True, "a compaction past its bound is cut so the owner's message goes first")
th.join(10)
check(CARD.get("compact_pending") is True, "the cut compaction is re-queued for the next idle")
check(S._autocompact_supported is None, "and STILL teaches nothing about the CLI")


# 6) the compact TURN ITSELF dies (stalled past the watchdog, driver crash) ---
# Measured 2026-08-30: the 183k session's /compact emitted nothing for >180s
# while genuinely working, so the watchdog killed it and _turn RAISED. Before
# this that escaped through steer's blanket except with only a log line - the
# card kept its full context and nothing ever retried.
S._autocompact_supported = None


def _turn_raises(t, prompt, **kw):
    spawned.append(kw.get("idle_timeout"))
    raise RuntimeError("claude turn stalled (no output for 180s) - session killed")


S._turn = _turn_raises
t = _track()
lg = _Log()
del spawned[:]
out = S._maybe_compact(t, lg)
check(out is None, "a died compaction returns None instead of exploding upward")
check(CARD.get("compact_pending") is True, "a died compaction RE-QUEUES for the next idle")
check(S._autocompact_supported is None, "a died compaction teaches nothing about the CLI")
check(S.compacting("t1") is None, "registry released even when the turn raised")
check(spawned and spawned[0] == S._COMPACT_IDLE_S,
      "the compact turn gets the generous SILENCE bound (%ds), not the old 180s"
      % S._COMPACT_IDLE_S)
check(S._COMPACT_IDLE_S > 180,
      "the bound that killed the 183k compaction mid-work is gone")

# 6b) THE STALL THAT ALREADY SUCCEEDED ---------------------------------------
# Measured 2026-08-30 on the same 183k session: `/compact` wrote its summary
# into the transcript and the CLI process then never exited. The turn died on
# the watchdog, so the harness called it "nothing happened" - twice - about a
# compaction that had already landed. The transcript is the evidence, the exit
# code is only the transport.
S._autocompact_supported = None
S._turn = _turn_raises
t = _track()
lg = _Log()
MARKS[0] = 0


def _turn_raises_after_writing(t_, prompt, **kw):
    MARKS[0] += 1                      # the CLI wrote the summary...
    raise RuntimeError("claude turn stalled (no output for 900s) - session killed")


S._turn = _turn_raises_after_writing
S._maybe_compact(t, lg)
check(S._autocompact_supported is True,
      "a stalled turn that DID write a compaction counts as a success, not a failure")
check(not CARD.get("compact_pending"),
      "a compaction proven by the transcript is NOT re-queued (no pointless retry)")
check(lg.saw("im Transkript"), "the card log says the compaction landed despite the hang")

# 6c) completed turn, meter unmoved, but the transcript shows a compaction ----
S._autocompact_supported = None
MARKS[0] = 0


def _turn_clean_but_writes(t_, prompt, **kw):
    MARKS[0] += 1
    return "sess-old", "compacted", {"_ctx": 183450}      # meter did not move


S._turn = _turn_clean_but_writes
t = _track()
lg = _Log()
S._maybe_compact(t, lg)
check(S._autocompact_supported is True,
      "a stale ctx reading no longer produces a false 'CLI doesn't honor /compact'")
check(lg.saw("Kontext-Meter"), "the log explains the meter lags until the next turn")

# 6d) ...but a turn that compacted NOTHING still learns False -----------------
S._autocompact_supported = None
MARKS[0] = 0
S._turn = _turn_returning("sess-old", "I don't know that command", new_ctx=183450)
t = _track()
S._maybe_compact(t, _Log())
check(S._autocompact_supported is False,
      "no shrink AND no transcript summary still learns 'unsupported' (probe intact)")
MARKS[0] = 0

# 7) an explicit idle override reaches the driver (ops/tools/compact_card.py) --
del spawned[:]
S._turn = _turn_raises            # records the idle_timeout it was handed
t = _track()
S._maybe_compact(t, _Log(), force=True, idle_timeout=900)
check(spawned and spawned[0] == 900, "--idle override is threaded down to the turn")

# 8) compact_pending SURVIVES a ctx_window re-derivation -----------------------
# Regression for card 20260910-134430: a retry queued by an earlier interrupt
# must not evaporate just because a LATER turn's ctx_window re-derivation (the
# "[1m]"/proof-beyond-200k evidence, spine/turn/econ.py - a window can only
# grow) makes the ctx/window ratio look fine again. "Is this retry still
# needed" belongs to ONE owner, lifecycle.sweep_pending_compaction (idle-gated,
# re-reads the live figure) - _maybe_compact's routine per-turn early return
# must leave the flag alone.
S._autocompact_supported = None
del spawned[:]
t = _track(ctx=604_000, sid="sess-old")
t["ctx_window"] = 1_000_000                 # just reclassified to the 1M tier
CARD["compact_pending"] = True              # owed retry from an earlier interrupt
lg = _Log()
out = S._maybe_compact(t, lg)
check(out is None, "well below the (new, bigger) 80% mark: no /compact spawned")
check(not spawned, "no /compact turn ran")
check(CARD.get("compact_pending") is True,
      "the owed retry SURVIVES the reclassification - not this call's decision")

# a plain 'nothing owed' turn still costs nothing in the same branch
CARD.pop("compact_pending", None)
t = _track(ctx=604_000, sid="sess-old")
t["ctx_window"] = 1_000_000
out = S._maybe_compact(t, _Log())
check(out is None and not CARD.get("compact_pending"),
      "no pending flag to begin with - the early return is still a no-op")

# 9) STEER NO LONGER GETS A SHORT-CUT: every waiter gets the full idle bound --
# Regression for the 2026-09-05 CI-watch livelock fix's inverse: a background
# continuation got the full _COMPACT_IDLE_S patience, but genuine owner input
# still only got 25s (_COMPACT_WAIT_S) - so a real /compact (which routinely
# takes minutes) was cut and re-queued on ordinary owner traffic too. Paseo's
# steerActiveTurn is simply unavailable while compacting, no owner-specific
# short-circuit - so the source-based split and the short bound are gone, and
# await_compaction's own default is the SAME generous patience for everyone.
check(not hasattr(S, "_COMPACT_WAIT_S"), "the owner-specific short wait is gone")
check(not hasattr(S, "_COMPACT_DEFER_SOURCES"),
      "the source-based defer split is gone - one bound for every steerer")
default_timeout = inspect.signature(S.await_compaction).parameters["timeout"].default
check(default_timeout == S._COMPACT_IDLE_S,
      "await_compaction defaults to the compaction's own full idle patience")

S._autocompact_supported = None
S._turn = _turn_returning("sess-old", "compacted", new_ctx=40000, delay=1.2)
t = _track()
del spawned[:]
th = threading.Thread(target=lambda: S._maybe_compact(dict(t), _Log()))
th.start()
time.sleep(0.3)
waiter = _Log()
t0 = time.time()
cut = S.await_compaction("t1", waiter)      # DEFAULT timeout - no source special-case anymore
check(cut is False,
      "the default wait outlasts an ordinary compaction, same as a background waiter used to")
check(time.time() - t0 > 0.2, "the waiter actually blocked until the compaction finished")
th.join(10)

print(("\nFAILED: %d" % len(_fails)) if _fails else "\nall compaction-interrupt checks pass")
sys.exit(1 if _fails else 0)
