# -*- coding: utf-8 -*-
"""OBSERVED system load - the seam load-aware admission (lanemachine._admit_heavy)
reads before starting a heavy op. ctypes only, no psutil: the daemon's actual
interpreter (py -3.12, per CLAUDE.md) does not have it vendored, so a dependency
on it would be an untested code path in production. Never shells to
powershell.exe (measured absent from this box's PATH - see memory
windows-mcp-cli-cold-start-timeout / paseo-architecture-learnings).

Windows-only measurement; a non-Windows box or a failed read returns None so a
caller can never block admission on a measurement it cannot trust - the same
fail-open shape as _repo_hook/_say_card ("never fail real work over a
diagnostic")."""
import ctypes
import os
import time


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


def _ft(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def cpu_percent(interval=0.2):
    """% CPU busy across ALL cores over `interval` seconds - the same idle vs
    kernel+user FILETIME delta Task Manager itself reads, no external process
    spawned. Returns None when unmeasurable (non-Windows, or the API call
    itself fails)."""
    if os.name != "nt":
        return None
    try:
        k32 = ctypes.windll.kernel32
        idle1, kernel1, user1 = _FILETIME(), _FILETIME(), _FILETIME()
        if not k32.GetSystemTimes(ctypes.byref(idle1), ctypes.byref(kernel1), ctypes.byref(user1)):
            return None
        time.sleep(max(0.05, interval))
        idle2, kernel2, user2 = _FILETIME(), _FILETIME(), _FILETIME()
        if not k32.GetSystemTimes(ctypes.byref(idle2), ctypes.byref(kernel2), ctypes.byref(user2)):
            return None
        idle_delta = _ft(idle2) - _ft(idle1)
        total_delta = (_ft(kernel2) - _ft(kernel1)) + (_ft(user2) - _ft(user1))
        if total_delta <= 0:
            return 0.0
        busy = total_delta - idle_delta
        return max(0.0, min(100.0, 100.0 * busy / total_delta))
    except Exception:
        return None


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def free_ram_mb():
    """Free physical RAM in MB, or None if unmeasurable (see cpu_percent)."""
    if os.name != "nt":
        return None
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        return stat.ullAvailPhys / (1024.0 * 1024.0)
    except Exception:
        return None


def sample(interval=0.2):
    """One observation of both signals, for callers that want to log/report
    RAM alongside the CPU threshold check without a second syscall round trip."""
    return {"cpu_pct": cpu_percent(interval), "free_ram_mb": free_ram_mb()}
