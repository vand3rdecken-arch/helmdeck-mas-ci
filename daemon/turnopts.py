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

# Curated Claude model manifest - same source-of-truth idea as Paseo's
# CLAUDE_MODEL_MANIFEST (packages/server/.../claude/model-manifest.ts): the
# `claude` CLI has no "list models" API, so the base list is hand-maintained.
# list_models() merges this with any custom models in the user's ~/.claude/
# settings.json (exactly like Paseo's getClaudeModelsWithSettings).
CLAUDE_MODELS = [
    {"id": "claude-fable-5",    "label": "Fable 5",    "desc": "Most powerful"},
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
ESCALATE_TURNS = 3      # a card that's taken this many turns has proven hard

# text is only a WEAK, secondary signal (structural signals win)
_HARD = re.compile(r"\b(refactor|architect|debug|design|analy[sz]e|"
                   r"root cause|prove|derive|reconcile|migrat)", re.I)
_EASY = re.compile(r"^\s*(hi|hey|hello|thanks|thank you|ok|okay|yes|no|got it)\b", re.I)


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
_MODELS_CACHE = os.path.join(os.path.dirname(__file__), "models_cache.json")
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
    try:
        cache = json.load(open(_MODELS_CACHE, encoding="utf-8"))
    except (OSError, ValueError):
        cache = None
    if cache and (now - cache.get("at", 0)) < _DISCOVER_TTL:
        return cache.get("models", [])
    fresh = _fetch_models()
    if fresh is not None:
        try:
            json.dump({"at": now, "models": fresh}, open(_MODELS_CACHE, "w", encoding="utf-8"))
        except OSError:
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


def pick_model(text, has_attach=False, signals=None):
    """Auto routing: cheap for trivial, strong for hard/high-stakes. Returns a
    concrete id. `signals` (optional) carries the card's own facts:
    {value: float, priority: str, turns: int} - these are the PRIMARY routing
    inputs; the prompt text is only a weak fallback. Only used when the user
    picked "Auto"; an explicit model always wins (see resolve_model)."""
    s = signals or {}
    t = text or ""
    prio = str(s.get("priority") or "").lower()
    value = float(s.get("value") or 0)
    turns = int(s.get("turns") or 0)
    failed = bool(s.get("failed"))     # card was bounced / a gate failed last round
    # STRONG tier - structural, stakes, or proven-hard signals (any one):
    #   real work in the prompt (attachment / long / code) OR a high-stakes card
    #   (urgent|high priority, or >= HIGH_VALUE) OR it already FAILED (bounce/gate
    #   -> escalate the retry) OR it's dragged on (turns >= ESCALATE_TURNS) OR
    #   hard keywords. The failed/turns paths are "escalate on measured evidence"
    #   - the next turn after a rejection gets the strong model, no retry loop.
    if (has_attach or len(t) > 600 or "```" in t
            or prio in ("urgent", "high")
            or (value and value >= HIGH_VALUE)
            or failed
            or turns >= ESCALATE_TURNS
            or _HARD.search(t)):
        return "claude-opus-5"
    # CHEAP tier - ONLY clear chatter (greetings/acks). A short imperative like
    # "add a null check" is still work -> it falls through to Sonnet, never Haiku.
    if len(t) < 40 and _EASY.search(t):
        return "claude-haiku-4-5"
    return "claude-sonnet-5"


def resolve_model(model, text, has_attach=False, signals=None):
    """(cli_model_id_or_None, chosen). '' -> driver default (None). 'auto' ->
    signal-based pick. A known model id (manifest or settings.json) -> itself.
    Unknown -> default. Server-side whitelist: arbitrary ids from the client are
    rejected. THE USER'S EXPLICIT CHOICE ALWAYS WINS - routing only runs for
    'auto'. `signals` = the card facts passed through to pick_model."""
    if model == "auto":
        mid = pick_model(text, has_attach, signals)
        return mid, mid
    model = _ALIAS.get(model, model)
    if model and model in _allowed_ids():
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
