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
    import sessions
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
