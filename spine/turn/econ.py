# -*- coding: utf-8 -*-
"""Card turn economics — extracted from sessions.py. Folds one model call's
spend/tokens/context into the track dict + the event log (the card's counterpart
of copilot_stats._fold_stats), and emits the typed turn-lifecycle feed record.
Operates on the caller's track dict (no store write of its own), so it stays out
of the mutation-lock discipline. Not monkeypatched; sessions.py re-imports the
names so every caller is unchanged. The one sessions dependency (_CTX_WINDOW) is
referenced lazily to avoid an import cycle.
"""
import time


def _record_econ(t, meta):
    """Fold ONE model call's spend into the card + the event log.

    Split out of _record_turn because not every model call is a card turn: the
    question-repair call (_repair_question) is real spend on the owner's account
    and the 'measured economics' law admits no unbilled calls - but it is not a
    turn of the conversation, so it must not move the failure signal or drop a
    rewind checkpoint."""
    from spine.storage import events
    from cells.engineer import sessions
    u = meta.get("usage") or {}
    cost = events.price_turn(meta.get("models"), u, meta.get("cost_usd"))
    t["ai_cost"] = round(t.get("ai_cost", 0.0) + cost, 6)
    t["tokens_in"] = t.get("tokens_in", 0) + u.get("input_tokens", 0) \
        + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    t["tokens_out"] = t.get("tokens_out", 0) + u.get("output_tokens", 0)
    # CONTEXT METER (Paseo-parity: contextWindowUsedTokens). tokens_in above is
    # CUMULATIVE across turns - useless for "how full is the window". And the
    # result event's `usage` SUMS every API call of the turn - a long multi-call
    # turn read as millions of "context" tokens (the 6634k/100% meter) and
    # falsely tripped auto-compact. The truthful source is the LAST assistant
    # call's own usage (meta.ctx_usage, captured by the driver, Paseo-style):
    # its input side = the context size at that moment. No fallback to the
    # summed value - a missing reading means NO update, never a wrong one.
    cu = meta.get("ctx_usage") or {}
    ctx = (cu.get("input_tokens", 0) + cu.get("cache_creation_input_tokens", 0)
           + cu.get("cache_read_input_tokens", 0))
    if ctx:
        t["ctx_tokens"] = ctx
    for m in meta.get("models") or []:
        if m not in t.setdefault("models", []):
            t["models"].append(m)
    # CONTEXT WINDOW - derived from the runtime's own evidence, never assumed.
    # The meter divided by a hardcoded 200k, so a card on a 1M model showed
    # "97% - Kontext fast voll" at a real ~23% (the Tester card carried a
    # 230k call through fine while the banner cried overflow). Two witnesses,
    # both from the CLI itself: the model id carries the window (the "[1m]"
    # suffix in modelUsage), and any SUCCESSFUL call's context proves a lower
    # bound (a window cannot be smaller than what it just held).
    win = 1_000_000 if any("[1m]" in m for m in (t.get("models") or [])) else sessions._CTX_WINDOW
    # A call that PROVED more context than the standard window is itself window
    # evidence: no 200k window could have held it, so the session runs on the 1M
    # tier even when the model id lacks the "[1m]" suffix. Without this the old
    # max(win, ctx) lower-bound pinned the meter at exactly 100% forever (478k
    # of "478k") while the CLI - which knows its real window - sat at ~48% and
    # correctly refused to compact: a red meter nothing would ever clear.
    if (t.get("ctx_tokens") or 0) > sessions._CTX_WINDOW:
        win = 1_000_000
    t["ctx_window"] = max(win, t.get("ctx_window") or 0, t.get("ctx_tokens") or 0)
    events.emit("turn", t["id"], cost=round(cost, 6), usage=u, models=meta.get("models") or [])
    return cost


def _record_turn(t, meta, cp_commit=None):
    """Fold one turn's economics into the track and the event log. Runs INSIDE
    _mutate; the rewind checkpoint (a git subprocess) is computed by the caller
    BEFORE the lock and handed in as `cp_commit`. Returns the turn's cost."""
    # structured failure signal off the driver's result event (not the prose
    # reply) - the night shift reads this instead of grepping last_reply.
    t["last_subtype"] = meta.get("subtype")
    t["last_error"] = meta.get("error") or ""
    cost = _record_econ(t, meta)
    if cp_commit:
        t.setdefault("checkpoints", []).append(
            {"turn": t.get("turns"), "commit": cp_commit,
             "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "reply": (t.get("last_reply") or "")[:80]})
    return cost


def _log_turn_end(log, meta, cost=None):
    """Typed turn-lifecycle record for the card feed (Phase 3.2). failed <=>
    error != null, a Stop is canceled, everything else completed + usage."""
    u = meta.get("usage") or {}
    usage = {k: u.get(k, 0) for k in ("input_tokens", "output_tokens",
                                      "cache_creation_input_tokens",
                                      "cache_read_input_tokens")} if u else {}
    try:
        if meta.get("canceled"):
            log.log("turn", "Turn abgebrochen", event="canceled")
        elif meta.get("error") or meta.get("is_error"):
            log.log("turn", "Turn fehlgeschlagen", event="failed",
                    error=(meta.get("error") or meta.get("subtype") or "error")[:500],
                    usage=usage, cost=cost)
        else:
            log.log("turn", "Turn abgeschlossen", event="completed",
                    usage=usage, cost=cost)
    except Exception:
        pass                     # the feed record must never fail the turn
