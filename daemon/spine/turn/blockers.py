# -*- coding: utf-8 -*-
"""'What needs the owner' — the ONE derivation of whether a card is blocked on
the human and why, extracted from sessions.py. Pure over track dicts (blocker()
touches no process table or disk); owner_blockers() pairs it with
sessions.present() so a phantom `running` counts from the moment it is read.
Every surface reads these instead of re-deriving from `status` (which is exactly
what let the glasses/board/needs feeds drift). Not monkeypatched; sessions.py
re-imports the names so callers are unchanged.
"""


def _blocker_text(v, n=160):
    """One short SINGLE-LINE reason. Bounce reports arrive as a list of gate
    problems, as a paragraph, or not at all; a badge and a 600x600 glasses
    display can render exactly one line of it.

    Whitespace is COLLAPSED, not truncated at the first newline the way the
    card's compact `punch` is: a gate problem's first line is only the name of
    the check ("tests/test_x.py:") and the assertion that actually failed sits
    on the line below it. At a glance the second line is the whole point."""
    if isinstance(v, (list, tuple)):
        v = " | ".join(str(x) for x in v if x)
    return " ".join(str(v or "").split())[:n]


def blocker(t):
    """The ONE derivation of "nothing moves on this card until the OWNER acts",
    and WHY. Returns None when the card is nobody's move but the machine's -
    running, gating, queued, landed, archived, or waiting on its own background
    task - else {"reason": one of BLOCKER_REASONS, "detail": short text}.

    Every surface that answers "what needs me" reads this instead of re-deriving
    it from `status`, because re-deriving is exactly what let the surfaces
    drift: the glasses feed listed `needs_you` only, so a card held by a RED
    GATE, an open merge conflict, a failed dispatch or a swept zombie - every
    one of them stuck until the owner acts - showed up nowhere, and neither did
    a card resting on Review for an accept. Three surfaces, three different
    answers to one question.

    Pass the card through present() first when the answer must be live: a
    phantom `running` (its turn died) is the owner's move, and only present()
    knows that.

    The bounce REPORTS are read most-specific-first, which is sound because the
    writers keep exactly one current report on a bounced card - _gatefail pops
    merge_report, _mergefail and _markers pop gate_report.

    Where the line is drawn, deliberately: a card nobody has started is not
    BLOCKED, it is unstarted. A `queued` backlog card the PM will never dispatch
    on its own (mode human/teach/cowork, or a quota-paused day) is the owner's
    WORK, not his decision - it belongs on a board, and putting it here would
    bury the six cards that really are stuck under fifty that merely wait."""
    t = t or {}
    if t.get("archived"):
        return None
    s = t.get("status")
    if s == "submitted":
        return {"reason": "review", "detail": _blocker_text(t.get("review_report"))}
    if s == "bounced":
        if t.get("gate_report"):
            return {"reason": "gate", "detail": _blocker_text(t["gate_report"])}
        if t.get("merge_report"):
            return {"reason": "conflict" if t.get("merge_kind") == "conflict" else "failed",
                    "detail": _blocker_text(t["merge_report"])}
        # A bounce with no report of its own - the owner dragged it back, a
        # dispatch died, a turn was swept. If that card is ALSO holding an
        # unanswered question, the question is the actionable half and reporting
        # only "failed" would drop it: answering it is what unsticks the card.
        if not t.get("question"):
            return {"reason": "failed", "detail": _blocker_text(t.get("last_reply"))}
    elif s != "needs_you" or t.get("waiting_on") == "background":
        return None
    if t.get("question"):
        try:
            from daemon.spine.ops import ask
            detail = ask.summary(t["question"])
        except Exception:
            detail = ""            # a summary is never worth failing a read
        return {"reason": "question", "detail": _blocker_text(detail)}
    return {"reason": "delivered", "detail": _blocker_text(t.get("last_reply"))}


# Modes the machine STRUCTURALLY refuses to start: every auto-dispatch path
# excludes them (pm._backlog, pm._chain_ready, pm.activity's todo list,
# processes._advance), and teach/human get no driver at all (MODE_DRIVER). A
# `do` card in the backlog is waiting its TURN; one of these is waiting for a
# human, forever, and nothing anywhere used to say so.
MANUAL_MODES = ("human", "teach", "cowork")


def manual_backlog(tracks):
    """Un-started cards only the OWNER can ever start, as [(card, why)].

    Deliberately NOT part of blocker(): these are not stuck work, they are
    unstarted work, and merging them into "what is blocked on me" would bury a
    red gate under a backlog. They are their own bucket with their own count -
    complete information, in the right order of alarm.

    An ordinary `do` card in the backlog is absent on purpose: the PM will get
    to it. These it will never get to."""
    out = []
    for t in tracks or ():
        t = t or {}
        if t.get("archived") or t.get("status") != "queued":
            continue
        if t.get("mode") in MANUAL_MODES:
            out.append((t, {"reason": "yours", "mode": t.get("mode"),
                            "detail": _blocker_text(t.get("description")
                                                    or t.get("task"))}))
    return out


def owner_blockers(tracks):
    """THE surface entry point: every card on `tracks` that is blocked on the
    human, as a list of (card, blocker) - the card as PRESENTED, so a phantom
    `running` (its turn died) counts from the moment it is read rather than
    whenever the reconciler next runs.

    blocker() alone is deliberately pure - it decides from the fields it is
    handed and touches no process table or disk. Pairing it with present() is
    the half every surface would otherwise have to remember, and forgetting it
    is a silent gap: the card is stuck, its stored status says `running`, and
    nothing anywhere says the owner has to act."""
    from daemon.cells.engineer import sessions  # present() stays in sessions (lifecycle observation); lazy = no cycle
    out = []
    for t in tracks or ():
        t = sessions.present(t)
        b = blocker(t)
        if b:
            out.append((t, b))
    return out


def waits_for_owner(t):
    """True when the card wants something from the HUMAN right now - finished
    work to accept, a question to answer, or a bounce/red gate to unstick. A
    background wait is excluded: it is the one parked state that is nobody's
    move but the machine's. Thin predicate over owner_blockers(), so there is
    one derivation and not a second one drifting alongside it."""
    return bool(owner_blockers([t] if t else []))
