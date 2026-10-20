# -*- coding: utf-8 -*-
"""Is THIS process (pid + creation time) still the one we started? ctypes only,
no psutil (the daemon's interpreter has none - see resources.py). The creation
time is what makes a recycled PID read as "gone" instead of "still running"."""
import ctypes
import os
from ctypes import wintypes

_QUERY_LIMITED = 0x1000
_STILL_ACTIVE = 259


def create_time(pid):
    """Process creation time as a FILETIME int, or None if no such process."""
    if os.name != "nt":
        return None
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(_QUERY_LIMITED, False, int(pid))
    if not h:
        return None
    try:
        c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
        if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                 ctypes.byref(kt), ctypes.byref(ut)):
            return None
        code = wintypes.DWORD()
        if k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != _STILL_ACTIVE:
            return None
        return (c.dwHighDateTime << 32) | c.dwLowDateTime
    finally:
        k.CloseHandle(h)


def alive(pid, ctime):
    """True only while pid exists AND was created at ctime."""
    return ctime is not None and create_time(pid) == ctime


def exists(pid):
    """Is there a live process with this pid? The ONE liveness probe for a pid
    read from a lock file. NEVER os.kill(pid, 0) on Windows: CPython maps every
    signal but CTRL_C/CTRL_BREAK to TerminateProcess, so the "probe" KILLS a
    foreign process and then raises SystemError (measured 2026-10-20: Henry's
    ship.lock line and an analysis session both took the live daemon down)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        return create_time(pid) is not None
    try:
        os.kill(pid, 0)                 # POSIX: signal 0 really is a probe
        return True
    except PermissionError:
        return True                     # exists, owned by someone else
    except OSError:
        return False
