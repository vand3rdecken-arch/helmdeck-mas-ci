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
import base64, json, os, re

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

# a turn "looks hard" if it's long, has attachments, or reads like real work
_HARD = re.compile(r"\b(refactor|architect|debug|why|design|analy[sz]e|plan|"
                   r"trade-?off|root cause|prove|derive|reconcile|migrat)", re.I)
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


def list_models():
    """The manifest + custom settings.json models, deduped (id order preserved)."""
    models = [dict(m) for m in CLAUDE_MODELS]
    ids = {m["id"] for m in models}
    for m in _settings_models():
        if m["id"] not in ids:
            ids.add(m["id"]); models.append(m)
    return models


def _allowed_ids():
    return {m["id"] for m in list_models()}


def pick_model(text, has_attach=False):
    """Auto routing: cheap for trivial, deep for hard. Returns a concrete id."""
    t = text or ""
    if has_attach or len(t) > 600 or "```" in t or _HARD.search(t):
        return "claude-opus-5"
    if len(t) < 40 and not _HARD.search(t) and (_EASY.search(t) or "?" not in t):
        return "claude-haiku-4-5"
    return "claude-sonnet-5"


def resolve_model(model, text, has_attach=False):
    """(cli_model_id_or_None, chosen). '' -> driver default (None). 'auto' ->
    heuristic. A known model id (manifest or settings.json) -> itself. Unknown ->
    default. Server-side whitelist: arbitrary ids from the client are rejected."""
    if model == "auto":
        mid = pick_model(text, has_attach)
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
