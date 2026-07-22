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
import base64, os, re

# whitelist: friendly key -> concrete model id passed to the driver
MODELS = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5",
          "opus": "claude-opus-4-8"}

# a turn "looks hard" if it's long, has attachments, or reads like real work
_HARD = re.compile(r"\b(refactor|architect|debug|why|design|analy[sz]e|plan|"
                   r"trade-?off|root cause|prove|derive|reconcile|migrat)", re.I)
_EASY = re.compile(r"^\s*(hi|hey|hello|thanks|thank you|ok|okay|yes|no|got it)\b", re.I)


def pick_model(text, has_attach=False):
    """Auto routing (Paseo-style): cheap for trivial, deep for hard."""
    t = text or ""
    if has_attach or len(t) > 600 or "```" in t or _HARD.search(t):
        return "opus"
    if len(t) < 40 and not _HARD.search(t) and (_EASY.search(t) or "?" not in t):
        return "haiku"
    return "sonnet"


def resolve_model(model, text, has_attach=False):
    """(cli_model_id_or_None, chosen_key). '' -> driver default (None).
    'auto' -> heuristic. A known key -> that model. Unknown -> default."""
    if model == "auto":
        key = pick_model(text, has_attach)
        return MODELS[key], key
    if model in MODELS:
        return MODELS[model], model
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
