# -*- coding: utf-8 -*-
"""GxP mode - the switch that makes HelmDeck's review-free paths go away.

Read docs/gxp-mode-design.md first. The short version:

HelmDeck can land and DEPLOY a card with no human involved - Henry's `move`
verb, per-card fast-track, the policy auto-accept, machine cards. For a
regulated customer that single fact decides the supplier audit, so it has to be
switchable OFF, provably, in one place.

SCOPE IS PER REPO, NOT GLOBAL AND NOT PER CARD (owner call, and he was right)
    A global kill switch that takes fast-track away everywhere is the kind of
    control that gets switched back off after two weeks, because most work is
    not regulated. So scope is narrow: only cards aimed at a listed repo need a
    signature, and every other repo is untouched - fast-track included.

    But it cannot be a per-CARD mood either, and this is the part that is easy
    to get wrong. Two cards in the same repo share one `main` and one deploy
    hook. If card X is signed and card Y is not, Y's unsigned change lands in
    the validated product and Y's own fast-track ships it - so the signature on
    X proves nothing about what was actually released. Scope has to follow the
    ARTEFACT, and in HelmDeck the artefact boundary is the repo.

    The card flag survives as an ADDITIVE override: `gxp: true` pulls a single
    card into scope (it touches the regulated thing from somewhere else). It
    can never push one out. Scope only ever grows.

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


def _norm(path):
    """Compare repo paths the way the filesystem does. Windows: case-insensitive
    and backslash/forward-slash equivalent, so a lock file written by hand
    matches a card dispatched by the daemon."""
    if not path:
        return ""
    return os.path.normcase(os.path.abspath(str(path)))


def in_scope(track):
    """Does THIS card need a signature?

    True when the card's repo is listed, or the card carries `gxp: true`.
    A missing/None `repos` list means the whole workspace is in scope - the
    strict setup, for an instance that only ever does regulated work.

    Note what is deliberately absent: there is no way for this to return False
    for a card whose repo IS listed. The card flag adds, never subtracts (see
    the module docstring) - otherwise anything that can edit a card can walk it
    out of the regulated system.
    """
    doc = _read()
    if not doc:
        return False
    if (track or {}).get("gxp"):
        return True
    repos = doc.get("repos")
    if repos is None:
        return True
    return _norm((track or {}).get("repo")) in {_norm(r) for r in repos}


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
    repos = doc.get("repos")
    return {"active": True,
            "activated_at": doc.get("activated_at"),
            "activated_by": doc.get("activated_by"),
            "four_eyes": bool(doc.get("four_eyes")),
            "scope": "workspace" if repos is None else "repos",
            "repos": list(repos or []),
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


def accept_block_reason(actor, track=None):
    """Why this actor may not land THIS card, or None if it may.

    The one question the lane machine asks. For a card in scope an accept has
    to be attributable to a real account; everything autonomous fails right
    here, without the lane machine needing to know which agents exist. A card
    out of scope is not this function's business and never blocked.
    """
    if not in_scope(track):
        return None
    if not is_human(actor):
        return ("GxP mode: landing a card in the regulated scope needs a human "
                "account - '%s' is not one" % (actor or "<none>"))
    return None
