# -*- coding: utf-8 -*-
"""Board-copilot PM-session economics — extracted from copilot.py (the 1.1k line
board agent) as a cohesive module seam. The ONE owner of copilot_stats.json:
folds each finished copilot turn's cost/tokens/context at event time (the board
chat's counterpart of sessions._record_econ). Not monkeypatched by the suite; copilot.py
re-imports these names so every caller is unchanged.
"""

# The stats doc is the runtime_doc row "copilot_stats" (state-into-db phase D;
# ledger step 7 imported state/copilot_stats.json).
_STATS_KEY = "copilot_stats"


def _stats():
    from spine.storage import db
    return db.doc_get(_STATS_KEY, {}) or {}


def _save_stats(d):
    from spine.storage import db
    db.doc_put(_STATS_KEY, d)


def _fold_stats(user, result, ctx_usage):
    """Fold ONE finished copilot turn into the user's PM-session stats - the
    board chat's counterpart of sessions._record_econ, and the ONE owner of
    copilot_stats.json (folded at event time from the runtime's own result +
    assistant events, never reconstructed from the transcript). The context
    meter reads ctx_usage = the LAST assistant call's own usage: its input
    side (input+cache) is the real window fill at that moment. The result
    event's usage instead SUMS every API call of the turn (the same trap
    sessions._record_econ documents - a long multi-call turn reads as millions
    of "context" tokens), so it feeds only the cumulative counters. A missing
    ctx reading means NO update, never a wrong one."""
    from spine.turn import econ
    from cells.engineer.cards import sessions
    u = result.get("usage") or {}
    models = list((result.get("modelUsage") or {}).keys())
    st = _stats()
    m = st.setdefault(user, {})
    m["turns"] = int(m.get("turns") or 0) + 1
    # the same spend also lands in the event log, so the plan calibration
    # sees Henry's share of the account (econ.record_spend)
    m["cost"] = round(float(m.get("cost") or 0.0)
                      + econ.record_spend("chat", models, u, result.get("total_cost_usd")), 6)
    m["tokens_in"] = int(m.get("tokens_in") or 0) + u.get("input_tokens", 0) \
        + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    m["tokens_out"] = int(m.get("tokens_out") or 0) + u.get("output_tokens", 0)
    cu = ctx_usage or {}
    ctx = (cu.get("input_tokens", 0) + cu.get("cache_creation_input_tokens", 0)
           + cu.get("cache_read_input_tokens", 0))
    if ctx:
        m["ctx_tokens"] = ctx
    for md in models:
        if md not in m.setdefault("models", []):
            m["models"].append(md)
    # window from the model's own evidence - the same two witnesses the card
    # uses (sessions._record_econ): the "[1m]" id suffix names a 1M window,
    # and any successful call's context proves a lower bound.
    win = 1_000_000 if any("[1m]" in x for x in (m.get("models") or [])) else sessions._CTX_WINDOW
    # proof-beyond-200k = 1M-tier evidence (sessions._record_econ parity): a
    # call that carried more than the standard window can only have run on the
    # 1M tier; the bare lower-bound pinned the meter at a permanent red 100%.
    if int(m.get("ctx_tokens") or 0) > sessions._CTX_WINDOW:
        win = 1_000_000
    m["ctx_window"] = max(win, int(m.get("ctx_window") or 0), int(m.get("ctx_tokens") or 0))
    _save_stats(st)
    return m
