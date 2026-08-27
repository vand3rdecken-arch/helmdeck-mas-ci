# -*- coding: utf-8 -*-
"""Night shift dispatcher - processes._priority_dispatch. Policy is data:
backlog cards at/above the settings floor start themselves while WIP headroom
exists. Three behaviors under test:

  ranking  - eligible backlog sorted by priority, then due date ('9999' when
             none, so undated cards sort last within a priority)
  claiming - each dispatched card is moved to "working" by actor "chain" and
             a priority_dispatch event is emitted for the audit trail
  limit    - never dispatch past wip_limit headroom; floor unset/invalid
             means the policy is off entirely

Runs headless: fake `sessions`/`events` modules injected into sys.modules
(processes imports them lazily inside the function), and threads replaced
with synchronous calls so claim order is deterministic."""
import sys
import types

import processes


def card(tid, lane="backlog", priority="medium", due="", mode=None):
    c = {"id": tid, "lane": lane, "priority": priority, "due": due}
    if mode is not None:
        c["mode"] = mode
    return c


class _SyncThread:
    def __init__(self, target=None, args=(), daemon=False):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def dispatch(monkeypatch, tracks, floor="low", wip_limit=6):
    """Run one dispatcher pass over fixture tracks; return (claims, events)."""
    ev = types.ModuleType("events")
    ev.emitted = []
    ev.settings = lambda: {"policy": {"auto_dispatch_priority": floor},
                           "capacity": {"wip_limit": wip_limit}}
    ev.emit = lambda kind, ref, **kw: ev.emitted.append((kind, ref, kw))

    se = types.ModuleType("sessions")
    se.claimed = []
    se.list_tracks = lambda: tracks
    se.move_lane = lambda tid, lane, actor=None: se.claimed.append(
        (tid, lane, actor))

    monkeypatch.setitem(sys.modules, "events", ev)
    monkeypatch.setitem(sys.modules, "sessions", se)
    monkeypatch.setattr(processes, "threading",
                        types.SimpleNamespace(Thread=_SyncThread))
    processes._priority_dispatch()
    return se.claimed, ev.emitted


# --- ranking ---------------------------------------------------------------

def test_ranks_by_priority_then_due(monkeypatch):
    tracks = [card("t-med", priority="medium", due="2026-08-01"),
              card("t-low", priority="low"),
              card("t-high-late", priority="high", due="2026-08-02"),
              card("t-high-early", priority="high", due="2026-08-01"),
              card("t-urgent", priority="urgent")]
    claimed, _ = dispatch(monkeypatch, tracks, floor="low")
    assert [c[0] for c in claimed] == \
        ["t-urgent", "t-high-early", "t-high-late", "t-med", "t-low"]


def test_undated_card_sorts_after_dated_same_priority(monkeypatch):
    tracks = [card("t-undated", priority="high"),
              card("t-dated", priority="high", due="2026-08-01")]
    claimed, _ = dispatch(monkeypatch, tracks, floor="high")
    assert [c[0] for c in claimed] == ["t-dated", "t-undated"]


def test_floor_excludes_lower_priorities(monkeypatch):
    tracks = [card("t-urgent", priority="urgent"),
              card("t-high", priority="high"),
              card("t-med", priority="medium"),
              card("t-low", priority="low")]
    claimed, _ = dispatch(monkeypatch, tracks, floor="high")
    assert [c[0] for c in claimed] == ["t-urgent", "t-high"]


def test_only_backlog_cards_are_eligible(monkeypatch):
    tracks = [card("t-working", lane="working", priority="urgent"),
              card("t-done", lane="done", priority="urgent"),
              card("t-backlog", priority="urgent")]
    claimed, _ = dispatch(monkeypatch, tracks, floor="low")
    assert [c[0] for c in claimed] == ["t-backlog"]


def test_human_teach_cowork_modes_never_auto_start(monkeypatch):
    tracks = [card("t-human", priority="urgent", mode="human"),
              card("t-teach", priority="urgent", mode="teach"),
              card("t-cowork", priority="urgent", mode="cowork"),
              card("t-do", priority="urgent", mode="do")]
    claimed, _ = dispatch(monkeypatch, tracks, floor="low")
    assert [c[0] for c in claimed] == ["t-do"]


# --- claiming --------------------------------------------------------------

def test_claim_moves_to_working_as_chain_and_emits(monkeypatch):
    claimed, emitted = dispatch(monkeypatch, [card("t-1", priority="urgent")],
                                floor="urgent")
    assert claimed == [("t-1", "working", "chain")]
    assert emitted == [("process", "-",
                        {"action": "priority_dispatch", "card": "t-1"})]


def test_claim_failure_does_not_raise(monkeypatch):
    """A dead card must not kill the poller loop - _auto_dispatch swallows."""
    ev = types.ModuleType("events")
    ev.settings = lambda: {"policy": {"auto_dispatch_priority": "low"},
                           "capacity": {"wip_limit": 6}}
    ev.emit = lambda *a, **kw: None
    se = types.ModuleType("sessions")
    se.list_tracks = lambda: [card("t-gone", priority="urgent")]

    def boom(tid, lane, actor=None):
        raise RuntimeError("card vanished")
    se.move_lane = boom
    monkeypatch.setitem(sys.modules, "events", ev)
    monkeypatch.setitem(sys.modules, "sessions", se)
    monkeypatch.setattr(processes, "threading",
                        types.SimpleNamespace(Thread=_SyncThread))
    processes._priority_dispatch()   # must not raise


# --- limit gate ------------------------------------------------------------

def test_dispatch_capped_at_headroom(monkeypatch):
    tracks = [card("w-1", lane="working"), card("w-2", lane="working"),
              card("t-a", priority="urgent", due="2026-08-01"),
              card("t-b", priority="urgent", due="2026-08-02"),
              card("t-c", priority="urgent", due="2026-08-03")]
    claimed, _ = dispatch(monkeypatch, tracks, floor="low", wip_limit=3)
    assert [c[0] for c in claimed] == ["t-a"]   # headroom 1 -> best card only


def test_no_dispatch_at_wip_limit(monkeypatch):
    tracks = [card("w-1", lane="working"), card("w-2", lane="working"),
              card("t-a", priority="urgent")]
    claimed, emitted = dispatch(monkeypatch, tracks, floor="low", wip_limit=2)
    assert claimed == [] and emitted == []


def test_no_dispatch_over_wip_limit(monkeypatch):
    # limit lowered under live WIP -> negative headroom must not slice weird
    tracks = [card("w-%d" % i, lane="working") for i in range(3)] + \
             [card("t-a", priority="urgent")]
    claimed, _ = dispatch(monkeypatch, tracks, floor="low", wip_limit=2)
    assert claimed == []


def test_policy_off_when_floor_unset_or_invalid(monkeypatch):
    for floor in ("", None, "sometimes", "URGENT"):
        claimed, emitted = dispatch(
            monkeypatch, [card("t-a", priority="urgent")], floor=floor)
        assert claimed == [] and emitted == [], "floor=%r dispatched" % floor
