# -*- coding: utf-8 -*-
"""Glasses /glance payload - extracted from server.py. glance_payload is
"what wants ME" (every card blocked on the human, via sessions.owner_blockers)
+ the "yours" bucket (manual-only cards); _glance_question trims a pending
decision to the lens caps. Testable without a socket. server.py re-imports
both names. Not monkeypatched.
"""

# a red gate or an unlandable branch is DEAD work, an unanswered question is
# STALLED work, and finished work is merely waiting. Worst news first.
GLANCE_RANK = {"gate": 0, "conflict": 1, "failed": 2,
               "question": 3, "review": 4, "delivered": 5}

# GLASS MODE caps. The lens is 960x540 and shows ONE card at a time (the
# on-device UX law: "one card fills the lens; you flip between cards, you don't
# scroll a wall"), so a question that would need scrolling is worse than useless
# there. These trim for the DISPLAY only - the phone still renders the full text
# from the untouched question on the track.
GLASS_Q_LEN = 160
GLASS_LABEL_LEN = 40
GLASS_DESC_LEN = 90
GLASS_MAX_OPTIONS = 6

# --- WEARABLE TEXT --------------------------------------------------------
#
# One policy, one implementation, two surfaces. These three moved here from
# routes_wear.py (where they were `_WEAR_MD`, `_wear_clip`, `_wear_text`) when
# the LENS gained a transcript of its own and needed byte-identical treatment.
#
# That file's own comment is the argument for the move: it had already been
# through this once, when /wear/board and /wear/chat carried two different clip
# rules and the weaker one shipped markdown to the wrist - "One wrist-text
# policy, one function". A second copy under surfaces/glasses would have been
# the same mistake one surface wider, and the failure mode is quiet: the watch
# renders a reply cleanly while the glasses render the same reply with literal
# '**' on it, and nothing errors.
#
# routes_wear.py keeps its private names as thin aliases, so the watch path and
# ops/tests/test_wear_card_body.py are unchanged in behaviour and in spelling.

import re

# The markup a renderer makes invisible and a bare screen shows as characters.
# Headings and list bullets per line (re.M); emphasis and code ticks anywhere.
# Deliberately NOT a markdown parser - it only removes the markers that would
# otherwise read as '**DELIVERED**' on a display with no formatting.
_MD_MARKS = re.compile(r"^\s{0,3}#{1,6}\s*|^\s{0,3}[-*+]\s+|\*\*|__|`+", re.M)


def clip_text(text, cap):
    """Cut at a boundary, and SAY that it was cut.

    Owner, 2026-08-29, reading a turn report on the watch: "Message
    abgeschnitten." A plain text[:cap] ends mid-word, which reads as a bug in
    the message rather than as a bound on the screen.

    Prefer a sentence end; fall back to a word boundary; the ellipsis is added
    either way so a cut is never mistaken for the end of the thought. The
    sentence end is only accepted in the second half of the budget - otherwise a
    single early full stop would throw away most of what fits.
    """
    text = text or ""
    if cap is None or len(text) <= cap:
        return text
    head = text[:cap]
    end = -1
    for mark in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        end = max(end, head.rfind(mark))
    if end >= cap // 2:
        return head[:end + 1].rstrip() + " ..."
    sp = head.rfind(" ")
    if sp <= 0:
        return head.rstrip() + "..."
    return head[:sp].rstrip(" ,;:-") + " ..."


def readable(raw, cap=None):
    """Agent prose, made readable on a screen with no markdown renderer.

    Three things are stripped, each for a reason established on a real device
    rather than invented here:

     1. the <helmdeck-ask> block, via ask.parse - the same parse every caller of
        this already uses. The STORED reply keeps the block verbatim (it is an
        interaction, and the live paths hand back the typed half separately);
        rendering it raw is the screenful of '{"label": ...' JSON the owner
        photographed on his watch on 2026-08-29.
     2. fenced blocks. ```actions is machine syntax and a code fence is
        unreadable at this width; taking the EVEN split segments drops the
        fenced halves and keeps the prose between them.
     3. markdown markers, which only a renderer makes invisible.

    Blank-line structure is KEPT (collapsed to one), because paragraph breaks
    are the only thing left telling the eye where a thought ends. Whitespace
    inside a line is collapsed - a wrapped narrow line has no use for the
    phone's columns.
    """
    from spine.ops import ask
    _q, prose = ask.parse(raw or "")
    text = prose or raw or ""
    text = "".join(text.split("```")[0::2])
    text = _MD_MARKS.sub("", text)
    out, blank = [], False
    for line in text.splitlines():
        line = " ".join(line.split())
        if not line:
            blank = True
            continue
        if out and blank:
            out.append("")
        blank = False
        out.append(line)
    return clip_text("\n".join(out).strip(), cap)


def _glance_question(t):
    """The pending decision, trimmed for the lens - or None.

    Only the fields a tap needs: the prompt, the header (which is the key the
    answer is posted under) and the option labels. Descriptions are included but
    hard-trimmed; the worker's full reasoning prose is deliberately NOT here,
    because it is paragraphs long and the lens cannot scroll it.
    """
    q = (t or {}).get("question") or {}
    qs = q.get("questions") or []
    if not qs:
        return None
    out = []
    for one in qs:
        out.append({
            "question": (one.get("question") or "")[:GLASS_Q_LEN],
            "header": one.get("header") or "",
            "multiSelect": bool(one.get("multiSelect")),
            "options": [{"label": (o.get("label") or "")[:GLASS_LABEL_LEN],
                         "description": (o.get("description") or "")[:GLASS_DESC_LEN]}
                        for o in (one.get("options") or [])[:GLASS_MAX_OPTIONS]],
        })
    # request_id is what makes an answer STALE-SAFE: the worker replaces its
    # question on every turn, and /glance/answer refuses a pick that names a
    # question the card has already moved past.
    return {"id": q.get("id") or "", "questions": out}


def glance_payload(tracks, m):
    """The /glance body: "what wants ME" - EVERY card blocked on the human, not
    just the parked ones. A red gate, an open merge conflict, a failed dispatch
    and a card resting on Review for an accept are all stuck until he acts, and
    all of them used to be invisible here because this surface re-derived
    "needs me" from `status == needs_you` on its own.

    sessions.owner_blockers is now the one place that is decided - the same one
    the PM narrative reads - and it presents each card first, so one whose turn
    died (a phantom `running`) counts as the owner's move the moment it is read,
    without waiting for the reconciler to heal the stored value. A card waiting
    on its own background task is nobody's move but the machine's and stays off
    the glasses.

    `yours` is a SECOND, separate bucket: cards only the owner can ever start
    (mode human/teach/cowork), which every auto-dispatch path structurally
    skips. They are unstarted work rather than stuck work, so merging them into
    needs_you would bury a red gate under a backlog - but leaving them out
    entirely is how they became invisible everywhere at once.

    Split out of do_GET so the selection is testable without a socket - the gap
    this closes is precisely the kind no test could reach before."""
    import time
    from cells.engineer import sessions
    ny = [{"id": t["id"], "task": (t.get("task") or "")[:70],
           "client": t.get("client", ""), "status": t.get("status"),
           "reason": b["reason"], "detail": b["detail"],
           # kept for glasses builds older than the reason vocabulary:
           # they render `asking` and nothing else
           "asking": b["reason"] == "question",
           # GLASS MODE: the decision ITSELF, not just the fact that one is
           # due. Without the options on the lens the glasses can only say
           # "this card asks you" and send you to the phone - the opposite of
           # deciding hands-free. None for every non-asking card.
           "question": _glance_question(t) if b["reason"] == "question" else None}
          for t, b in sessions.owner_blockers(tracks)]
    ny.sort(key=lambda c: (GLANCE_RANK.get(c["reason"], 9), c["id"]))
    yours = [{"id": t["id"], "task": (t.get("task") or "")[:70],
              "client": t.get("client", ""), "mode": b["mode"]}
             for t, b in sessions.manual_backlog(tracks)]
    return {
        # WHEN this was true. The glasses cache the last response and a webapp
        # on a battery display does not poll, so without a stamp there is no way
        # to tell a five-second-old "all clear" from a five-hour-old one - and a
        # stale all-clear is the exact failure this endpoint exists to prevent.
        "ts": int(time.time()),
        "needs_you": ny,
        "yours": yours,
        # the home screen's big number and the list are ONE derivation - they
        # cannot disagree the way a separately-counted total could
        "econ": {"needs_you": len(ny), "yours": len(yours),
                 "wip": m["capacity"]["wip"],
                 "wip_limit": m["capacity"]["wip_limit"],
                 "headroom": m["capacity"]["headroom"],
                 "margin": m["totals"]["margin"],
                 "currency": m["settings"].get("currency", "EUR")},
        "sows": [{"name": (s["name"] or "")[:40], "margin": s["margin"]}
                 for s in m.get("sows", [])[:5]]}
