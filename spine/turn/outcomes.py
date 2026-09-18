# -*- coding: utf-8 -*-
"""Card outcome extraction — the 1-2 line result sentence derived from a card's
final reply, split out of sessions.py. Pure text parsing; sessions.py re-imports
these names (the accept mutators call _record_outcome, backfill_outcomes calls
extract_outcome). Not monkeypatched.
"""
import re

_DELIVERED_RE = re.compile(r"\bDELIVERED\b[:\s*-]*", re.I)
_READY_TAIL_RE = re.compile(r"ready for review\b.*", re.I | re.S)


def _first_lines(text):
    """1-2 lines out of `text`, hand-off boilerplate stripped, word-boundary
    cut past 240 chars (never a bare slice - the same defect
    turnrunner._clip_reply/notice.label exist to avoid). '' when nothing
    usable. Shared by extract_outcome (candidate = the DELIVERED tail, or the
    whole reply) and lede (candidate = whatever comes BEFORE that tail)."""
    lines = [l.strip(" \t*-#") for l in _READY_TAIL_RE.sub("", text).splitlines()]
    lines = [l for l in lines if l]
    if not lines:
        return ""
    out = " ".join(lines[:2])
    if len(out) <= 240:
        return out
    cut = out[:238]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 120 else cut).rstrip(" ,;:-") + " …"


def extract_outcome(reply):
    """A 1-2 line result sentence from a card's final reply: the agent's
    DELIVERED summary (cells/engineer/harness/agents/card-worker.md convention, same anchor ask.py keys
    off) when present, else the reply's first lines. '' when nothing usable."""
    text = (reply or "").strip()
    if not text:
        return ""
    m = _DELIVERED_RE.search(text)
    for cand in ([text[m.end():]] if m else []) + [text]:
        out = _first_lines(cand)
        if out:
            return out
    return ""


def lede(reply):
    """The reply's OWN opening statement - whatever it said BEFORE any
    DELIVERED/ready-for-review tail - as 1-2 lines. '' when there is nothing
    ahead of that marker (e.g. a reply that opens with "DELIVERED: ..."
    itself), NOT the tail - callers that want a guaranteed pick fall back to
    extract_outcome for that.

    Exists apart from extract_outcome because the two readers of a reply want
    OPPOSITE halves of it: extract_outcome's DELIVERED tail is written for
    Henry's planning snapshot (sessions._record_outcome persists it there) and
    deliberately keeps the file names/commit hash that snapshot needs; the
    owner's chat inbox (cells/copilot/chat/card_mirror.py) wants the
    plain-language sentence a worker wrote BEFORE it started listing what it
    touched - the one that actually answers 'did it work' (owner complaint
    2026-09-15: the inbox was printing the technical tail, mangled, instead)."""
    text = (reply or "").strip()
    if not text:
        return ""
    m = _DELIVERED_RE.search(text)
    head = text[:m.start()] if m else text
    return _first_lines(head)


def excerpt(text, max_chars=1500):
    """The reply's own words, WHOLE up to `max_chars`, cut on a word boundary
    with an explicit pointer past the cut. Unlike lede/extract_outcome this is
    not a distillation - callers that want to hand the worker's actual
    sentence to an owner-facing announcement (a card-close report riding
    alongside Henry's own text) use this instead of a plain-language summary.
    '' when there is nothing to show."""
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    sp = cut.rfind(" ")
    clipped = (cut[:sp] if sp > max_chars // 2 else cut).rstrip(" ,;:-")
    return clipped + " … (weiter im Thread)"


def _record_outcome(tt):
    """Runs INSIDE the accept mutators. Keeps an existing outcome when the
    final reply yields nothing (e.g. a re-accept after a silent lane fix)."""
    out = extract_outcome(tt.get("last_reply"))
    if out:
        tt["outcome"] = out
