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
import json, os, re, secrets, time

from daemon.paths import DAEMON_ROOT as ROOT
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
    # bearer token for the Meta Ray-Ban Display glance webapp (surfaces/glasses/).
    # empty = the /glance endpoint is OFF. Owner sets it; it does not touch the
    # session-cookie auth - a scoped surface, read-only on its own.
    "glance_token": "",
    # GLASS MODE: may the glasses ANSWER a worker's pending question (POST
    # /glance/answer), i.e. tap a decision the agent offered and let the card's
    # session continue? Default OFF and deliberately a SECOND switch, not a
    # property of glance_token: answering runs an agent turn, so turning it on
    # promotes one shared read-only secret into one that can move the board.
    # Even on, it can only PICK options the worker itself wrote - never free
    # text, never a card that is not currently asking.
    "glance_decide": False,
    # GLASS MODE: may the glasses TALK to the board agent (POST /glance/talk)?
    # Default OFF and a THIRD switch on purpose: unlike reading or answering,
    # every tap here spends plan quota on a real agent turn, so a leaked token
    # would burn budget. The turn is advisory - board actions are dropped, never
    # executed (copilot.chat allow_actions=False).
    "glance_talk": False,
    # The PUBLIC glance origin - the Cloudflare Worker (surfaces/glasses/worker,
    # ops/deploy/push_glance.sh) that proxies /glance* to this daemon. The phone
    # app's GlassVoiceService is a plain HttpURLConnection client OUTSIDE the
    # E2EE relay, so it needs this origin + glance_token to reach Henry
    # (surfaces/app/src/data/glasses.ts explains why the relay URL cannot serve).
    # Empty = glasses voice stays unconfigured; the app degrades, never errors.
    "glance_origin": "",
    # Un-versioned files copied into every new worktree. A worktree holds only
    # TRACKED files, so git-ignored local toolchain config (SDK paths, local
    # env) would be missing and builds that work by hand fail inside a card.
    # Signing material is intentionally NOT here - add it only if you want
    # agents to be able to sign releases.
    "worktree_seed": ["apk/local.properties", "local.properties"],
    # zero-knowledge reverse-tunnel relay (surfaces/relay/relay.py + e2ee.py) so the
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
    # POLICY - the flexible half of the ops/harness/loop split. Everything here is
    # workspace configuration the owner may change (incl. via the copilot):
    # how work flows. The FIXED half (auth, audit, gate-before-review, measured
    # economics, worktree isolation, chain ordering, driver commands) is code,
    # deliberately not configurable from chat.
    "policy": {
        # UI + owner-facing prose language: "de" | "en". ONE language, sharply -
        # the app translates every screen through surfaces/app/src/i18n.ts and the daemon
        # runs its chat/push messages through i18n.t(). The append-only AUDIT
        # trail (event log, gate output, git) stays English on purpose: it is a
        # technical record, not owner prose, and must read the same in every
        # workspace. ops/tools/i18n_lint.py enforces that nothing drifts back.
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
        # LOAD-AWARE ADMISSION (ops/docs/backlog/load-aware-admission, the desktop-lock
        # pattern generalized to CPU): a heavy op (gate run, ops/deploy/preview
        # hook - APK/Gradle build + emulator boot) admits immediately when
        # OBSERVED CPU load (spine.ops.resources, sampled on demand -
        # never a stored flag) is under cpu_max_pct; over it, the op QUEUES
        # with a visible named-holder note in the card's chat and re-samples
        # every poll_s. wait_s bounds the queue - past it the op starts ANYWAY,
        # because this is ADMISSION (defer the start of a heavy op), never
        # cgroup enforcement or a permanent refusal.
        "load_admission": {
            "enabled": True,
            "cpu_max_pct": 85,
            "wait_s": 1800,
            "poll_s": 5,
        },
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

# Any key whose NAME matches this (at any nesting depth) is masked before it
# ever reaches the audit trail - card 5 (ops/docs/backlog/rbac-gxp), same "no
# secret in the log" discipline as spine/auth/auth.py's _audit. Matched on the
# key name, not the value shape, so a not-yet-invented secret field is caught
# by naming convention rather than by remembering to list it here.
_SECRET_KEY_RE = re.compile(r"(token|password|secret|api[_-]?key|\bpw\b)", re.I)

def _masked(v, key=""):
    if isinstance(v, dict):
        return {k: _masked(vv, k) for k, vv in v.items()}
    if isinstance(v, list):
        return [_masked(x, key) for x in v]
    if v and _SECRET_KEY_RE.search(key or ""):
        return "***"
    return v

def save_settings(patch, actor="system", reason=""):
    significant = bool(reason) or (patch and any(k in SIGNIFICANT_SETTINGS for k in patch))
    if patch and significant:
        try:
            from spine.ops import checkpoints
            checkpoints.create(actor=actor,
                               reason=reason or ("changed: " + ", ".join(sorted(patch))))
        except Exception as e:
            print("checkpoint failed:", e)
    before = settings()
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
        from spine.storage import db
        db.bump()
    except Exception:
        pass
    # Audit trail (card 5): one event per write, old->new per CHANGED top-level
    # key only (unmodified keys stay silent - the diff is the point, not the
    # whole blob), secrets masked by name. Best-effort, same contract as every
    # other emit() call site - a sink hiccup must never block the save itself
    # (the file write above already happened and is the durable state).
    try:
        changed = {k: {"before": _masked(before.get(k), k), "after": _masked(s.get(k), k)}
                   for k in (patch or {}) if before.get(k) != s.get(k)}
        if changed:
            emit("settings", "-", op="save", actor=actor, changed=changed)
    except Exception:
        pass
    return s

def emit(kind, track, **fields):
    # `ts` stays host-local, on purpose: it is what every existing consumer
    # (dashboard, day-boundary rollups, quota-window math) already reads, and
    # reinterpreting it as UTC in place would silently shift every "today" /
    # "this week" boundary computed from it - a correctness change disguised
    # as a timestamp fix. `at_utc` is the unambiguous anchor added ALONGSIDE
    # it, on every event (this used to exist only on auth/signature events,
    # added by hand at each call site - now every emit() gets one, so no
    # future event kind can forget it). A caller that already computed a more
    # precise UTC value (e.g. a signature's own signed_at) can still pass its
    # own at_utc in **fields - row.update() below runs after this and wins.
    #
    # `id`: the file and the db table used to share no key at all (debt
    # events-two-stores-unreconciled), so a dropped db write-through - the
    # try/except below is best-effort by design - stayed dropped and silent
    # forever, and the file could never be safely re-scanned to heal it
    # without risking duplicates. secrets.token_hex, not a counter: this must
    # stay unique across process restarts with no shared state to coordinate
    # against, which a counter can't promise and a random token can.
    row = {"id": secrets.token_hex(12),
           "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "track": track,
           "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    row.update(fields)
    with open(EV, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    # Write-through to the query path (db.events_all, what consecutive_gate_fails
    # / consecutive_bounces / read_events actually read). db.event_insert had NO
    # callers anywhere - events.jsonl only gets into sqlite via the ONE-TIME
    # startup migration (db.init), so every event emitted after boot was
    # invisible to every consumer of read_events(). Best-effort: the jsonl
    # append above is the durable record regardless of db state.
    try:
        from spine.storage import db
        db.event_insert(row)
    except Exception:
        pass
    return row

def log(kind, msg):
    """Freeform log line, no track association (bridge/pm/merge chatter)."""
    return emit(kind, "-", msg=msg)

def read_events():
    from spine.storage import db
    return db.events_all()

def query_audit(kind=None, track=None, actor=None, since=None, until=None, q=None):
    """Every event matching these filters, oldest first (read_events()'s own
    order) - unlimited, unpaginated. The ONE filter implementation shared by
    GET /audit (routes_audit.py - JSON preview caps+tails this, CSV export
    doesn't) and Henry's `audit_query` chat action (cells/copilot/
    copilot_actions.py, card 5) - "who activated GxP" and "what changed in
    /audit last week" answer from the same filtered set, not two.

    `kind` accepts a comma-separated string (as query params arrive) or an
    iterable of kinds. All filters are optional; no filters = everything."""
    kinds = ({k for k in kind.split(",") if k} if isinstance(kind, str)
             else set(kind or ()))
    text = (q or "").lower()

    def _match(e):
        if kinds and e.get("kind") not in kinds:
            return False
        if track and e.get("track") != track:
            return False
        if actor and e.get("actor") != actor:
            return False
        at = e.get("at_utc") or ""
        if since and at < since:
            return False
        if until and at >= until:
            return False
        if text and text not in json.dumps(e, ensure_ascii=False, sort_keys=True).lower():
            return False
        return True

    return [e for e in read_events() if _match(e)]

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

def consecutive_bounces(track, ev=None):
    """How many times in a row this track has bounced with reason=daemon_restart
    (the daemon itself died mid-turn), most recent first - resets on any
    completed turn. Mirrors consecutive_gate_fails: real trajectory evidence
    instead of a single-shot flag, so a card that keeps taking the daemon down
    with it (not just failing its own turn) can be told apart from an ordinary
    one-off restart."""
    n = 0
    for e in sorted((e for e in (ev if ev is not None else read_events())
                     if e.get("track") == track
                     and (e.get("kind") == "bounce" and e.get("reason") == "daemon_restart"
                          or e.get("kind") == "turn")),
                    key=lambda x: x["ts"]):
        n = n + 1 if e.get("kind") == "bounce" else 0
    return n

def plan_effective(s=None):
    """Resolve settings.pm.plan to the plan that actually bills this board.

    "auto" (the default) DETECTS it from the CLI's real auth instead of asking
    the owner to know their own billing - the same signal Paseo's usage tab
    keys off: a stored Claude Code login whose subscriptionType names a flat
    plan (Max/Pro) burns quota; a login without one is a Console account and an
    ANTHROPIC_API_KEY is per-token - both bill real money. Explicit
    "max"/"api"/"mixed" stay as owner overrides for the day the detection is
    wrong. Returns (plan, source) with plan in {"max","api","mixed"} and source
    naming the evidence ("setting", "oauth:max", "api_key", "default")."""
    plan = ((s or settings()).get("pm") or {}).get("plan", "auto")
    if plan and plan != "auto":
        return plan, "setting"
    try:
        from spine.ops import usage
        lm = usage.login_method()
    except Exception:
        lm = {}
    if lm.get("method") == "oauth":
        sub = lm.get("subscription")
        # subscription login = flat quota; a Console login (no subscriptionType)
        # bills the workspace per token even though it is OAuth.
        return ("max", "oauth:%s" % sub) if sub else ("api", "oauth:console")
    if lm.get("method") == "api_key":
        return "api", "api_key"
    # no Claude auth found at all (fresh box, creds unreadable): keep the old
    # default - flat - so cost surfaces never invent $-spend out of nothing.
    return "max", "default"


def ai_billing(s=None):
    """How the AI on this board is BILLED - the display contract, not the meter.
    plan_effective() names the Anthropic plan (auto-detected by default): "max"
    is the flat subscription - a turn burns quota, not cash, so the measured $
    figure is an API-equivalent reference and must never render as spend. "api"
    (and "mixed", where at least some turns are per-token) bill real money per
    token. Every turn keeps being priced either way (measured-economics law);
    only what the number MEANS differs."""
    plan, _src = plan_effective(s)
    return "flat" if plan == "max" else "metered"

WEEK_SEC = 7 * 24 * 3600
MIN_CALIB_PCT = 2.0     # below this the division amplifies rounding into nonsense

def _ts_epoch(ts):
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return 0.0

def turn_tokens(e):
    """Every token a turn drew against the plan - cache reads included, because
    the allowance counts them even though they are cheap in API dollars."""
    u = e.get("usage") or {}
    return (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0) + u.get("output_tokens", 0))

def plan_calibration(ev=None, s=None):
    """What ONE PERCENT of the Claude subscription costs, in tokens.

    On a flat plan the honest unit is SHARE OF THE PLAN. Dollars are a foreign
    currency (the API price list prices nothing that was bought), and a raw
    token count means nothing without the allowance it is drawn against - "73k
    tokens" answers no question the owner has. "3.2% of a weekly quota" does.

    Anthropic's usage endpoint reports each window as a percentage and never
    publishes the absolute limit, so we CALIBRATE against it: the tokens this
    board burned inside the live weekly window correspond to that window's
    utilization ->
        tokens_per_pct = tokens_in_window / used_pct
    An owner-set settings.pm.plan_tokens_week (the real allowance, if they know
    it) wins over the measurement. Returns None when there is nothing to
    calibrate against - no Claude login, a just-reset window, or no recorded
    turns - and every caller then falls back to showing tokens."""
    s = s or settings()
    per_week = ((s.get("pm") or {}).get("plan_tokens_week") or 0)
    if per_week > 0:
        return {"tokens_per_pct": float(per_week) / 100.0, "source": "configured",
                "window": "weekly", "used_pct": None, "observed_tokens": None}
    try:
        from spine.ops import usage as _usage
        snap = _usage.cached()          # never blocks; None while the cache is cold
    except Exception:
        return None
    if not snap or snap.get("status") != "ok":
        return None
    w = next((x for x in snap.get("windows", []) if x.get("id") == "weekly"), None)
    used = (w or {}).get("usedPct")
    if not isinstance(used, (int, float)) or used < MIN_CALIB_PCT:
        return None
    cutoff = time.time() - WEEK_SEC
    # external=True (spine.turn.econ._record_econ, a remote device with its
    # OWN Claude account - ops/docs/backlog/remote-device-execution) is
    # excluded HERE specifically: `used` above is THIS account's own usage
    # percentage from the Anthropic usage API, and an external device's
    # tokens never drew against it - folding them into `tok` would inflate
    # tokens_per_pct for every card sharing the real account. Measured
    # 2026-08-25: without this exclusion the corruption is silent, not an
    # error - the number is just wrong.
    rows = [e for e in (ev if ev is not None else read_events())
            if e.get("kind") == "turn" and not e.get("external")
            and _ts_epoch(e.get("ts", "")) >= cutoff]
    tok = sum(turn_tokens(e) for e in rows)
    if tok <= 0:
        return None
    # COST calibration beside the token one. Raw tokens over-weight cache
    # reads ~10x (a cache-read token draws ~0.1x of a fresh input token from
    # the plan, exactly like its API price) - so a card with cache-heavy turns
    # (long tool loops) showed a SMALLER "% vom Abo" than a card with fewer
    # but cache-light turns: upside down from what it really consumed ("viel
    # mehr activities und trotzdem weniger %"). The measured per-turn $
    # (price_turn) already weights every token class correctly, so the plan
    # share divides measured cost by the window's cost-per-utilization-percent.
    cost = sum(float(e.get("cost") or 0.0) for e in rows)
    out = {"tokens_per_pct": tok / float(used), "source": "measured",
           "window": "weekly", "used_pct": used, "observed_tokens": tok,
           "resets_at": w.get("resetsAt")}
    if cost > 0:
        out["cost_per_pct"] = cost / float(used)
        out["observed_cost"] = round(cost, 4)
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
    # On the flat plan the consumption unit is share-of-subscription, not tokens
    # and certainly not tokens x API price. None = not calibratable right now,
    # and every surface falls back to the raw token count.
    calib = plan_calibration(ev, s) if flat else None
    per_pct = (calib or {}).get("tokens_per_pct") or 0.0
    cost_per_pct = (calib or {}).get("cost_per_pct") or 0.0
    def plan_pct(tok, cost=None):
        # 4 decimals, not 2: a single cheap turn is a few thousandths of a
        # percent and rounding it to 0.0 would render "-" (no consumption)
        # instead of the honest "<0.01%". The UI does the human rounding.
        # COST basis wins when calibrated: raw tokens over-weight cache reads
        # ~10x, ranking a cache-heavy card BELOW a lighter one that actually
        # drew less from the plan (see plan_calibration).
        if cost is not None and cost_per_pct > 0:
            return round(float(cost) / cost_per_pct, 4)
        return round(tok / per_pct, 4) if per_pct > 0 else None
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
                      "tokens_in": t.get("tokens_in", 0), "tokens_out": t.get("tokens_out", 0),
                      "plan_pct": plan_pct(t.get("tokens_in", 0) + t.get("tokens_out", 0),
                                           cost=ai)})

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
        # the quoting number on a flat plan: what one turn of this model eats
        # out of the subscription, in percent.
        b["plan_pct_per_turn"] = (plan_pct((b["tok_in"] + b["tok_out"]) / b["turns"],
                                           cost=b["cost"] / b["turns"])
                                  if b["turns"] else None)
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
    from cells.process import processes as _processes
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
                                     "cards": 0, "done": 0, "tokens": 0})
        r["billed"] += c["billed"]; r["ai_cost"] += c["ai_cost"]
        r["tokens"] += c["tokens_in"] + c["tokens_out"]
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
                     "plan_pct": plan_pct(r["tokens"], cost=r["ai_cost"]),
                     "all_done": r["cards"] > 0 and r["done"] == r["cards"]})
    sows.sort(key=lambda x: -x["margin"])

    # company totals from per-card recognized revenue (billing-aware), so the
    # SoW rollup and the totals never double-count.
    value_done = sum(c["billed"] for c in cards)
    ai_all = sum(c["ai_cost"] for c in cards)
    tok_all = sum(c["tokens_in"] + c["tokens_out"] for c in cards)
    touch_all = sum(c["touches"] for c in cards) or 1
    # WIP limit now flows through the tracked policy control plane. policy seeds
    # its wipLimit FROM settings (below), so this is identical to the old value
    # until someone swaps it; a tracked policy.swap then changes it live. Fully
    # defensive: any policy hiccup falls back to the settings value.
    wip_limit = s["capacity"]["wip_limit"]
    try:
        from spine.auth import policy
        wip_limit = int(policy.get_policies().get("wipLimit", wip_limit))
    except Exception:
        pass
    return {
        "settings": s,
        "ai_billing": billing_mode,
        "plan_calibration": calib,
        "cards": cards,
        "sows": sows,
        "capacity": {"wip": wip, "wip_limit": wip_limit,
                     "touches_today": touches_today, "actors": actors,
                     "touch_budget_day": s["capacity"]["touch_budget_day"],
                     "headroom": max(0, wip_limit - wip)},
        "yield_first_pass": (sum(1 for ok in gated.values() if ok), len(gated)),
        "automation": (sum(1 for c in done if c["mode"] == "auto"), len(done)),
        "gate_failures": sorted(fails.items(), key=lambda kv: -kv[1]),
        "ai_by_model": dict(sorted(by_model.items(), key=lambda kv: -kv[1]["cost"])),
        "totals": {"value_delivered": round(value_done, 2),
                   "ai_spend": round(ai_all, 4),
                   "ai_tokens": tok_all,
                   "plan_pct": plan_pct(tok_all, cost=ai_all),
                   "margin": round(value_done - (0.0 if flat else ai_all), 2),
                   "leverage_per_touch": round(value_done / touch_all, 2)},
    }
