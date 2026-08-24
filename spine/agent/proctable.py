# -*- coding: utf-8 -*-
"""Process table + PID lifecycle - extracted from drivers.py. A ctypes
Toolhelp32 process table, tree-kill (snapshot descendants BEFORE killing),
the driver_pids.json record (pid -> spawn epoch) and the pid-reuse-safe
identity check, plus reap_orphans (kill a previous daemon's leftover trees
at startup). Self-contained (its own _pid_lock + _PIDFILE); drivers.py
re-imports the names. The test suite patches drivers._tree_kill/_record_pid/
_forget_pid - unchanged, because their real callers stay in drivers.py.
"""
import json
import os
import subprocess
import threading


def _pid_table():
    """[(pid, ppid, exe)] for every live process (Windows), via a ctypes
    Toolhelp32 snapshot - no subprocess, no PATH dependency (PowerShell is NOT
    guaranteed to be on PATH: this very dev box lacks it), and the only reliable
    way to know a tree BEFORE we start killing it."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)     # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        return []
    out = []
    try:
        e = PROCESSENTRY32()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = k32.Process32First(snap, ctypes.byref(e))
        while ok:
            out.append((int(e.th32ProcessID), int(e.th32ParentProcessID),
                        e.szExeFile.decode("mbcs", "replace")))
            ok = k32.Process32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def _descendants(pid):
    """All live descendant pids of `pid`, snapshotted BEFORE the kill. taskkill
    /T walks the tree at kill time - if the parent died first (polite pass), it
    can no longer see the children, which is exactly how MCP/node orphans leak."""
    try:
        table = _pid_table()
    except Exception:
        return []
    kids = {}
    for p, pp, _exe in table:
        kids.setdefault(pp, []).append(p)
    out, stack, seen = [], [pid], {pid}
    while stack:
        for c in kids.get(stack.pop(), []):
            if c not in seen:
                seen.add(c)
                out.append(c)
                stack.append(c)
    return out


def _tree_kill(proc, grace=2.0):
    """Take the whole process tree down, escalating (Paseo tree-kill parity):
    polite signal -> grace -> force -> CONFIRM the descendants are gone. `proc`
    is the `cmd /c claude` wrapper, so terminate() alone leaves the real
    claude/node child (and its MCP children) running. The polite pass gives
    claude a chance to flush its session .jsonl; the confirm pass reaps MCP
    orphans whose parent died first (invisible to taskkill /T by then)."""
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            _forget_pid(proc.pid)
            return
    except Exception:
        pass
    pid = proc.pid
    try:
        if os.name == "nt":
            family = _descendants(pid)                      # snapshot BEFORE killing
            subprocess.run(["taskkill", "/T", "/PID", str(pid)],   # polite (WM_CLOSE)
                           capture_output=True, timeout=10)
            try:
                proc.wait(timeout=grace)
            except Exception:
                pass
            if proc.poll() is None:                          # ignored -> force
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=10)
            # confirm: reap surviving descendants one by one. Guarded by the
            # image check so a recycled pid can never hit an innocent process.
            try:
                alive = {p for p, _pp, _exe in _pid_table()}
            except Exception:
                alive = set()
            for cp in family:
                if cp in alive and _is_agent_pid(cp):
                    subprocess.run(["taskkill", "/F", "/PID", str(cp)],
                                   capture_output=True, timeout=10)
        else:
            proc.terminate()                                 # SIGTERM
            try:
                proc.wait(timeout=grace)
            except Exception:
                proc.kill()                                  # SIGKILL
        try:
            proc.wait(timeout=5)                             # confirm the wrapper died
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    _forget_pid(pid)


from daemon.paths import DAEMON_ROOT as _DAEMON_ROOT
_PIDFILE = os.path.join(_DAEMON_ROOT, "driver_pids.json")
_pid_lock = threading.Lock()


def _read_pids():
    """driver_pids.json maps "<pid>" -> spawn epoch. Tolerates the legacy plain
    list format (no timestamps) by converting it to timestamp-less entries."""
    try:
        with open(_PIDFILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, list):
        return {str(p): None for p in data}
    return {str(k): v for k, v in (data or {}).items()}


def _write_pids(pids):
    try:
        tmp = _PIDFILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pids, f)
        os.replace(tmp, _PIDFILE)
    except Exception:
        pass


def _record_pid(pid, spawn_time=None):
    with _pid_lock:
        pids = _read_pids()
        pids[str(pid)] = spawn_time
        _write_pids(pids)


def _forget_pid(pid):
    with _pid_lock:
        pids = _read_pids()
        if pids.pop(str(pid), "absent") != "absent":
            _write_pids(pids)


def _proc_start_epoch(pid):
    """OS-reported start time (UTC epoch seconds) of a live pid, or None.
    ctypes GetProcessTimes, not PowerShell: powershell.exe is not guaranteed on
    PATH (this dev box lacks it), and a silently-failing subprocess here would
    degrade the pid-reuse guard to the weaker image check without anyone noticing."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            created, exited, kern, user = (wintypes.FILETIME(), wintypes.FILETIME(),
                                           wintypes.FILETIME(), wintypes.FILETIME())
            if not k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                       ctypes.byref(kern), ctypes.byref(user)):
                return None
            t100 = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return t100 / 1e7 - 11644473600.0          # FILETIME (1601) -> epoch (1970)
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


# SUBSTRING-safe image names: long/distinctive enough that a false positive
# (some unrelated process whose filename happens to CONTAIN one of these) is
# implausible. "codex"/"opencode" added for their own native drivers
# (docs/multi-engine-build-plan.md Cards 6/7) - unverified against real
# binaries, but the image names themselves are exactly the CLI binary names
# those drivers spawn, not a guess.
_AGENT_IMG_SUBSTR = ("claude", "node", "cmd", "codex", "opencode")
# EXACT-basename-only image names: too short/common to trust as a substring.
# "omp" would match "compress.exe"/"compact.exe" (contain "omp"); "pi" would
# match "pip.exe" - a near-universal process on any dev machine - as a
# substring, which would have made reap_orphans/tree-kill treat a random pip
# install as an agent process. Caught reviewing this same change (Cards 6-8),
# not shipped - but the ALREADY-SHIPPED "omp" entry (Card 8) had the exact
# same latent bug and is fixed here too, not left for later.
_AGENT_IMG_EXACT = ("omp.exe", "omp", "pi.exe", "pi")


def _is_agent_pid(pid):
    """Weaker fallback guard: the pid is still a known agent-driver image."""
    if os.name != "nt":
        return True
    try:
        for p, _pp, exe in _pid_table():
            if p == pid:
                img = (exe or "").lower()
                return (any(n in img for n in _AGENT_IMG_SUBSTR)
                        or img in _AGENT_IMG_EXACT)
        return False
    except Exception:
        return False


def _is_ours(pid, spawn_time):
    """Pid-reuse-safe identity check. If we recorded a spawn time AND the OS can
    report this pid's start time, require them to MATCH (a recycled pid would show
    a later start time). Only when the start time is unavailable do we fall back
    to the weaker claude/node/cmd image guard."""
    started = _proc_start_epoch(pid)
    if started is not None and spawn_time:
        return abs(started - float(spawn_time)) <= 6.0
    return _is_agent_pid(pid)


def reap_orphans():
    """On daemon start, tree-kill driver processes left running by a PREVIOUS
    daemon (crash/restart) so orphaned claude+MCP trees don't accumulate. Only
    PIDs WE recorded (and that pass the pid-reuse identity check) are touched -
    never a blanket claude.exe kill that would hit the desktop's own session."""
    with _pid_lock:
        rec = _read_pids()
        _write_pids({})
    killed = 0
    for pid_s, spawn in rec.items():
        try:
            pid = int(pid_s)
            if not _is_ours(pid, spawn):
                continue
            if os.name == "nt":
                r = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   capture_output=True, timeout=10)
                if r.returncode == 0:
                    killed += 1
            else:
                os.kill(pid, 9)
                killed += 1
        except Exception:
            pass
    return killed
