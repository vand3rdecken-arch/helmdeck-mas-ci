# -*- coding: utf-8 -*-
"""MEMWATCH - where does the daemon's memory go?

Measured 2026-10-15: a fresh daemon starts at ~155 MB private and sits at
~1,055 MB after 18.7 h (~50 MB/h) even after the timeline-cache and SQLite
page-cache fixes. `/tracks` was ruled out (7 MB, flat under 24 concurrent
calls). Guessing further is what already cost two rounds, so the daemon now
reports on itself:

  * every SAMPLE_EVERY seconds one `mem` event (the existing append-only event
    log - no new table, no new config): private/working-set size, threads,
    live-object count;
  * for the first TRACE_HOURS (2) after boot, tracemalloc (1 frame) as well: the
    event names the code LINES that hold the most memory and the lines that
    GREW since a baseline taken BASELINE_AFTER seconds after boot. A type
    histogram ("dict +50k") cannot say that; an allocation site can;
  * then tracemalloc stops by itself. Its cost ends with the diagnosis, the
    cheap sampling stays.

GET /admin/memory (owner) answers the same question on demand.

Read-only: nothing here changes daemon behaviour. When the cause is fixed,
drop the tracemalloc half (debt `memwatch-tracemalloc-window`)."""
import ctypes
import gc
import os
import threading
import time
import tracemalloc
from ctypes import wintypes

from daemon.paths import REPO_ROOT

SAMPLE_EVERY = 600          # seconds between `mem` events
BASELINE_AFTER = 300        # tracemalloc baseline this long after boot
TRACE_HOURS = 2             # measured cost: allocation-heavy paths run ~2.8x slower while tracing, so keep it short; 2 h x ~50 MB/h shows the leader
TOP_N = 8

_started = 0.0
_baseline = None
_baseline_at = 0.0
_lock = threading.Lock()
_t = None


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def process_memory():
    """(private_mb, working_set_mb) of THIS process, or (None, None). ctypes,
    not psutil: the daemon's own interpreter does not ship psutil."""
    if os.name != "nt":
        return None, None
    try:
        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return None, None
        return pmc.PrivateUsage / 1e6, pmc.WorkingSetSize / 1e6
    except Exception:                                    # noqa: BLE001
        return None, None


def _short(path):
    try:
        return os.path.relpath(path, REPO_ROOT).replace("\\", "/")
    except ValueError:
        return os.path.basename(path)


def _site(stat):
    fr = stat.traceback[0]
    return "%s:%d" % (_short(fr.filename), fr.lineno)


def tracing():
    return tracemalloc.is_tracing()


def _grew(limit=TOP_N):
    """Allocation sites that grew since the baseline: [(site, +KiB, now KiB, blocks)]."""
    if not tracemalloc.is_tracing() or _baseline is None:
        return []
    snap = tracemalloc.take_snapshot().filter_traces((tracemalloc.Filter(False, tracemalloc.__file__),))
    out = []
    for d in snap.compare_to(_baseline, "lineno")[:limit]:
        out.append((_site(d), d.size_diff / 1024.0, d.size / 1024.0, d.count))
    return out


def _holding(limit=TOP_N):
    if not tracemalloc.is_tracing():
        return []
    snap = tracemalloc.take_snapshot().filter_traces((tracemalloc.Filter(False, tracemalloc.__file__),))
    return [(_site(s), s.size / 1024.0, s.count) for s in snap.statistics("lineno")[:limit]]


def report(top=15):
    """The on-demand answer (GET /admin/memory)."""
    priv, ws = process_memory()
    with _lock:
        up = time.time() - _started if _started else None
        return {
            "private_mb": priv, "working_set_mb": ws,
            "uptime_s": up, "threads": threading.active_count(),
            "gc_objects": len(gc.get_objects()),
            "tracing": tracing(), "baseline_age_s": (time.time() - _baseline_at) if _baseline else None,
            "grew_since_baseline_kib": [{"site": s, "plus_kib": round(d, 1), "now_kib": round(n, 1), "blocks": c}
                                        for s, d, n, c in _grew(top)],
            "holding_most_kib": [{"site": s, "kib": round(k, 1), "blocks": c} for s, k, c in _holding(top)],
        }


def _line(priv, ws):
    parts = ["private %s MB, working set %s MB, %d threads, %d objects" % (
        ("%.0f" % priv) if priv else "?", ("%.0f" % ws) if ws else "?",
        threading.active_count(), len(gc.get_objects()))]
    grew = _grew()
    if grew:
        parts.append("GREW: " + "; ".join("%s %+.0f KiB (now %.0f, %d blocks)" % g for g in grew))
        parts.append("HOLDS: " + "; ".join("%s %.0f KiB" % (s, k) for s, k, _c in _holding(5)))
    elif tracing():
        parts.append("tracing, baseline not taken yet")
    else:
        parts.append("tracemalloc window over")
    return " | ".join(parts)


def sample():
    """One `mem` event. Never raises into the daemon."""
    global _baseline, _baseline_at
    try:
        now = time.time()
        if tracing() and _baseline is None and now - _started >= BASELINE_AFTER:
            _baseline = tracemalloc.take_snapshot().filter_traces((tracemalloc.Filter(False, tracemalloc.__file__),))
            _baseline_at = now
        if tracing() and now - _started >= TRACE_HOURS * 3600:
            tracemalloc.stop()                      # the diagnosis window is over: the cost ends here
            _baseline = None
        priv, ws = process_memory()
        from spine.storage import events
        events.log("mem", _line(priv, ws))
    except Exception as e:                          # noqa: BLE001
        print("memwatch error:", e)


def start(every=None, trace=True):
    """Idempotent. Starts tracemalloc (1 frame) for the diagnosis window and the
    sampling loop. `trace=False` keeps only the cheap sampling."""
    global _started, _t
    if _t is not None:
        return
    _started = time.time()
    if trace and not tracemalloc.is_tracing():
        tracemalloc.start(1)
    iv = SAMPLE_EVERY if every is None else every

    def loop():
        time.sleep(min(BASELINE_AFTER + 5, iv))     # first event after the baseline exists
        while True:
            sample()
            time.sleep(iv)

    _t = threading.Thread(target=loop, daemon=True, name="memwatch")
    _t.start()
