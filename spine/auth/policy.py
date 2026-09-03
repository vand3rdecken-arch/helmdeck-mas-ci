# -*- coding: utf-8 -*-
"""Policy control plane — the daemon half of the full-dynamism decree.

The seeded rules (PolicySet + charter instructions) live in policy_seed.json as
the ONE canonical source both this daemon and the TS app kernel read (the app
hydrates via GET /policy; boot/policies.ts + boot/charter.ts hold the same seed
values today and become fetch-on-boot).

The decree's only floor is TRACKABILITY: there is no mutation path here that does
not append to the append-only events sink. `swap()` is the single writer; it
records op/actor/before/after into events.jsonl (via events.emit) and returns the
previous value so every change is reversible.

Two charters, deliberately kept apart:
  - `charter`            : agent instructions (CLAUDE.md), swappable like policy.
  - `capability_charter` : the connector SANDBOX (daemon/charter.py). A security
                           boundary. Represented for trackability but its swap is
                           human-only (capabilitySwapRequiresHuman, default True);
                           agentMaySwap does NOT unlock it.
"""
import json
import os
import threading

from daemon.paths import DAEMON_ROOT as HERE
SEED = os.path.join(HERE, "policy_seed.json")   # tracked file, the code default
LIVE = os.path.join(HERE, "policy_live.json")   # PRE-db era only, see load()

_LOCK = threading.RLock()  # reentrant: swap() holds it and calls load()


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _seed():
    return _read(SEED)


def _backfill_new_seed_keys(doc):
    """Add any key a LATER code change put into policy_seed.json but this
    doc's row predates - never touch a key already present (a value the
    owner explicitly set or explicitly left at a prior default is real
    state, not a gap). Mutates `doc` in place; returns True if anything
    changed.

    Found 2026-09-03 the hard way: `load()` returned db.policy_doc_get()'s
    row completely as-is once it existed, so buildLoopEnabled/copilotEnabled/
    engineerEnabled/permissions/sod_accept - every seed key ADDED after this
    workspace's very first boot - were silently ABSENT from every /policy
    response forever, not merely defaulted. Python readers happened to
    default the ones they read via `.get(key, True)`, but the app's
    Modules & Rules screen reads `policies?.buildLoopEnabled` directly and
    has no such fallback - a genuinely missing key rendered as an
    unexplained OFF toggle, and permissions.matrix() (same bug class, fixed
    separately) 403'd the owner on brand-new capabilities. Same rollout
    seam as _ROLLOUT_CAPS in spine/auth/permissions.py, one layer up: this
    is the general form, that was the special case for the permissions
    sub-key specifically."""
    seed = _seed()
    healed = False
    for section in ("policies", "charter", "capability_charter"):
        seed_section = seed.get(section) or {}
        if not seed_section:
            continue
        live_section = doc.setdefault(section, {})
        for k, v in seed_section.items():
            if k not in live_section:
                live_section[k] = v
                healed = True
    return healed


def load():
    """Current composed policy doc. Backed by db.policy_doc (config-
    consolidation phase 3) - `LIVE` above is no longer written; it is read
    ONCE, as a migration source, if a pre-db install's file is still there
    and the db row does not exist yet (the file is never deleted, only left
    behind - the db becomes the one source of truth going forward).

    Seeds from SEED on first run so the seed file itself is never mutated in
    place (seed = defaults, live = state)."""
    with _LOCK:
        from spine.storage import db
        doc = db.policy_doc_get()
        if doc is not None:
            if _backfill_new_seed_keys(doc):
                db.policy_doc_put(doc)
                print("policy: backfilled new seed key(s) into the stored doc")
            return doc
        # BELT+SUSPENDERS (same shape as db._migrate()'s ROOT/DBPATH guard):
        # LIVE binds to daemon.paths.DAEMON_ROOT at THIS module's import time,
        # independent of db.ROOT/DBPATH - a sandbox that repoints only the
        # latter (or forgets to patch LIVE itself) would otherwise migrate a
        # REAL leftover policy_live.json into an isolated db (measured
        # 2026-09-03: a test read back the machine's real wipLimit instead of
        # the seed's). Only trust LIVE as a migration source when it sits
        # next to the db this call is actually writing to.
        live_is_local = (os.path.dirname(os.path.abspath(LIVE))
                         == os.path.dirname(os.path.abspath(db.DBPATH)))
        if live_is_local and os.path.exists(LIVE):
            doc = _read(LIVE)          # migrate a pre-db install's file once
        else:
            doc = _seed()
            # wipLimit has an existing owner (settings.capacity.wip_limit). Seed
            # FROM it so the policy plane never diverges from the live board on
            # first run; after that a tracked swap() owns the value.
            try:
                from spine.storage import events
                sw = events.settings().get("capacity", {}).get("wip_limit")
                if isinstance(sw, int):
                    doc.setdefault("policies", {})["wipLimit"] = sw
            except Exception:
                pass
        db.policy_doc_put(doc)
        return doc


def get_policies():
    return load().get("policies", {})


def get_charter():
    return load().get("charter", {})


def get_capability_charter():
    return load().get("capability_charter", {})


class PolicyDenied(Exception):
    pass


def swap(section, patch, actor="system", note=None):
    """The ONLY mutation path. Apply `patch` (a dict) onto `section`
    ("policies" | "charter" | "capability_charter"), append a tracked
    reconfiguration event to the append-only sink, and return the PREVIOUS
    section value (the reversibility handle).

    Authority: an agent-initiated policy/charter swap needs agentMaySwap=True.
    A capability_charter swap is human-only while capabilitySwapRequiresHuman
    (default True) — agentMaySwap never unlocks the sandbox.
    """
    with _LOCK:
        doc = load()
        pols = doc.get("policies", {})

        if section == "capability_charter":
            cap = doc.get("capability_charter", {})
            if cap.get("capabilitySwapRequiresHuman", True) and actor not in ("user", "seed"):
                raise PolicyDenied("capability_charter swap is human-only")
        elif actor == "agent" and not pols.get("agentMaySwap", False):
            raise PolicyDenied("agentMaySwap is false; agent swap needs a human confirm")

        before = dict(doc.get(section, {}))
        after = dict(before)
        after.update(patch)
        doc[section] = after
        doc["version"] = int(doc.get("version", 1)) + 1
        from spine.storage import db
        db.policy_doc_put(doc)

        _mirror(op="swap", section=section, actor=actor, before=before, after=after, note=note)
        return before


def _mirror(**fields):
    """Append the reconfiguration to the real append-only audit. Best-effort on
    the db write-through (same contract as events.emit), durable in events.jsonl."""
    try:
        from spine.storage import events
        events.emit("reconfig", "-", **fields)
    except Exception:
        # never let an audit-sink hiccup swallow the fact of the change; the
        # LIVE file write already happened and is itself the durable state.
        pass


def revert(section, before, actor="system", note="revert"):
    """Restore a section to a prior value (the `before` swap() returned). Itself
    a tracked swap — reverting is also recorded, never silent."""
    return swap(section, before, actor=actor, note=note)
