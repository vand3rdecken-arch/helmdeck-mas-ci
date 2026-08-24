# -*- coding: utf-8 -*-
"""Electronic signatures on a card acceptance (21 CFR 11.50 / 11.70).

Read docs/gxp-mode-design.md 2.0-2.2. The parts that matter here:

WHAT IS SIGNED IS A PAIR OF COMMIT IDS, not a checksum we invented.
    git already content-addresses everything, so the subject of a signature is
    (head of the card branch, base of main). head covers the entire change;
    base records what it was integrated against. An auditor can walk both with
    stock git and needs no tool from us.

THE SIGNATURE IS A PRECONDITION, NOT A DIALOG.
    Nothing here accepts a card. This module produces a record; the lane
    machine refuses to land an in-scope card unless a valid, unconsumed one
    exists. That is why the control cannot be bypassed by a caller that simply
    does not ask - there is nothing to ask.

DRIFT VOIDS IT, AND THAT IS THE POINT.
    The recorded head/base are re-checked at accept time. If the agent
    committed again, or main moved, what would land is not what was reviewed,
    so the signature no longer applies. "You signed what you saw" is the whole
    claim, and re-signing is cheap.

    Consequence worth knowing: a card must be COMMITTED before it can be
    signed. _move_lane's _autocommit would otherwise create a commit during the
    accept and void the signature it just checked. Refusing to sign a dirty
    card is the honest version of that - the alternative is signing a state
    that does not exist yet.

NOT YET HERE: the signed git tag (owner deferred the signing-key decision).
    Without it the record is ours to vouch for rather than independently
    verifiable, which is exactly the difference between 11.50 (met) and the
    full strength of 11.70 (bound, but on our word). Debt
    gxp-mode-has-no-signature-yet tracks the remainder.
"""
import time

from spine.git.gitutil import _git_try

# 11.50(a)(3): a signature has to carry its MEANING. These are the three the
# design settled on; "reviewed" is what makes a two-person flow possible
# (A reviews, B approves) without inventing a second mechanism.
MEANINGS = ("approved", "reviewed", "rejected")


def _now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def subject(t):
    """What signing THIS card would commit to, or (None, reason).

    Returns a dict describing the exact state a signer is looking at. Refuses
    when the card is not in a signable state at all, and says why in words a
    person can act on.
    """
    repo, branch, wt = t.get("repo"), t.get("branch"), t.get("worktree")
    if not repo or not branch:
        return None, "card has no repo/branch to sign"
    rc, head, err = _git_try(repo, "rev-parse", branch)
    if rc != 0:
        return None, "cannot read the card branch: %s" % err
    rc, base, err = _git_try(repo, "rev-parse", "HEAD")
    if rc != 0:
        return None, "cannot read the base branch: %s" % err
    if wt:
        rc, dirty, _ = _git_try(wt, "status", "--porcelain")
        if rc == 0 and dirty.strip():
            return None, ("the card has %d uncommitted change(s) - a signature "
                          "must name a commit that exists, so finish or commit "
                          "the work first" % len(dirty.splitlines()))
    stat = _git_try(repo, "diff", "--shortstat", "%s...%s" % (base, branch))[1]
    files = _git_try(repo, "diff", "--name-only", "%s...%s" % (base, branch))[1]
    ahead = _git_try(repo, "rev-list", "--count", "%s..%s" % (base, branch))[1]
    return {"card": t.get("id"), "branch": branch, "head": head, "base": base,
            "commits": int(ahead or 0), "shortstat": stat,
            "files": [f for f in files.splitlines() if f][:200]}, None


def drift(t, sig):
    """Has what would land changed since it was signed? Reason string or None."""
    subj = sig.get("subject") or {}
    repo, branch = t.get("repo"), t.get("branch")
    if not repo or not branch:
        return "card lost its repo/branch since signing"
    head = _git_try(repo, "rev-parse", branch)[1]
    base = _git_try(repo, "rev-parse", "HEAD")[1]
    if head != subj.get("head"):
        return ("the card branch moved since it was signed (%s -> %s)"
                % (str(subj.get("head"))[:8], head[:8]))
    if base != subj.get("base"):
        return ("the base branch moved since it was signed (%s -> %s) - the "
                "integration is no longer the one that was reviewed"
                % (str(subj.get("base"))[:8], base[:8]))
    return None


def create(t, actor, actor_role, meaning, reason, subj):
    """Build the immutable record. Caller has already re-authenticated."""
    if meaning not in MEANINGS:
        raise ValueError("meaning must be one of %s" % (MEANINGS,))
    if meaning == "rejected" and not (reason or "").strip():
        raise ValueError("a rejection has to say why")
    prior = list(t.get("signatures") or [])
    return {
        "seq": len(prior) + 1,
        "actor": actor,                  # 11.50(a)(1) printed name
        "actor_role": actor_role,
        "meaning": meaning,              # 11.50(a)(3)
        "reason": (reason or "").strip(),
        "signed_at": _now_utc(),         # 11.50(a)(2), UTC not host-local
        "subject": subj,                 # 11.70 binding: the commit pair
        "auth": {"method": "password", "components": ["userid", "password"]},
        "git": {"tag": None, "tag_sha": None, "merge_sha": None},
        "consumed_by": None,
    }


def valid_open(t):
    """The signature that authorises landing this card right now, or None.

    'approved', not yet consumed, and still describing what would land.
    Deliberately re-derived from the record + git on every call rather than
    cached on the card: a stored "is approved" boolean is exactly the kind of
    remembered state that goes stale the moment the branch moves.
    """
    for sig in reversed(t.get("signatures") or []):
        if sig.get("meaning") != "approved" or sig.get("consumed_by"):
            continue
        if drift(t, sig):
            continue
        return sig
    return None


def four_eyes_violation(t, sig):
    """Same person filed and approved it? Reason string or None."""
    dispatcher = t.get("dispatched_by")
    if dispatcher and dispatcher == sig.get("actor"):
        return ("four-eyes: '%s' dispatched this card and cannot also approve it"
                % dispatcher)
    return None
