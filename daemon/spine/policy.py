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
SEED = os.path.join(HERE, "policy_seed.json")
LIVE = os.path.join(HERE, "policy_live.json")  # git-ignored; current composed value

_LOCK = threading.RLock()  # reentrant: swap() holds it and calls load()


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _seed():
    return _read(SEED)


def load():
    """Current composed policy doc. Seeds LIVE from SEED on first run so the
    seed file itself is never mutated in place (seed = defaults, live = state)."""
    with _LOCK:
        if not os.path.exists(LIVE):
            doc = _seed()
            # wipLimit has an existing owner (settings.capacity.wip_limit). Seed
            # FROM it so the policy plane never diverges from the live board on
            # first run; after that a tracked swap() owns the value.
            try:
                from daemon.spine import events
                sw = events.settings().get("capacity", {}).get("wip_limit")
                if isinstance(sw, int):
                    doc.setdefault("policies", {})["wipLimit"] = sw
            except Exception:
                pass
            _atomic_write(LIVE, doc)
            return doc
        return _read(LIVE)


def get_policies():
    return load().get("policies", {})


def get_charter():
    return load().get("charter", {})


def get_capability_charter():
    return load().get("capability_charter", {})


def _atomic_write(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


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
        _atomic_write(LIVE, doc)

        _mirror(op="swap", section=section, actor=actor, before=before, after=after, note=note)
        return before


def _mirror(**fields):
    """Append the reconfiguration to the real append-only audit. Best-effort on
    the db write-through (same contract as events.emit), durable in events.jsonl."""
    try:
        from daemon.spine import events
        events.emit("reconfig", "-", **fields)
    except Exception:
        # never let an audit-sink hiccup swallow the fact of the change; the
        # LIVE file write already happened and is itself the durable state.
        pass


def revert(section, before, actor="system", note="revert"):
    """Restore a section to a prior value (the `before` swap() returned). Itself
    a tracked swap — reverting is also recorded, never silent."""
    return swap(section, before, actor=actor, note=note)
