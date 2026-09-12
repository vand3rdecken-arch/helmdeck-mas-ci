# -*- coding: utf-8 -*-
"""Shared turn options for BOTH chats (board copilot + card steer).

One source of truth so the two surfaces can't drift: model whitelist + Auto
routing, the thinking-mode directive, and attachment saving. Kept honest:
- model is a server-side whitelist - the client never passes a raw model id.
- "auto" is a real length/complexity heuristic, not a label over sonnet.
- "thinking" is a genuine prompt-level directive (the driver thinks before it
  acts) - no pretend capability.
- attachments are size/count-capped and written where the agent can read them;
  the prompt references them by path.
"""
import base64, json, os, re, time, urllib.request

from daemon.paths import DAEMON_ROOT as _DAEMON_ROOT

# Curated Claude model manifest - same source-of-truth idea as Paseo's
# CLAUDE_MODEL_MANIFEST (packages/server/.../claude/model-manifest.ts): the
# `claude` CLI has no "list models" API, so the base list is hand-maintained.
# list_models() merges this with any custom models in the user's ~/.claude/
# settings.json (exactly like Paseo's getClaudeModelsWithSettings).
CLAUDE_MODELS = [
    {"id": "claude-fable-5-1",  "label": "Fable 5.1",  "desc": "Most powerful"},
    {"id": "claude-fable-5",    "label": "Fable 5",    "desc": "Previous Fable"},
    {"id": "claude-opus-5",     "label": "Opus 5",     "desc": "Latest · most capable", "default": True},
    {"id": "claude-opus-4-8",   "label": "Opus 4.8",   "desc": "Previous Opus"},
    {"id": "claude-sonnet-5",   "label": "Sonnet 5",   "desc": "Best for everyday work"},
    {"id": "claude-opus-4-7",   "label": "Opus 4.7",   "desc": "Older release"},
    {"id": "claude-opus-4-6",   "label": "Opus 4.6",   "desc": "Older · complex work"},
    {"id": "claude-sonnet-4-6", "label": "Sonnet 4.6", "desc": "Older everyday"},
    {"id": "claude-haiku-4-5",  "label": "Haiku 4.5",  "desc": "Fastest · cheapest"},
]
# friendly aliases still resolve (older drafts / Auto internals)
_ALIAS = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5", "opus": "claude-opus-5"}

# Auto routing looks at STRUCTURAL signals (the card's own facts) first, and only
# falls back to reading the prompt text - text keywords are noisy ("why not" is
# not hard work), the card's value/priority/turn-count are facts. Community
# practice (FrugalGPT cascades, role-based routing): route on evidence, escalate
# on measured difficulty. These thresholds are policy - kept as named constants
# so they can later move to settings (events.settings) without touching logic.
HIGH_VALUE = 100.0      # €: a card worth this much gets the best model on Auto
ESCALATE_TURNS = 3      # consecutive GATE FAILS before needs_you (sessions.py);
                        # no longer a model-routing trigger (owner decree 2026-09-04)

# text signals: _HARD is no longer a routing trigger (it fired on ordinary
# German card prose - see pick_model), kept only as documentation of the class
_HARD = re.compile(r"\b(refactor|architect|debug|design|analy[sz]e|"
                   r"root cause|prove|derive|reconcile|migrat)", re.I)
_EASY = re.compile(r"^\s*(hi|hey|hello|thanks|thank you|ok|okay|yes|no|got it)\b", re.I)

# -- context windows: a model must be able to HOLD the session it resumes -----
# MEASURED 2026-08-30 from the failure it explains: Henry's board session stood
# at 615,889 tokens (daemon/copilot_stats.json) when the owner typed "Ok" into
# card 20260830-065545. Two characters, matched by _EASY, routed to the CHEAP
# tier - and Haiku's window is 200k, not the 1M the session had grown into. The
# CLI resumes the WHOLE transcript, so the API rejected the request with
# "Prompt is too long" before the model read a single word of the new message.
# The card's own meter (110k/55%) described the WORKER's session, a different
# conversation entirely - which is why the number looked impossible.
#
# The routing tier and the window are independent facts: picking "cheap because
# the message is trivial" is only valid if cheap can still carry the history.
CTX_WINDOWS = {
    "claude-haiku-4-5":  200_000,
    "claude-sonnet-4-6": 1_000_000,
    "claude-sonnet-5":   1_000_000,
    "claude-opus-4-6":   1_000_000,
    "claude-opus-4-7":   1_000_000,
    "claude-opus-4-8":   1_000_000,
    "claude-opus-5":     1_000_000,
    "claude-fable-5":    1_000_000,
    "claude-fable-5-1":  1_000_000,
}
# room the resumed transcript is NOT allowed to occupy: the board snapshot, the
# system brief, this turn's text and the reply all ride on top of ctx_tokens.
CTX_HEADROOM = 32_000
# escalation ladder when the picked model cannot hold the session - cheapest
# model with a measured window that fits, strongest last.
_CTX_LADDER = ("claude-sonnet-5", "claude-opus-5")


def model_window(mid):
    """Context window for a model id, or None when UNKNOWN.

    Two witnesses, both from the runtime itself (sessions._record_econ parity):
    the "[1m]" suffix the CLI stamps on a 1M-tier id, and the measured table
    above. Anything else returns None - never a guess. A None window means the
    fit check declines to act: we only ever exclude a model we positively KNOW
    is too small, so a newly shipped model can't be mis-escalated by this code
    on the day it appears."""
    m = (mid or "").strip().lower()
    if not m:
        return None
    if "[1m]" in m:
        return 1_000_000
    m = m.split("[")[0]
    for known, win in CTX_WINDOWS.items():
        if m == known or m.startswith(known + "-"):   # dated ids: ...-20251001
            return win
    return None


def fits_window(mid, ctx_tokens):
    """`mid`, or the cheapest model that can actually hold `ctx_tokens`.

    ctx_tokens is the DERIVED context meter (copilot_stats._fold_stats /
    econ._record_econ fold it at event time from the last assistant call's own
    usage) - not an estimate and not a re-scan of the transcript. No reading =
    no action: a 0/None ctx leaves the pick untouched."""
    ctx = int(ctx_tokens or 0)
    if ctx <= 0:
        return mid
    win = model_window(mid)
    if win is None or ctx + CTX_HEADROOM <= win:
        return mid
    for cand in _CTX_LADDER:
        w = model_window(cand)
        if w and ctx + CTX_HEADROOM <= w:
            return cand
    return mid              # nothing measurably fits - keep the caller's pick


def _settings_models():
    """Custom models from the user's ~/.claude/settings.json (model + the
    ANTHROPIC_*_MODEL env keys) - the dynamic half of Paseo's list."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    try:
        with open(os.path.join(cfg, "settings.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    out, seen = [], set()
    def add(v):
        v = v.strip() if isinstance(v, str) else ""
        if v and v not in seen:
            seen.add(v); out.append({"id": v, "label": v, "desc": "from ~/.claude/settings.json"})
    add(d.get("model"))
    env = d.get("env") if isinstance(d.get("env"), dict) else {}
    for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
              "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL"):
        add(env.get(k))
    return out


# -- auto-register: live model discovery from Anthropic's /v1/models ----------
# The `claude` CLI has no list-models command, but the HTTP API does. We reuse
# the CLI's own OAuth token (~/.claude/.credentials.json) so a NEW model appears
# in the picker the day Anthropic ships it - no code edit, no rebuild. The static
# CLAUDE_MODELS manifest degrades to what community tooling (LiteLLM, Aider) uses
# it for: curated labels/order + an OFFLINE FALLBACK. Cached 24h; any failure
# (no token, offline, 401) silently falls back to the last cache, then the
# manifest - the picker is never empty.
_MODELS_CACHE_KEY = "models_cache"   # runtime_doc row (state-into-db phase D)
_DISCOVER_TTL = 24 * 3600


def _oauth_token():
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    try:
        d = json.load(open(os.path.join(cfg, ".credentials.json"), encoding="utf-8"))
        return (d.get("claudeAiOauth") or {}).get("accessToken")
    except (OSError, ValueError, AttributeError):
        return None


def _fetch_models():
    """Live [{id, display_name}] from Anthropic /v1/models, or None on failure."""
    tok = _oauth_token()
    if not tok:
        return None
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/models?limit=1000",
            headers={"Authorization": "Bearer " + tok,
                     "anthropic-version": "2023-06-01",
                     "anthropic-beta": "oauth-2025-04-20"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.load(r)
        out = [{"id": m["id"], "display_name": m.get("display_name") or m["id"]}
               for m in data.get("data", []) if m.get("id")]
        return out or None
    except Exception:
        return None


def _discovered():
    """Cached live models (24h TTL). Fetches when stale; on failure serves the
    last good cache; [] if none (then the manifest stands alone)."""
    now = time.time()
    from spine.storage import db
    try:
        cache = db.doc_get(_MODELS_CACHE_KEY)
    except Exception:                                            # noqa: BLE001
        cache = None
    if cache and (now - cache.get("at", 0)) < _DISCOVER_TTL:
        return cache.get("models", [])
    fresh = _fetch_models()
    if fresh is not None:
        try:
            db.doc_put(_MODELS_CACHE_KEY, {"at": now, "models": fresh})
        except Exception:                                        # noqa: BLE001
            pass
        return fresh
    return (cache or {}).get("models", [])   # stale cache, or [] -> manifest only


def list_models():
    """Curated manifest (labels/order/default) + AUTO-DISCOVERED live models +
    custom settings.json models, deduped (id order preserved). New Anthropic
    models are appended automatically; the manifest just gives the known ones
    nice labels and the offline fallback."""
    models = [dict(m) for m in CLAUDE_MODELS]
    ids = {m["id"] for m in models}
    for m in _discovered():
        if m["id"] not in ids:
            ids.add(m["id"])
            models.append({"id": m["id"], "label": m.get("display_name") or m["id"],
                           "desc": "auto-discovered"})
    for m in _settings_models():
        if m["id"] not in ids:
            ids.add(m["id"]); models.append(m)
    return models


def _allowed_ids():
    return {m["id"] for m in list_models()}


# The mechanism's own defaults - what every caller gets when it passes no
# `policy` (or a caller that hasn't been migrated yet). These are no longer
# the only answer: cells/engineer/cards/turnrunner.py::_routing_policy and
# cells/copilot/chat/copilot.py resolve the project-overridable rows
# (spine/registry/behavior.py: routing.auto_model/escalate_value/
# escalate_urgent) and pass the effective policy in. turnopts itself stays
# the MECHANISM - whitelist, window law, explicit-wins - never the policy
# owner (owner decree 2026-09-04: routing policy is Henry/engineer logic per
# project, not a spine constant).
DEFAULT_ROUTING_POLICY = {
    "auto_model": "claude-sonnet-5",
    "strong_model": "claude-opus-5",
    "cheap_model": "claude-haiku-4-5",
    "escalate_value": HIGH_VALUE,
    "escalate_urgent": True,
}


def pick_model(text, has_attach=False, signals=None, policy=None):
    """Auto routing: cheap for trivial, strong for hard/high-stakes. Returns a
    concrete id. `signals` (optional) carries the card's own facts:
    {value: float, priority: str, turns: int, ctx_tokens: int} - these are the
    PRIMARY routing inputs; the prompt text is only a weak fallback. Only used
    when the user picked "Auto"; an explicit model always wins (see
    resolve_model). `ctx_tokens` is a HARD constraint, not a preference - see
    fits_window. `policy` (optional) overrides DEFAULT_ROUTING_POLICY - the
    per-project routing.* rows resolved by the calling cell; missing keys fall
    back to the default so an unmigrated caller sees no change."""
    s = signals or {}
    t = text or ""
    p = {**DEFAULT_ROUTING_POLICY, **(policy or {})}
    prio = str(s.get("priority") or "").lower()
    value = float(s.get("value") or 0)
    turns = int(s.get("turns") or 0)
    # `fails` = consecutive gate failures from the append-only event log (real
    # trailing evidence, via events.consecutive_gate_fails). `failed` stays a
    # back-compat one-shot flag; either one means "escalate the retry".
    fails = int(s.get("fails") or 0)
    failed = bool(s.get("failed")) or fails > 0
    _ = turns  # kept in the signal shape; no longer a trigger (see below)
    # STRONG tier - every return goes through fits_window: the tier answers
    # "how hard is this turn", the window answers "can that model still carry
    # the conversation". Both must hold, the second is not negotiable - see
    # CTX_WINDOWS. The failed path is "escalate on measured evidence": the
    # next turn after a gate rejection gets the strong model, no retry loop.
    ctx = s.get("ctx_tokens")
    # Owner decree 2026-09-04: Sonnet 5 IS the Auto model for card
    # implementation (now `policy["auto_model"]`, project-overridable). Three
    # former STRONG triggers got dropped because each was measured to fire on
    # ordinary cards and starve Sonnet, exactly like the length/backtick pair
    # before them:
    #  - prio "high": Henry mints practically every chat-born direct card
    #    priority=high (all recent -direct cards -> 100% Opus);
    #  - turns >= ESCALATE_TURNS(3): a normal implementation card reaches 3
    #    turns routinely (live board 2026-09-04: turns 4/5/7/9/34 on ordinary
    #    cards) - turn count is age, not difficulty;
    #  - _HARD keywords: German card prose trips them constantly ("Design",
    #    "Root Cause", "migrat..." in 2 of 5 recent cards).
    # What still escalates is deliberate or measured: "urgent" (unless the
    # project switched escalate_urgent off), a card worth escalate_value, an
    # attachment, or a real gate failure (retry gets strength).
    if (has_attach
            or (p["escalate_urgent"] and prio == "urgent")
            or (value and value >= float(p["escalate_value"]))
            or failed):
        return fits_window(p["strong_model"], ctx)
    # CHEAP tier - ONLY clear chatter (greetings/acks). A short imperative like
    # "add a null check" is still work -> it falls through to Sonnet, never Haiku.
    if len(t) < 40 and _EASY.search(t):
        return fits_window(p["cheap_model"], ctx)
    return fits_window(p["auto_model"], ctx)


def resolve_model(model, text, has_attach=False, signals=None, policy=None):
    """(cli_model_id_or_None, chosen). '' -> driver default (None). 'auto' ->
    signal-based pick. A known model id (manifest or settings.json) -> itself.
    Unknown -> default. Server-side whitelist: arbitrary ids from the client are
    rejected. THE USER'S EXPLICIT CHOICE ALWAYS WINS - routing only runs for
    'auto'. `signals` = the card facts passed through to pick_model. `policy` =
    the project's resolved routing.* rows, passed through to pick_model
    untouched - an explicit model pick never reads it.

    ONE exception to "explicit wins", and it is a capability limit rather than a
    preference: a model whose measured window cannot hold the session about to
    be resumed cannot answer AT ALL - the API rejects the request outright. The
    voice path proves this is not hypothetical: routes_copilot pins `haiku` for
    every spoken turn (a SYSTEM default, not a typed pick), and on a 615k board
    session that is a guaranteed "Prompt is too long". So an explicit pick is
    lifted - never lowered, never touched when it fits, and only ever on a
    window we positively measured (see fits_window / CTX_WINDOWS)."""
    ctx = (signals or {}).get("ctx_tokens")
    if model == "auto":
        mid = pick_model(text, has_attach, signals, policy)
        return mid, mid
    model = _ALIAS.get(model, model)
    if model and model in _allowed_ids():
        model = fits_window(model, ctx)
        return model, model
    return None, ""  # default: let the driver/session default decide


MAX_FILES = 6
MAX_BYTES = 5 * 1024 * 1024          # per file
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name, i):
    base = _SAFE.sub("_", os.path.basename(name or "")).strip("._") or ("file%d" % i)
    return base[:80]


def save_attachments(dest_dir, attachments):
    """attachments = [{name, data(base64), mime?}]. Writes capped files into
    dest_dir/.attachments and returns the list of saved absolute paths. Silently
    skips anything oversized or malformed - an attachment must never crash a turn."""
    if not attachments:
        return []
    out_dir = os.path.join(dest_dir, ".attachments")
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for i, a in enumerate(attachments[:MAX_FILES]):
        try:
            raw = base64.b64decode((a.get("data") or "").split(",")[-1], validate=False)
        except Exception:
            continue
        if not raw or len(raw) > MAX_BYTES:
            continue
        path = os.path.join(out_dir, "%d_%s" % (i, _safe_name(a.get("name"), i)))
        try:
            with open(path, "wb") as f:
                f.write(raw)
            saved.append(path)
        except OSError:
            continue
    return saved


# thinking LEVELS - each directive embeds the Claude Code budget keyword
# (think < think hard < ultrathink) so extended thinking is really allocated,
# not just described. "" / None = off.
THINK_LEVELS = {
    "think": "Think about this step by step before you act.\n\n",
    "think-hard": "Think hard about this - reason through the approach, edge "
                  "cases, and consequences before you act.\n\n",
    "ultrathink": "Ultrathink about this before you act: reason very carefully "
                  "and thoroughly, considering approach, edge cases, and "
                  "consequences, then proceed.\n\n",
}


def augment_prompt(text, thinking="", attach_paths=None):
    """Assemble the prompt actually sent to the driver. `thinking` is a level key
    (think|think-hard|ultrathink) or falsy for off. The human's original text is
    logged elsewhere; this augmented form is what the agent receives."""
    parts = []
    directive = THINK_LEVELS.get(thinking) if thinking else None
    if directive:
        parts.append(directive)
    parts.append(text or "")
    if attach_paths:
        rel = ", ".join(attach_paths)
        parts.append("\n\nAttached files (read them as needed): " + rel)
    return "".join(parts)
