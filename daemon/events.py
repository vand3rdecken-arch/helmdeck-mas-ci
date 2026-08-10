# -*- coding: utf-8 -*-
"""The company's instrumentation. One JSONL row per business event (events.jsonl):
lane moves, gate runs, human touches, per-turn AI usage, acceptances. Settings
(settings.json) hold the business rates: capacity budget + touch tariff, model
price table, value per deliverable. The dashboard is computed from these two
files at request time, so retuning a rate re-prices all history.

The economic model (owner decision): humans are a FIXED-capacity resource
(hired anyway - no per-minute billing), AI is the variable cost. Human work is
counted in touch units against a daily budget; margin per card = value - AI cost;
the human question is utilization/headroom, not dollars."""
import json, os, time

ROOT = os.path.dirname(os.path.abspath(__file__))
EV = os.path.join(ROOT, "events.jsonl")
SET = os.path.join(ROOT, "settings.json")

DEFAULTS = {
    # capacity: what a sustainable day looks like, self-declared. Touches consume it.
    "capacity": {"wip_limit": 6, "touch_budget_day": 30,
                 "tariff": {"steer": 1, "review": 1, "bounce": 3}},
    # $ per million tokens, matched by substring of the model id; CLI-reported
    # cost wins when present - this table is the fallback pricer.
    "prices": {"claude-opus": {"in": 15.0, "out": 75.0},
               "claude-sonnet": {"in": 3.0, "out": 15.0},
               "claude-haiku": {"in": 0.8, "out": 4.0},
               "default": {"in": 3.0, "out": 15.0}},
    "value_per_card": 50.0,   # default deliverable value; per-card value overrides
    "currency": "EUR",
    # read-only bearer token for the Meta Ray-Ban Display glance webapp (glasses/).
    # empty = the /glance endpoint is OFF. Owner sets it; it does NOT grant any
    # write access or touch the session-cookie auth - a scoped read-only surface.
    "glance_token": "",
    # Un-versioned files copied into every new worktree. A worktree holds only
    # TRACKED files, so git-ignored local toolchain config (SDK paths, local
    # env) would be missing and builds that work by hand fail inside a card.
    # Signing material is intentionally NOT here - add it only if you want
    # agents to be able to sign releases.
    "worktree_seed": ["apk/local.properties", "local.properties"],
    # zero-knowledge reverse-tunnel relay (relay/relay.py + e2ee.py) so the
    # mobile app reaches this daemon over the internet without port-forwarding
    # and end-to-end encrypted. url = where the owner hosts the relay (HTTPS);
    # room = public routing id; sk = this daemon's Curve25519 secret (generated
    # at pairing); phone_pubs = pinned device keys (phone_pub = legacy mirror of
    # [0], the push target); pair_pending = the single-use pairing window opened
    # by issuing a code ({expires: ts}, see relay_client.PAIR_TTL).
    # Empty url = OFF (LAN only).
    "relay": {"url": "", "room": "", "sk": "", "phone_pub": "",
              "phone_pubs": [], "pair_pending": None},
    # preset repo: filing a ticket never needs a path typed (fallback repo).
    "default_repo": "",
    # execution drivers (drivers.py): a card picks one by name. claude-desktop =
    # Claude Code allowed to drive Windows/browser via windows-mcp, screen-recorded.
    "drivers": {"claude": {"type": "claude"},
                "claude-desktop": {"type": "claude",
                                   "allowed_tools": ["mcp__windows-mcp__*"],
                                   "record": True}},
    # self-registration on the sign-in screen: closed by default; users join
    # with the invite code (owner shares it) and get default_role. open=True
    # drops the code requirement (LAN-trusted setups only).
    "registration": {"open": False, "invite_code": "", "default_role": "client"},
    # APPEARANCE - ambient backdrop behind the glass (never carries data;
    # card/status colors stay semantic). Chat-configurable.
    "appearance": {"backdrop": "mesh"},   # mesh|aurora|ember|forest|mono
    # DASHBOARD composition - which tiles/panels the CEO view shows, in order.
    # tiles: value_delivered, ai_spend, margin, yield, automation, leverage
    # panels: capacity, gates, work
    "dashboard": {"tiles": ["value_delivered", "ai_spend", "margin",
                            "yield", "automation", "leverage"],
                  "panels": ["sows", "capacity", "gates", "work"]},
    # POLICY - the flexible half of the harness/loop split. Everything here is
    # workspace configuration the owner may change (incl. via the copilot):
    # how work flows. The FIXED half (auth, audit, gate-before-review, measured
    # economics, worktree isolation, chain ordering, driver commands) is code,
    # deliberately not configurable from chat.
    "policy": {
        # UI + owner-facing prose language: "de" | "en". ONE language, sharply -
        # the app translates every screen through app/src/i18n.ts and the daemon
        # runs its chat/push messages through i18n.t(). The append-only AUDIT
        # trail (event log, gate output, git) stays English on purpose: it is a
        # technical record, not owner prose, and must read the same in every
        # workspace. tools/i18n_lint.py enforces that nothing drifts back.
        "lang": "de",
        # EMPTY on purpose: a lane label shipped in the defaults would be
        # hardcoded in ONE language and it overrides the translation, so a
        # German workspace read "Backlog / Working / Review / Done" - exactly
        # the mix policy.lang exists to end. Empty = the app translates the
        # lane; this stays here purely as a per-workspace RENAME ("Working" ->
        # "Bei uns"), which is language-neutral by definition.
        "lane_labels": {},
        # which step modes the chain starts without a human
        "auto_dispatch_modes": ["do", "prepare"],
        # green gate on a chain step -> accept automatically (full autonomy);
        # False = a human always accepts (control). Per-workspace choice.
        "auto_accept_green": False,
        # backlog cards at/above this priority dispatch themselves when
        # capacity has headroom ("" = never)
        "auto_dispatch_priority": "",
        # which roles may RECONFIGURE the workspace from the copilot chat
        # (actions/steering stay available to owner+operator regardless)
        "chat_configure_roles": ["owner"],
    },
    # Jira Cloud data flow (Settings > Data flows). api_token = Atlassian API token.
    "jira": {"base": "", "email": "", "api_token": "", "default_jql": ""},
    # auth: every API call needs a bearer token of one of these users.
    # roles: owner (everything) / operator (work, no settings) / client
    # (file + comment + watch own cards only). Filled on first serve.
    "users": [],
}

def settings():
    s = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(SET):
        try:
            with open(SET, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    s[k] = v
        except ValueError:
            pass
    return s

# A checkpoint marks REAL development - new integrations/runtimes, structural
# policy, the target repo - not cosmetic settings tuning (backdrop, card value,
# dashboard tiles). Only a patch touching one of these earns a restore point.
# (Connector installs/rollbacks checkpoint via their own path in sessions.py.)
SIGNIFICANT_SETTINGS = {"drivers", "policy", "registration", "default_repo", "connectors"}

def save_settings(patch, actor="system", reason=""):
    significant = bool(reason) or (patch and any(k in SIGNIFICANT_SETTINGS for k in patch))
    if patch and significant:
        try:
            import checkpoints
            checkpoints.create(actor=actor,
                               reason=reason or ("changed: " + ", ".join(sorted(patch))))
        except Exception as e:
            print("checkpoint failed:", e)
    s = settings()
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    tmp = SET + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SET)
    try:
        import db
        db.bump()
    except Exception:
        pass
    return s

def emit(kind, track, **fields):
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "track": track}
    row.update(fields)
    with open(EV, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row

def read_events():
    import db
    return db.events_all()

def consecutive_gate_fails(track, ev=None):
    """How many times this track's gate has failed in a row, most recent first.
    The gate history is already append-only in events.jsonl; this reads the
    trailing run of ok=False gate events and resets on the last ok=True. It is
    real trajectory evidence (SageRoute's "repeated error class" signal): a
    single-shot `failed` flag can't tell one bounce from an agent rewriting-and-
    refailing the same gate five times while burning the budget."""
    fails = 0
    for e in sorted((e for e in (ev if ev is not None else read_events())
                     if e.get("kind") == "gate" and e.get("track") == track),
                    key=lambda x: x["ts"]):
        fails = 0 if e.get("ok") else fails + 1
    return fails

def ai_billing(s=None):
    """How the AI on this board is BILLED - the display contract, not the meter.
    settings.pm.plan (pm.py) names the Anthropic plan: "max" is the flat
    subscription - a turn burns quota, not cash, so the measured $ figure is an
    API-equivalent reference and must never render as spend. "api" (and "mixed",
    where at least some turns are per-token) bill real money per token. Every
    turn keeps being priced either way (measured-economics law); only what the
    number MEANS differs."""
    plan = ((s or settings()).get("pm") or {}).get("plan", "max")
    return "flat" if plan == "max" else "metered"

def price_turn(models, usage, cost_usd=None):
    """Dollar cost of one session turn. CLI-reported total wins; else price the
    token counts against the settings table (first matching model substring)."""
    if cost_usd is not None:
        return float(cost_usd)
    prices = settings()["prices"]
    model = (models or ["default"])[0]
    p = prices["default"]
    for key, v in prices.items():
        if key != "default" and key in model:
            p = v
            break
    ti = (usage or {}).get("input_tokens", 0) + (usage or {}).get("cache_creation_input_tokens", 0)
    to = (usage or {}).get("output_tokens", 0)
    return ti / 1e6 * p["in"] + to / 1e6 * p["out"]

# -- dashboard math ------------------------------------------------------

def time_in_work(track_events, running_now=False):
    """Real elapsed seconds the card spent in the 'working' lane - paired from
    lane-change events (to='working' ... the next lane change), not the touch-
    count tariff (that stays a separate human-capacity/utilization signal).
    This is the real "hours" a time & material project bills against."""
    from datetime import datetime
    fmt = "%Y-%m-%d %H:%M:%S"
    secs = 0.0
    start = None
    for e in sorted((e for e in track_events if e["kind"] == "lane"), key=lambda x: x["ts"]):
        ts = datetime.strptime(e["ts"], fmt)
        if e.get("to") == "working":
            start = ts
        elif start is not None:
            secs += (ts - start).total_seconds()
            start = None
    if start is not None and running_now:
        secs += (datetime.strptime(time.strftime(fmt), fmt) - start).total_seconds()
    return secs

def _completion_mode(track_events, turns):
    """auto = accepted with zero human touches beyond acceptance (one dispatch
    turn, no steers, no bounces). assisted = you steered or it bounced."""
    bounced = any(e["kind"] == "touch" and e.get("touch") == "bounce" for e in track_events)
    gate_failed = any(e["kind"] == "gate" and not e.get("ok") for e in track_events)
    steers = sum(1 for e in track_events if e["kind"] == "touch" and e.get("touch") == "steer")
    if bounced or gate_failed or steers > 0 or (turns or 0) > 1:
        return "assisted"
    return "auto"

def metrics(tracks):
    """Everything the dashboard shows, computed fresh from events + tracks."""
    s = settings()
    ev = read_events()
    # flat (Max subscription): AI cost is measured but is NOT cash, so margins
    # must not subtract it - the phantom-$ would misprice every card. metered
    # (API): the measured cost is real spend and margins carry it.
    billing_mode = ai_billing(s)
    flat = billing_mode == "flat"
    tariff = s["capacity"]["tariff"]
    today = time.strftime("%Y-%m-%d")
    by_track = {}
    for e in ev:
        by_track.setdefault(e.get("track"), []).append(e)

    cards = []
    for t in tracks:
        te = by_track.get(t["id"], [])
        touches = sum(tariff.get(e.get("touch"), 1) for e in te if e["kind"] == "touch")
        secs = time_in_work(te, running_now=t.get("lane") == "working")
        hours = secs / 3600.0
        ai = t.get("ai_cost", 0.0)
        # a value of 0 is valid (free/internal card) - don't treat it as "unset"
        value = t.get("value")
        value = s["value_per_card"] if value is None else value
        # per-card billing -> recognized revenue (`billed`). Touch units are NOT
        # billing (they measure human capacity); billing is fixed price or T&M
        # hours, or none. fixed recognizes on 'done'; tm accrues with worked time.
        billing = t.get("billing") or "fixed"
        rate = t.get("rate")
        if billing == "none":
            billed = 0.0
        elif billing == "tm":
            billed = round(hours * (rate or 0.0), 2)
        else:   # fixed
            billed = value if t.get("lane") == "done" else 0.0
        mode = _completion_mode(te, t.get("turns")) if t.get("lane") == "done" else None
        cards.append({"id": t["id"], "task": t["task"][:60], "branch": t["branch"],
                      "lane": t.get("lane"), "ai_cost": round(ai, 4), "touches": touches,
                      "time_seconds": round(secs, 1), "project_id": t.get("project_id"),
                      "value": value, "billing": billing, "rate": rate,
                      "billed": round(billed, 2),
                      "margin": round(billed - (0.0 if flat else ai), 2),
                      "mode": mode, "models": t.get("models", []),
                      "tokens_in": t.get("tokens_in", 0), "tokens_out": t.get("tokens_out", 0)})

    done = [c for c in cards if c["lane"] == "done"]
    gated = {}   # first gate outcome per track (first-pass yield)
    fails = {}   # failure reason histogram
    for e in ev:
        if e["kind"] != "gate":
            continue
        gated.setdefault(e["track"], e.get("ok", False))
        if not e.get("ok"):
            for r in e.get("problems", ["unknown"]):
                key = r.split("\n")[0][:60]
                fails[key] = fails.get(key, 0) + 1
    # AI usage by model - the quoting table: what a unit of agent work costs
    by_model = {}
    for e in ev:
        if e["kind"] != "turn":
            continue
        u = e.get("usage") or {}
        for m in (e.get("models") or ["unknown"]):
            b = by_model.setdefault(m, {"turns": 0, "cost": 0.0, "tok_in": 0, "tok_out": 0})
            b["turns"] += 1
            b["cost"] += e.get("cost") or 0.0
            b["tok_in"] += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)                 + u.get("cache_read_input_tokens", 0)
            b["tok_out"] += u.get("output_tokens", 0)
    for b in by_model.values():
        b["cost"] = round(b["cost"], 4)
        b["avg_cost_per_turn"] = round(b["cost"] / b["turns"], 4) if b["turns"] else 0
    touches_today = sum(tariff.get(e.get("touch"), 1) for e in ev
                        if e["kind"] == "touch" and e["ts"][:10] == today)
    actors = {}
    for e in ev:
        if e["kind"] == "touch" and e["ts"][:10] == today:
            a = e.get("actor") or "owner"
            actors[a] = actors.get(a, 0) + tariff.get(e.get("touch"), 1)
    archived_ids = {t["id"] for t in tracks if t.get("archived")}
    wip = sum(1 for c in cards if c["lane"] == "working" and c["id"] not in archived_ids)

    # -- SoW rollup: one process = one SoW = the billing unit ---------------
    # a PROCESS (processes.py) groups its accepted steps' cards into one client
    # engagement; the SoW's margin is the sum of its cards' per-card `billed`
    # minus their AI cost. Cards not in any process bill standalone (still in
    # `cards`). This replaces the old separate projects.py billing wrapper -
    # billing now lives on the card, the process is just the grouping.
    import processes as _processes
    track_proc, proc_meta = {}, {}
    for p in _processes.list_processes():
        proc_meta[p["id"]] = {"name": (p.get("request") or p["id"])[:70],
                              "client": p.get("client", ""), "status": p.get("status"),
                              "due": p.get("due", "")}
        for st in p.get("steps", []):
            if st.get("track"):
                track_proc[st["track"]] = p["id"]
    sow_agg = {}
    for c in cards:
        pid = track_proc.get(c["id"])
        if not pid:
            continue
        r = sow_agg.setdefault(pid, {"billed": 0.0, "ai_cost": 0.0, "hours": 0.0,
                                     "cards": 0, "done": 0})
        r["billed"] += c["billed"]; r["ai_cost"] += c["ai_cost"]
        r["hours"] += c["time_seconds"] / 3600.0; r["cards"] += 1
        r["done"] += 1 if c["lane"] == "done" else 0
    sows = []
    for pid, r in sow_agg.items():
        m = proc_meta.get(pid, {})
        sows.append({"id": pid, "name": m.get("name", pid), "client": m.get("client", ""),
                     "status": m.get("status"), "due": m.get("due", ""),
                     "cards": r["cards"], "done": r["done"], "hours": round(r["hours"], 2),
                     "billed": round(r["billed"], 2), "ai_cost": round(r["ai_cost"], 4),
                     "margin": round(r["billed"] - (0.0 if flat else r["ai_cost"]), 2),
                     "all_done": r["cards"] > 0 and r["done"] == r["cards"]})
    sows.sort(key=lambda x: -x["margin"])

    # company totals from per-card recognized revenue (billing-aware), so the
    # SoW rollup and the totals never double-count.
    value_done = sum(c["billed"] for c in cards)
    ai_all = sum(c["ai_cost"] for c in cards)
    touch_all = sum(c["touches"] for c in cards) or 1
    return {
        "settings": s,
        "ai_billing": billing_mode,
        "cards": cards,
        "sows": sows,
        "capacity": {"wip": wip, "wip_limit": s["capacity"]["wip_limit"],
                     "touches_today": touches_today, "actors": actors,
                     "touch_budget_day": s["capacity"]["touch_budget_day"],
                     "headroom": max(0, s["capacity"]["wip_limit"] - wip)},
        "yield_first_pass": (sum(1 for ok in gated.values() if ok), len(gated)),
        "automation": (sum(1 for c in done if c["mode"] == "auto"), len(done)),
        "gate_failures": sorted(fails.items(), key=lambda kv: -kv[1]),
        "ai_by_model": dict(sorted(by_model.items(), key=lambda kv: -kv[1]["cost"])),
        "totals": {"value_delivered": round(value_done, 2),
                   "ai_spend": round(ai_all, 4),
                   "margin": round(value_done - (0.0 if flat else ai_all), 2),
                   "leverage_per_touch": round(value_done / touch_all, 2)},
    }
