# -*- coding: utf-8 -*-
"""PM per-card budget watchdog - extracted from pm.py (god-file breakup, see
daemon/spine/registry/debt.py daemon-god-files).

PMBOK cost control in code, deliberately NOT LLM-judged (a judge call per
tick would itself be spend, and a budget overrun needs no judgement, only
arithmetic). The 843/226M-token card ran three DAYS with the owner actively
steering and not one ping: every existing guard is either presence-gated
(_board_idle) or watches the WEEK (_usage_checkin) - nothing watched ONE
card's burn.

Owner-decreed units: thresholds are ABSOLUTE shares of the REAL budget,
never shadow-euros (on a Max plan € is a foreign currency - ai_billing), and
priority earns budget - low gets less than high. Escalation = PMBOK control
thresholds, not a ping per tick: first at 1x BAC (Budget At Completion),
re-armed at 2x, 4x, ... Runs on EVERY tick, NOT behind the acting
(_in_window/_board_idle) gates - the failure mode is burn WHILE the owner is
around.

pm._pm() is imported LAZILY (inside _cost_watch) - pm.py imports THIS module
at module level to re-export these names unchanged for existing callers, so
a top-level import back would cycle."""
from daemon.spine.registry import i18n as _i18n
from daemon.cells.pm.pm_state import _save_loopstate
from daemon.cells.pm.pm_comm import _activity, _escalate

_WATCH_PRIO = {"urgent": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5}


def _watch_budget_ctx():
    """How this board's REAL budget is denominated, for the watchdog (PMBOK:
    a cost baseline needs a funding source before variances mean anything):
      ("pct", calib) - Max plan with a warm calibration: the honest unit is %
                       of the weekly quota (cost basis when calibrated, else
                       tokens - see events.plan_calibration).
      ("eur", None)  - API plan with a monthly cap: real money.
      ("usd", None)  - no plan size known (cold calibration, capless API):
                       the measured API-equivalent $ - degraded but never
                       silent, and never labeled as spend (ai_billing)."""
    from daemon.spine.storage import events
    from daemon.cells.pm.pm import _pm
    plan, _src = events.plan_effective()
    if plan == "api" and (_pm().get("monthly_eur") or 0) > 0:
        return "eur", None
    try:
        calib = events.plan_calibration()
    except Exception:
        calib = None
    if plan != "api" and calib and (calib.get("cost_per_pct") or calib.get("tokens_per_pct")):
        return "pct", calib
    return "usd", None


def _watch_bac_pct(base_pct, reserve, prio, weight_sum):
    """One card's Budget At Completion, as an ABSOLUTE % of the plan budget:
    base% x its priority weight (low earns less budget than high), capped by
    its fair share of the allocatable pool - (100% - reserve) split over the
    working set's weights - so allocations SHRINK when more work draws on the
    same window. The reserve is PMBOK's management reserve: the slice never
    allocated to cards (the owner's own interactive use + risk)."""
    w = _WATCH_PRIO.get(prio, 1.0)
    pool = max(0.0, 100.0 - reserve)
    crowd = pool * w / weight_sum if weight_sum > 0 else pool * w
    return max(0.0, min(base_pct * w, crowd))


def _cost_watch(st, tracks):
    """PER-CARD BUDGET WATCHDOG - PMBOK cost control in code, deliberately NOT
    LLM-judged (a judge call per tick would itself be spend, and a budget
    overrun needs no judgement, only arithmetic). The 843/226M-token card ran
    three DAYS with the owner actively steering and not one ping: every
    existing guard is either presence-gated (_board_idle) or watches the WEEK
    (_usage_checkin) - nothing watched ONE card's burn.

    Owner-decreed units: thresholds are ABSOLUTE shares of the REAL budget,
    never shadow-euros (on a Max plan € is a foreign currency - ai_billing),
    and priority earns budget - low gets less than high. So each working card
    gets a Budget At Completion (_watch_bac_pct): watch_base_pct x priority
    weight, capped by its fair share of (100% - watch_reserve_pct) split over
    the cards sharing the window. The BAC recomputes EVERY tick from live
    calibration + WIP + priority - self-adjusting by construction; only the
    SPENT baseline is snapshotted when the card enters 'working'.

    Escalation = PMBOK control thresholds, not a ping per tick: first at 1x
    BAC, re-armed at 2x, 4x, ... (spend is monotonic and can never 'come back
    under'; doubling the rung is what 'clears' this corner). The unit degrades
    honestly (_watch_budget_ctx): % of the weekly quota -> € vs the monthly
    cap -> measured API-equivalent $. ctx_tokens keeps its absolute floor -
    plan-neutral (a full window costs on every plan), clears on compaction,
    re-fires on the next crossing.

    Baselines live in loopstate (survive restarts); a card leaving 'working'
    drops its entry and re-baselines fresh on re-entry. Runs on EVERY tick,
    NOT behind the acting (_in_window/_board_idle) gates - the failure mode is
    burn WHILE the owner is around."""
    from daemon.cells.pm.pm import _pm
    pm = _pm()
    ctx_floor = int(pm.get("watch_ctx_floor") or 0) or 150_000
    base_pct = float(pm.get("watch_base_pct") or 0) or 5.0
    reserve = min(95.0, max(0.0, float(pm.get("watch_reserve_pct") or 0.0)))
    watch = st.setdefault("cost_watch", {})
    working = {t["id"]: t for t in tracks
               if t.get("lane") == "working" and not t.get("archived")}
    changed = False
    for tid in [k for k in watch if k not in working]:
        del watch[tid]; changed = True           # left 'working' -> fresh next time
    kind, calib = _watch_budget_ctx()
    weight_sum = sum(_WATCH_PRIO.get(t.get("priority"), 1.0) for t in working.values())
    for tid, t in working.items():
        cost = float(t.get("ai_cost") or 0.0)
        tok = int(t.get("tokens_in") or 0) + int(t.get("tokens_out") or 0)
        ctx = int(t.get("ctx_tokens") or 0)
        w = watch.get(tid)
        if w is None:                            # first tick in 'working' = baseline
            watch[tid] = {"cost": cost, "tok": tok, "mult": 1.0, "ctx_hot": False}
            changed = True
            continue
        task = (t.get("task") or "").replace("\n", " ")[:60]
        prio = t.get("priority") or "medium"
        bac_pct = _watch_bac_pct(base_pct, reserve, prio, weight_sum)
        d_cost = max(0.0, cost - float(w.get("cost") or 0.0))
        d_tok = max(0, tok - int(w.get("tok") or 0))
        if kind == "pct":
            cpp = (calib or {}).get("cost_per_pct")
            spent = d_cost / cpp if cpp else d_tok / float(calib["tokens_per_pct"])
            budget = bac_pct
        elif kind == "eur":
            spent = d_cost
            budget = float(pm.get("monthly_eur") or 0) * bac_pct / 100.0
        else:                                    # cold calibration: shadow-$ ladder
            spent = d_cost
            budget = (float(pm.get("watch_floor_usd") or 0) or 5.0) * _WATCH_PRIO.get(prio, 1.0)
        mult = float(w.get("mult") or 1.0)
        if budget > 0 and spent >= budget * mult:
            # jump PAST the current spend, so one huge turn fires ONE rung -
            # not a backlog of pings on the following ticks
            while budget * mult <= spent:
                mult *= 2.0
            w["mult"] = mult; changed = True
            nxt = budget * mult
            if kind == "pct":
                _activity("blocked", "Budget ueberschritten (%.1f%% von %.1f%% Woche): %s"
                          % (spent, budget, task), card=tid)
                _escalate("💸 Budget-Watchdog: „%s“ liegt über Budget: ~%.1f%% vom "
                          "Wochenkontingent verbraucht, zugeteilt ~%.1f%% (Prio %s, "
                          "%d Karte(n) im Fenster, %.0f%% Reserve). Stoppen, steuern "
                          "oder bewusst weiterlaufen lassen? Nächste Meldung bei ~%.1f%%."
                          % (task, spent, budget, prio, len(working), reserve, nxt),
                          tid=tid, title=_i18n.t("push.pmCost"))
            elif kind == "eur":
                _activity("blocked", "Budget ueberschritten (EUR %.2f von %.2f): %s"
                          % (spent, budget, task), card=tid)
                _escalate("💸 Budget-Watchdog: „%s“ liegt über Budget: ~€%.2f verbraucht, "
                          "zugeteilt ~€%.2f (%.1f%% vom Monats-Cap, Prio %s). Stoppen, "
                          "steuern oder weiterlaufen lassen? Nächste Meldung bei ~€%.2f."
                          % (task, spent, budget, bac_pct, prio, nxt),
                          tid=tid, title=_i18n.t("push.pmCost"))
            else:
                _activity("blocked", "Budget ueberschritten (USD %.2f API-Gegenwert): %s"
                          % (spent, task), card=tid)
                _escalate("💸 Kosten-Watchdog: „%s“ hat seit Arbeitsbeginn ~$%.2f "
                          "API-Gegenwert verbrannt (Kontingent-Kalibrierung noch kalt - "
                          "kein €-Spend auf dem Abo, aber Kontingent). Stoppen, steuern "
                          "oder weiterlaufen lassen? Nächste Meldung bei ~$%.2f."
                          % (task, spent, nxt),
                          tid=tid, title=_i18n.t("push.pmCost"))
        hot = ctx >= ctx_floor
        if hot and not w.get("ctx_hot"):
            w["ctx_hot"] = True; changed = True
            _activity("blocked", "Kontext-Drift: ~%dk Tokens Fenster - eskaliere: %s"
                      % (ctx // 1000, task), card=tid)
            _escalate("🧠 Kontext-Watchdog: „%s“ schleppt ~%dk Tokens Kontext (Schwelle "
                      "%dk) - jeder weitere Turn zahlt das fast volle Fenster. Karte "
                      "kompaktieren, aufteilen oder abschliessen."
                      % (task, ctx // 1000, ctx_floor // 1000),
                      tid=tid, title=_i18n.t("push.pmCtx"))
        elif not hot and w.get("ctx_hot"):
            w["ctx_hot"] = False; changed = True     # compacted back under - re-armed
    if changed:
        _save_loopstate(st)
