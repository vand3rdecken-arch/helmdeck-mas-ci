# -*- coding: utf-8 -*-
"""Per-card dev port allocation - extracted from sessions.py (Paseo
PASEO_WORKTREE_PORT parity). A free port no OTHER card has claimed, persisted on
the track (tracks.json is durable; a worktree is regenerable). Depends only on
trackstore._load. sessions.py re-imports DEV_PORT_RANGE + _alloc_dev_port.
"""
from daemon.spine.trackstore import _load

DEV_PORT_RANGE = (3401, 3999)   # settings.json "dev_port_range": [lo, hi] overrides


def _alloc_dev_port(exclude_tid=None):
    """A free port no OTHER card has claimed (Paseo's range allocator: random
    start, scan the whole range wrapping around, skip reserved, bind-check
    each candidate). Returns None when the range is exhausted - the card still
    runs, it just gets no reserved port."""
    import socket, random
    from daemon.spine import events
    rng = events.settings().get("dev_port_range") or DEV_PORT_RANGE
    try:
        lo, hi = int(rng[0]), int(rng[1])
    except Exception:
        lo, hi = DEV_PORT_RANGE
    if lo > hi:
        lo, hi = hi, lo
    taken = {t.get("dev_port") for t in _load()
             if t.get("dev_port") and t.get("id") != exclude_tid}
    span = hi - lo + 1
    start = random.randrange(span)
    for i in range(span):
        port = lo + (start + i) % span
        if port in taken:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        finally:
            s.close()
        return port
    return None
