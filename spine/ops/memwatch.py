# -*- coding: utf-8 -*-
"""MEMWATCH - the daemon's own memory, on the record.

One `mem` event every SAMPLE_EVERY seconds in the existing append-only event log
(no new table, no new config): private size, working set, the PEAK working set
since process start, threads and live Python objects. GET /admin/memory (owner)
answers the same on demand.

Why the PEAK is in the line: a 10-minute raster cannot see a transient. The
tool-result prune used to load Henry's 374 MB session whole - +614 MB for two
seconds, eight times a day - and no sample ever caught it; the daemon looked
"flat" while it was not. The peak working set is the OS's own high-water mark, so
a spike between two samples still shows up as the peak jumping between two lines.
(Not reset after a read: the only way to reset it empties the working set, which
would page the whole daemon out every 10 minutes - too high a price for a number.)

History: this module also carried a 2 h tracemalloc window (2026-10-15) that
names the code lines that grow. It found the real picture - the Python heap was
~30 MB of a 250 MB process, i.e. the memory was native/transient, not a leaking
Python structure - and was removed again; tracing slowed allocation-heavy paths
~2.8x. Read-only: nothing here changes daemon behaviour."""
import ctypes
import gc
import os
import threading
import time
from ctypes import wintypes

SAMPLE_EVERY = 600          # seconds between `mem` events

_started = 0.0
_t = None


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def process_memory():
    """(private_mb, working_set_mb, peak_working_set_mb) of THIS process, or
    (None, None, None). ctypes, not psutil: the daemon's interpreter has none."""
    if os.name != "nt":
        return None, None, None
    try:
        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        h = k32.GetCurrentProcess()
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if not psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return None, None, None
        return pmc.PrivateUsage / 1e6, pmc.WorkingSetSize / 1e6, pmc.PeakWorkingSetSize / 1e6
    except Exception:                                    # noqa: BLE001
        return None, None, None


def report():
    """The on-demand answer (GET /admin/memory)."""
    priv, ws, peak = process_memory()
    return {"private_mb": priv, "working_set_mb": ws, "peak_working_set_mb": peak,
            "uptime_s": (time.time() - _started) if _started else None,
            "threads": threading.active_count(), "gc_objects": len(gc.get_objects())}


def _line(priv, ws, peak):
    f = lambda v: ("%.0f" % v) if v else "?"           # noqa: E731
    return "private %s MB, working set %s MB, peak %s MB, %d threads, %d objects" % (
        f(priv), f(ws), f(peak), threading.active_count(), len(gc.get_objects()))


def sample():
    """One `mem` event. Never raises into the daemon."""
    try:
        priv, ws, peak = process_memory()
        from spine.storage import events
        events.log("mem", _line(priv, ws, peak))
    except Exception as e:                              # noqa: BLE001
        print("memwatch error:", e)


def start(every=None):
    """Idempotent: the sampling loop, first event one interval after boot."""
    global _started, _t
    if _t is not None:
        return
    _started = time.time()
    iv = SAMPLE_EVERY if every is None else every

    def loop():
        while True:
            time.sleep(iv)
            sample()

    _t = threading.Thread(target=loop, daemon=True, name="memwatch")
    _t.start()
