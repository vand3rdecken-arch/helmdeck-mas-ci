# -*- coding: utf-8 -*-
"""Card outcome extraction — the 1-2 line result sentence derived from a card's
final reply, split out of sessions.py. Pure text parsing; sessions.py re-imports
these names (the accept mutators call _record_outcome, backfill_outcomes calls
extract_outcome). Not monkeypatched.
"""
import re

_DELIVERED_RE = re.compile(r"\bDELIVERED\b[:\s*-]*", re.I)
_READY_TAIL_RE = re.compile(r"ready for review\b.*", re.I | re.S)


def extract_outcome(reply):
    """A 1-2 line result sentence from a card's final reply: the agent's
    DELIVERED summary (cells/engineer/harness/agents/card-worker.md convention, same anchor ask.py keys
    off) when present, else the reply's first lines. '' when nothing usable."""
    text = (reply or "").strip()
    if not text:
        return ""
    m = _DELIVERED_RE.search(text)
    for cand in ([text[m.end():]] if m else []) + [text]:
        lines = [l.strip(" \t*-#") for l in _READY_TAIL_RE.sub("", cand).splitlines()]
        lines = [l for l in lines if l]
        if lines:
            out = " ".join(lines[:2])
            if len(out) <= 240:
                return out
            # word-boundary cut, not a bare slice - a raw [:240] ends mid-word
            # (the same defect turnrunner._clip_reply/notice.label exist to
            # avoid). Only ever reached for a single unbroken line past 240
            # chars; the 1-2 line join above is already short in practice.
            cut = out[:238]
            sp = cut.rfind(" ")
            return (cut[:sp] if sp > 120 else cut).rstrip(" ,;:-") + " …"
    return ""


def _record_outcome(tt):
    """Runs INSIDE the accept mutators. Keeps an existing outcome when the
    final reply yields nothing (e.g. a re-accept after a silent lane fix)."""
    out = extract_outcome(tt.get("last_reply"))
    if out:
        tt["outcome"] = out
