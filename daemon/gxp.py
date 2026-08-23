# -*- coding: utf-8 -*-
"""GxP mode - the switch that makes HelmDeck's review-free paths go away.

Read docs/gxp-mode-design.md first. The short version:

HelmDeck can land and DEPLOY a card with no human involved - Henry's `move`
verb, per-card fast-track, the policy auto-accept, machine cards. For a
regulated customer that single fact decides the supplier audit, so it has to be
switchable OFF, provably, in one place.

WHY THIS IS CODE AND NOT A POLICY FLAG
    policy.swap() guards capability_charter with `actor not in ("user","seed")`
    - an actor STRING supplied by the caller, not an authentication. Anything
    that can call swap() can claim to be a user. A `gxpMode: true` in
    policy_live.json would be exactly as strong as the agent's own honesty,
    which is the thing being controlled. So the switch lives in a file the
    control plane cannot write, and the enforcement lives in code.

WHY NOTHING IS CACHED
    Every accessor re-reads the file. No module global holding "we are in GxP
    mode", no value folded in at import. A stale copy of a security switch is
    the whole NO-MONKEY-PATCH failure mode: load-bearing state must be derived
    at the moment it is used, not remembered from boot. The file is a few
    hundred bytes and the read happens on lane transitions, not per request.

RESIDUAL RISK, STATED
    A machine card or direct task runs with a shell on this host and could
    delete gxp.lock. That is why the lock disables exactly those paths - but it
    only covers agents that start AFTER activation. The honest answer for an
    auditor is that the mode is activated at commissioning, before any agent
    runs, as part of the qualified installation (IQ). No software-only control
    stops an agent that already holds a shell; that is a property of the threat
    model, not a hole in this file.
"""
import json
import os

from daemon.paths import DAEMON_ROOT

LOCK = os.path.join(DAEMON_ROOT, "gxp.lock")

# Everything the mode can switch off. Names are matched by disabled(<name>).
FEATURES = ("fast_track", "machine", "direct_task", "auto_accept_green",
            "henry_move", "henry_did", "agent_may_swap")

# What a lock file with no explicit `disable` list turns off. The whole point of
# the mode is that these are gone, so the default is all of them - an operator
# who wants one back has to name the rest, deliberately.
_DEFAULT_DISABLE = FEATURES


def _read():
    """The lock file, or None. Never raises, never caches."""
    try:
        with open(LOCK, encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) and doc.get("enabled") else None
    except (OSError, ValueError):
        return None


def active():
    return _read() is not None


def disabled(feature):
    """Is `feature` switched off by the active mode? False when mode is off."""
    doc = _read()
    if not doc:
        return False
    return feature in (doc.get("disable") or _DEFAULT_DISABLE)


def four_eyes():
    """Must the approver be someone other than the dispatcher? Off by default:
    a one-person shop cannot satisfy it and must not be locked out of the mode
    (docs/gxp-mode-design.md 2.6)."""
    doc = _read()
    return bool(doc and doc.get("four_eyes"))


def state():
    """Public description for the API/UI. Never leaks the file's other fields."""
    doc = _read()
    if not doc:
        return {"active": False}
    return {"active": True,
            "activated_at": doc.get("activated_at"),
            "activated_by": doc.get("activated_by"),
            "four_eyes": bool(doc.get("four_eyes")),
            "disabled": sorted(doc.get("disable") or _DEFAULT_DISABLE)}


def is_human(actor):
    """Does `actor` name a real account?

    Derived from the user registry at the moment of the check, not from a list
    of known agent names - a hardcoded blocklist is wrong the day someone adds
    a cell. "henry", "policy", "pm", "chain" and "board-Agent (auto)" are not
    users and never will be; a person is.
    """
    if not actor:
        return False
    try:
        from daemon.spine.auth import auth
        return auth.get_user(actor) is not None
    except Exception:
        # Fail CLOSED: if the registry cannot be read we cannot prove a human,
        # and this function only ever gates things that need one.
        return False


def accept_block_reason(actor):
    """Why this actor may not land a card, or None if it may.

    The one question the lane machine asks. In GxP mode an accept has to be
    attributable to a real account; everything autonomous fails right here,
    without the lane machine needing to know which agents exist.
    """
    if not active():
        return None
    if not is_human(actor):
        return ("GxP mode: landing a card needs a human account - '%s' is not one"
                % (actor or "<none>"))
    return None
