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
    # preset repos: filing a ticket never needs a path typed. default_repo is
    # the fallback; plane.repos maps a Plane project name -> repo path.
    "default_repo": "",
    "plane": {"base": "http://localhost:8090", "api_token": "", "workspace": "",
              "repos": {}, "default_repo": "", "poll_secs": 20},
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
                  "panels": ["capacity", "gates", "work"]},
    # POLICY - the flexible half of the harness/loop split. Everything here is
    # workspace configuration the owner may change (incl. via the copilot):
    # how work flows. The FIXED half (auth, audit, gate-before-review, measured
    # economics, worktree isolation, chain ordering, driver commands) is code,
    # deliberately not configurable from chat.
    "policy": {
        "lane_labels": {"backlog": "Backlog", "working": "Working",
                        "review": "Review", "done": "Done"},
        # which step modes the chain starts without a human
        "auto_dispatch_modes": ["do", "prepare"],
        # green gate on a chain step -> accept automatically (full autonomy);
        # False = a human always accepts (control). Per-workspace choice.
        "auto_accept_green": False,
        # backlog cards at/above this priority dispatch themselves when
        # capacity has headroom ("" = never)
        "auto_dispatch_priority": "",
    },
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

def save_settings(patch):
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
    return s

def emit(kind, track, **fields):
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "track": track}
    row.update(fields)
    with open(EV, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row

def read_events():
    if not os.path.exists(EV):
        return []
    out = []
    with open(EV, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out

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
    tariff = s["capacity"]["tariff"]
    today = time.strftime("%Y-%m-%d")
    by_track = {}
    for e in ev:
        by_track.setdefault(e.get("track"), []).append(e)

    cards = []
    for t in tracks:
        te = by_track.get(t["id"], [])
        touches = sum(tariff.get(e.get("touch"), 1) for e in te if e["kind"] == "touch")
        ai = t.get("ai_cost", 0.0)
        value = t.get("value") or s["value_per_card"]
        mode = _completion_mode(te, t.get("turns")) if t.get("lane") == "done" else None
        cards.append({"id": t["id"], "task": t["task"][:60], "branch": t["branch"],
                      "lane": t.get("lane"), "ai_cost": round(ai, 4), "touches": touches,
                      "value": value, "mode": mode, "models": t.get("models", []),
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
    touches_today = sum(tariff.get(e.get("touch"), 1) for e in ev
                        if e["kind"] == "touch" and e["ts"][:10] == today)
    actors = {}
    for e in ev:
        if e["kind"] == "touch" and e["ts"][:10] == today:
            a = e.get("actor") or "owner"
            actors[a] = actors.get(a, 0) + tariff.get(e.get("touch"), 1)
    wip = sum(1 for c in cards if c["lane"] == "working")
    value_done = sum(c["value"] for c in done)
    ai_all = sum(c["ai_cost"] for c in cards)
    touch_all = sum(c["touches"] for c in cards) or 1
    return {
        "settings": s,
        "cards": cards,
        "capacity": {"wip": wip, "wip_limit": s["capacity"]["wip_limit"],
                     "touches_today": touches_today, "actors": actors,
                     "touch_budget_day": s["capacity"]["touch_budget_day"],
                     "headroom": max(0, s["capacity"]["wip_limit"] - wip)},
        "yield_first_pass": (sum(1 for ok in gated.values() if ok), len(gated)),
        "automation": (sum(1 for c in done if c["mode"] == "auto"), len(done)),
        "gate_failures": sorted(fails.items(), key=lambda kv: -kv[1]),
        "totals": {"value_delivered": round(value_done, 2),
                   "ai_spend": round(ai_all, 4),
                   "margin": round(value_done - ai_all, 2),
                   "leverage_per_touch": round(value_done / touch_all, 2)},
    }
