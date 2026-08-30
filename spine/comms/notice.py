# -*- coding: utf-8 -*-
"""THE LENGTH LAW for anything the harness says to the owner unprompted.

Owner decree 2026-08-30, on the PM's daily "Ziel vs. Budget" block:

    "Diese Karte sollte in der Form nicht mehr im Chat sein. Zu viel info..
     bzw ich weiss nicht was ich dazu machen soll."

Two rules came out of that, and only the first one lives here:

  1. LENGTH - an owner-visible automatic notice is at most two short
     sentences. Enforced here, in code, at the writers' edge.
  2. ROUTING - a notice with no owner DECISION in it does not go to his chat
     at all; it goes to the dashboard feed or to Henry. That one cannot be a
     function, because only the caller knows whether there is a decision. It
     is enforced per-notice, at each call site (cells/pm/pm_comm.py's
     _to_henry / _ask_owner carry it).

WHY spine AND NOT THE PM CELL
-----------------------------
Two cells speak into the owner's one chat without him typing: the pm cell
(pm_comm._say/_escalate) and the copilot cell (henry_broker._notify_owner -
free LLM prose, and therefore the likeliest future source of exactly the wall
this law bans). A cap that lived in either cell would have to be imported by
the other, which is the cross-cell reach the four-folder rule exists to stop.
Shared infrastructure no cell owns is spine, and "how we reach the owner" is
already spine/comms (notify, presence).

This module deliberately holds no policy about WHICH notices exist, no i18n
and no delivery - it clips a string and nothing else, so it can never become
the second place a routing decision is made.
"""
import re

# Two SHORT sentences - the owner's own measure of what a notice may be.
MAX_CHARS = 240
MAX_SENTENCES = 2

# A SENTENCE END, not merely a period. The naive "split on [.!?…]" version of
# this was written first and the watchdog test caught it immediately: these
# notices are FULL of decimal points ("~6.0% vom Wochenkontingent statt ~5.0%"),
# and splitting on those cut the line after "hat ~6." - throwing away the ask
# and keeping the number, the exact inversion of what the decree wants.
#
# So a terminator is a period/!/?/… followed by WHITESPACE OR END, and NOT one
# that trails
#   - a single-letter word: "z. B.", initials;
#   - a DIGIT: German dates are the case that bit second - "So 30.08. 20:00"
#     puts a period-then-space right in the middle of a timestamp, so a notice
#     that named a reset time got cut at the date.
# Both guards can only ever make the clip keep MORE text. That is the safe
# direction to be wrong in: the character cap below bounds the line either way,
# whereas a false terminator silently amputates the sentence that carries the
# owner's actual move.
_TERMINATOR = re.compile(r"(?<!\b\w)(?<!\d)[.!?…]+(?=\s|$)")


def short(text, chars=MAX_CHARS, sentences=MAX_SENTENCES):
    """Clip an owner-visible notice to at most `sentences` sentences and
    `chars` characters, on a word boundary, marked as clipped.

    FOR CHANNELS THAT CANNOT SCROLL - and ONLY those. An FCM push, a watch
    line, a question's button header: surfaces where the text that does not fit
    is text the owner will never see. NOT the board chat. The chat is a
    transcript with its own honest fold (card_transcript.tsx clampText: past
    1600 chars it collapses behind a "mehr anzeigen" toggle, nothing lost), so a
    clip on the way IN throws away what the fold would have kept one tap away.
    This is not a style preference, it is a measured regression: short() was
    wired into the two chat writers on 2026-08-30 and the owner photographed the
    result at 14:08 the same day - a Henry card ending mid-thought in "…"
    directly beneath intact ordinary bubbles. Both writers are back to whole
    text (henry_broker._notify_owner, pm_comm._say); a third one is the bug.

    Enforced in the WRITER on purpose - the writer at the UNSCROLLABLE edge. The
    previous form of this rule was a style request in a prompt plus the good
    intentions of whoever wrote each format string, and it held for none of them
    - _goal_budget_text alone concatenated up to five sentences of projections.
    For the CHAT that discipline lives in the notice AUTHORS instead, and
    ops/tests/test_notice_routing.py asserts it directly (`short(line) == line`):
    a notice must be born short enough that the clip never has to fire.

    Newlines collapse to one line: a bulleted wall is precisely the shape the
    owner rejected, so a notice that wants a list has to pick its ONE item
    itself rather than lean on the clip to do it - which would silently drop
    the rest without saying so.

    The " …" is not decoration: a clipped line that does not admit it was
    clipped reads as the complete message (the watch learned this the hard
    way, d243545; card_mirror.RESULT_MAX carries the same marker).

    `chars` is a TRUE ceiling - the marker is paid for out of the budget, not
    added on top of it. It used to return chars+2, which contradicted this
    docstring and, worse, made the function unusable at a hard edge: a caller
    with a real byte limit had to write short(text, chars-2) and every one of
    them would have got that subtraction wrong eventually."""
    t = " ".join((text or "").split())
    if not t:
        return t
    ends = [m.end() for m in _TERMINATOR.finditer(t)]
    out = t[:ends[sentences - 1]].strip() if len(ends) >= sentences else t
    if len(out) > chars:
        cut = out[:max(chars - 2, 0)]          # 2 = len(" …"), reserved up front
        sp = cut.rfind(" ")
        out = (cut[:sp] if sp > chars // 2 else cut).rstrip(" ,;:-") + " …"
    return out


LABEL_MAX = 42


def label(text, fallback="?", chars=LABEL_MAX):
    """A card's KURZNAME - what the owner would call it out loud.

    The first line, clipped on a WORD boundary. Not the same job as short():
    that bounds a whole notice by sentences, this names ONE thing inside a
    sentence, so it must never cut mid-word. The first live tick of the notice
    rework showed why it matters - the budget question read

        „UX-FIX (Owner-Beschwerde 2026-08-30): Die automatischen PM-M“

    which is a raw [:60] slice and reads like a truncated log line, not like a
    card the owner recognises.

    card_mirror.short_name() had solved this months ago and is now this
    function's only other caller, delegating here so the rule has ONE owner
    (its word-boundary threshold is normalised from >20 to >chars//2, a
    one-index difference on a 42-char label and the more principled rule:
    take the word boundary unless it costs more than half the label)."""
    first = (text or "").replace("\r", "\n").split("\n")[0].strip()
    if not first:
        return fallback or "?"
    if len(first) <= chars:
        return first
    cut = first[:chars]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > chars // 2 else cut).rstrip(" ,.;:-") + "…"
