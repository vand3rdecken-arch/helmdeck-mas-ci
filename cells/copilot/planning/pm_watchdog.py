# -*- coding: utf-8 -*-
"""PM per-card budget watchdog - extracted from pm.py (god-file breakup, see
spine/registry/debt.py daemon-god-files).

PMBOK cost control in code, deliberately NOT LLM-judged (a judge call per
tick would itself be spend, and a budget overrun needs no judgement, only
arithmetic). The 843/226M-token card ran three DAYS with the owner actively
steering and not one ping: every existing guard is either presence-gated
(_board_idle) or watches the WEEK (pm.py's _triangle_watch Budget corner) -
nothing watched ONE card's burn.

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
from spine.registry import i18n as _i18n
from cells.copilot.planning.pm_state import _save_loopstate
from spine.comms.notice import label as _label
from cells.copilot.planning.pm_comm import _activity, _ask_owner, _to_henry

_WATCH_PRIO = {"urgent": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5}

# The owner's move when a card is over budget. Three buttons, because those are
# genuinely the only three things he can do about it - the old prose ended in
# "Stoppen, steuern oder bewusst weiterlaufen lassen?" and then gave him
# nothing to tap, which is exactly the complaint (owner decree 2026-08-30).
_OVER_BUDGET_OPTIONS = [
    {"label": "Stoppen", "description": "Karte anhalten und zurück in die Ablage"},
    {"label": "Weiterlaufen", "description": "Budget bewusst erhöhen, Karte läuft weiter"},
    {"label": "Zeig mir die Karte", "description": "Erst ansehen, dann entscheiden"},
]


def _watch_budget_ctx():
    """How this board's REAL budget is denominated, for the watchdog (PMBOK:
    a cost baseline needs a funding source before variances mean anything):
      ("pct", calib) - Max plan with a warm calibration: the honest unit is %
                       of the weekly quota (cost basis when calibrated, else
                       tokens - see events.plan_calibration).
      ("eur", None)  - API plan with a monthly cap: real money.
      ("none", None) - no plan size known and no live usage reachable either
                       (offline, no Claude login): genuinely nothing honest to
                       show - never a shadow-$ standing in for it (owner
                       decree 2026-09-04, "echte Kosten oder gar nicht oder
                       Anteil" - a Max-plan card that showed "$770 API-
                       Gegenwert" read as a real invoice, label or not).

    plan_calibration() reads events.usage.cached() - a non-blocking, possibly
    STALE snapshot, deliberately cheap for hot request paths (events.metrics()
    polls it every few seconds). _cost_watch runs on the PM's own background
    tick (every 120s, its own thread), not a request path, so it can afford
    the one thing cached() can't: a bounded fresh fetch (15s timeout) when the
    cache is cold, rather than falling back to a fake currency. Measured
    2026-09-04: a cold-cache read returned None while a live fetch, taken
    seconds later, returned real calibration (49% weekly, tokens_per_pct
    ~36.2M) - the SAME real data, just not yet cached in this process."""
    from spine.storage import events
    from spine.ops import usage
    from cells.copilot.planning.pm import _pm
    plan, _src = events.plan_effective()
    if plan == "api" and (_pm().get("monthly_eur") or 0) > 0:
        return "eur", None
    try:
        calib = events.plan_calibration()
    except Exception:
        calib = None
    if plan != "api" and calib and (calib.get("cost_per_pct") or calib.get("tokens_per_pct")):
        return "pct", calib
    if plan != "api":
        try:
            fresh = usage.snapshot()          # bounded fetch, not the cold cached()
        except Exception:
            fresh = None
        if fresh and fresh.get("status") == "ok":
            try:
                calib = events.plan_calibration()   # re-read: usage.cached() is warm now
            except Exception:
                calib = None
            if calib and (calib.get("cost_per_pct") or calib.get("tokens_per_pct")):
                return "pct", calib
    return "none", None


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
    (pm.py's _triangle_watch Budget corner) - nothing watched ONE card's burn.

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
    from cells.copilot.planning.pm import _pm
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
        # The OWNER-facing name is not the same string as the log-facing one.
        # `task` is a raw 60-char slice - fine for the activity feed, wrong in a
        # question: the first live ask read „UX-FIX (Owner-Beschwerde
        # 2026-08-30): Die automatischen PM-M“, cut mid-word. notice.label is
        # the KURZNAME rule the card mirror has used all along.
        name = _label(t.get("task") or "", fallback=tid)
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
        else:
            # NO calibration reachable at all (offline, no Claude login) and
            # not an API plan either: TOKENS are the one honest absolute left
            # - real, measured, never dressed as a currency (owner decree
            # 2026-09-04, "echte Kosten oder gar nicht oder Anteil" - a
            # shadow-"$770 API-Gegenwert" on a Max-plan card read as a real
            # invoice, the "never labeled as spend" comment notwithstanding).
            spent = float(d_tok)
            budget = (float(pm.get("watch_floor_tokens") or 0) or 2_000_000.0) * _WATCH_PRIO.get(prio, 1.0)
        mult = float(w.get("mult") or 1.0)
        if budget > 0 and spent >= budget * mult:
            # jump PAST the current spend, so one huge turn fires ONE rung -
            # not a backlog of pings on the following ticks
            while budget * mult <= spent:
                mult *= 2.0
            w["mult"] = mult; changed = True
            nxt = budget * mult
            # ONE line + three buttons for the owner. The arithmetic behind the
            # rung (allocation, priority weight, how many cards crowd the window,
            # the reserve, the next threshold) is dropped from the OWNER-facing
            # line deliberately: it never changed what he could DO about it, and
            # it is the "zu viel info" of the 2026-08-30 decree. It is not lost -
            # the activity line right above keeps every number for the dashboard,
            # and the card carries its own live cost.
            if kind == "pct":
                _activity("blocked", "Budget ueberschritten (%.1f%% von %.1f%% Woche, "
                          "Prio %s, %d Karte(n) im Fenster, %.0f%% Reserve, naechste "
                          "Meldung ~%.1f%%): %s"
                          % (spent, budget, prio, len(working), reserve, nxt, task), card=tid)
                over = "~%.1f%% vom Wochenkontingent statt der zugeteilten ~%.1f%%" % (spent, budget)
            elif kind == "eur":
                _activity("blocked", "Budget ueberschritten (EUR %.2f von %.2f, %.1f%% vom "
                          "Monats-Cap, Prio %s, naechste Meldung ~%.2f): %s"
                          % (spent, budget, bac_pct, prio, nxt, task), card=tid)
                over = "~€%.2f statt der zugeteilten ~€%.2f" % (spent, budget)
            else:
                _activity("blocked", "Ungewoehnlich viel Kontext verbraucht (%.1fM Tokens, "
                          "keine Kalibrierung erreichbar, naechste Meldung ~%.1fM): %s"
                          % (spent / 1e6, nxt / 1e6, task), card=tid)
                over = "~%.1f Mio. Tokens (keine %%- oder €-Umrechnung moeglich)" % (spent / 1e6)
            # 💸 only where money is the actual unit - a token count wearing a
            # money-bag emoji is the exact misleading-currency bug under fix.
            icon = "📊" if kind == "none" else "💸"
            _ask_owner("%s „%s“ hat %s verbraucht. Weiterlaufen lassen?" % (icon, name, over),
                       _OVER_BUDGET_OPTIONS, header="Über Budget", card=tid,
                       title=_i18n.t("push.pmCost"))
        hot = ctx >= ctx_floor
        if hot and not w.get("ctx_hot"):
            w["ctx_hot"] = True; changed = True
            # TO HENRY, NOT to the owner (owner decree 2026-08-30, quoting this
            # exact message). It always WAS a work order for Henry - its own text
            # said "Karte kompaktieren, aufteilen oder abschliessen", and none of
            # those three is something the owner does while all three are things
            # Henry has hands for. He was being handed a token count and a chore
            # list he had no button for.
            _to_henry("context-bloat", card=tid,
                      detail=("Karte „%s“ schleppt ~%dk Tokens Kontext (Schwelle %dk) - jeder "
                              "weitere Turn zahlt das fast volle Fenster. Kompaktieren, "
                              "aufteilen oder abschliessen; den Owner nur wecken, wenn keine "
                              "dieser drei sicher moeglich ist."
                              % (task, ctx // 1000, ctx_floor // 1000)),
                      feed="Kontext-Drift: ~%dk Tokens Fenster - an Henry: %s"
                           % (ctx // 1000, task))
        elif not hot and w.get("ctx_hot"):
            w["ctx_hot"] = False; changed = True     # compacted back under - re-armed
    if changed:
        _save_loopstate(st)
