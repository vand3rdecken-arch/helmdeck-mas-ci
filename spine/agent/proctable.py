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


# -- process ownership: a Windows Job Object per spawn ------------------------
# WHY. Windows has no reparenting and no process groups: the moment an
# intermediate process dies, everything below it is unreachable by parent
# links - taskkill /T, _descendants and reap_orphans all walk LIVE links only.
# Measured 2026-10-11 on this box: a card's `npm install` (450 MB each, three
# at once on a swapping 16 GB machine), two `opencode serve` (59 h), a bash
# with ten children - all parents dead, all invisible to the harness. The
# reproduction is 20 lines: worker -> middle -> grandchild, middle exits,
# `taskkill /F /T worker` leaves the grandchild; closing a KILL_ON_JOB_CLOSE
# job leaves nothing.
#
# So ownership is a FACT THE OS KEEPS, not a tree we reconstruct: every spawn
# is assigned to its own job; children inherit the job whatever happens to
# the processes in between. The job handle lives here (ONE owner); closing it
# - or the daemon dying, which closes every handle - kills the whole family.
#
# BREAKAWAY_OK: a process may ESCAPE on purpose with CREATE_BREAKAWAY_FROM_JOB
# (popen_breakaway below) - the persistent Chrome, ops/tools/detach.py jobs and
# the restart helper must outlive the worker that started them.
_jobs = {}                      # pid -> job handle
_jobs_lock = threading.Lock()
BREAKAWAY = 0x01000000          # CREATE_BREAKAWAY_FROM_JOB


def _job_api():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, k32


def adopt(pid):
    """Put a FRESHLY spawned process (and so everything it will ever start) in
    its own kill-on-close job. Returns True when owned. Never raises: a spawn
    must not fail because ownership could not be taken - it degrades to the old
    tree-kill, loudly (stdout = the daemon log)."""
    if os.name != "nt" or not pid:
        return False
    try:
        ctypes, wintypes, k32 = _job_api()

        class _BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in
                        ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class _EXT(ctypes.Structure):
            _fields_ = [("Basic", _BASIC), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemory", ctypes.c_size_t),
                        ("PeakJobMemory", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError("CreateJobObjectW err %d" % ctypes.GetLastError())
        info = _EXT()
        info.Basic.LimitFlags = 0x2000 | 0x0800     # KILL_ON_JOB_CLOSE | BREAKAWAY_OK
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.GetLastError()
            k32.CloseHandle(job)
            raise OSError("SetInformationJobObject err %d" % err)
        hp = k32.OpenProcess(0x0100 | 0x0001, False, int(pid))     # SET_QUOTA | TERMINATE
        if not hp:
            err = ctypes.GetLastError()
            k32.CloseHandle(job)
            raise OSError("OpenProcess err %d" % err)
        try:
            ok = k32.AssignProcessToJobObject(job, hp)
            err = ctypes.GetLastError()
        finally:
            k32.CloseHandle(hp)
        if not ok:
            k32.CloseHandle(job)
            raise OSError("AssignProcessToJobObject err %d" % err)
        with _jobs_lock:
            old = _jobs.pop(int(pid), None)             # a recycled pid: its old family is long gone
            _jobs[int(pid)] = job
        if old:
            k32.TerminateJobObject(old, 1)
            k32.CloseHandle(old)
        threading.Thread(target=_close_when_root_exits, args=(int(pid), job),
                         daemon=True, name="job-%d" % int(pid)).start()
        return True
    except Exception as e:                              # noqa: BLE001
        print("proctable: job ownership failed for pid %s (%s) - falling back to tree-kill" % (pid, e))
        return False


def _close_when_root_exits(pid, job):
    """The worker is the family's root: when IT ends - cleanly, by crash, or by
    anyone's kill - nothing it started can report to it any more, so the family
    goes too. One blocking wait on the process handle (event time, no polling).
    This is the leak that used to run until the NEXT turn (or forever): a
    worker dying on its own left its tool shells and MCP servers behind."""
    try:
        ctypes, wintypes, k32 = _job_api()
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        hp = k32.OpenProcess(0x00100000, False, pid)             # SYNCHRONIZE
        if not hp:
            return
        try:
            k32.WaitForSingleObject(hp, 0xFFFFFFFF)               # INFINITE
        finally:
            k32.CloseHandle(hp)
    except Exception:                                   # noqa: BLE001
        return
    close_job(pid, only=job)


def close_job(pid, only=None):
    """Kill everything the job owns (the worker, its tool shells, MCP servers,
    npm, a leaked `opencode serve`...) and release the handle. True if a job
    existed. Idempotent - safe on a pid that never had one. `only`: act just if
    the registered job IS that handle (a recycled pid must not close a NEWER
    worker's family)."""
    if os.name != "nt":
        return False
    with _jobs_lock:
        job = _jobs.get(int(pid))
        if not job or (only is not None and job != only):
            return False
        del _jobs[int(pid)]
    try:
        _ctypes, _wintypes, k32 = _job_api()
        k32.TerminateJobObject(job, 1)
        k32.CloseHandle(job)
    except Exception:                                   # noqa: BLE001
        pass
    return True


def own(p):
    """adopt() for a Popen the CALLER made - the spawn sites that do not go
    through a driver's _record_pid (Henry's chat port, judge, PM, room Henry).
    The caller keeps `subprocess.Popen` in its own module on purpose: the test
    suite patches `<module>.subprocess` to stand in for the CLI, and a Popen
    made in here would slip past that patch and start the real thing. Taking
    ownership never decides whether the spawn works (getattr: a stand-in has
    no pid)."""
    adopt(getattr(p, "pid", None))
    return p


def own_turn(p):
    """own() for a one-shot TURN the restart tool must wait for (Henry's judge /
    broker runs). own() lives in the daemon's memory; restart_daemon.py is another
    process and reads driver_pids.json - so a turn is recorded there too, and
    forget_turn() removes it. 2026-10-20 22:30: a restart read "nothing running"
    while the broker was mid-way through filing a process's step cards."""
    own(p)
    pid = getattr(p, "pid", None)
    if pid:
        _record_pid(pid, _proc_start_epoch(pid))
    return p


def forget_turn(p):
    pid = getattr(p, "pid", None)
    if pid:
        _forget_pid(pid)


def owned():
    """[(pid, exe, started_epoch_or_None)] of every live process THIS daemon
    owns - the question "is this one mine?" answered from what the OS keeps,
    never from a stored list. Owned = a descendant of the daemon by live parent
    links, OR a member of one of our kill-on-close jobs (that is what still
    reaches a grandchild whose parent already died). Everything else on the
    box belongs to the owner or to another program (Paseo, Claude Desktop,
    the owner's shells) - ownership by EXCLUSION, the way Paseo's agent knows
    its own sessions. Read-only; nothing here kills or adopts."""
    try:
        table = _pid_table()
    except Exception:                                   # noqa: BLE001
        return []
    names = {p: exe for p, _pp, exe in table}
    mine = set(_descendants(os.getpid()))
    if os.name == "nt":
        try:
            ctypes, wintypes, k32 = _job_api()
            k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
            with _jobs_lock:
                jobs = list(_jobs.values())
            if jobs:
                for pid in names:
                    if pid in mine or pid == os.getpid():
                        continue
                    hp = k32.OpenProcess(0x1000, False, pid)        # QUERY_LIMITED_INFORMATION
                    if not hp:
                        continue
                    try:
                        for j in jobs:
                            r = wintypes.BOOL(0)
                            if k32.IsProcessInJob(hp, j, ctypes.byref(r)) and r.value:
                                mine.add(pid)
                                break
                    finally:
                        k32.CloseHandle(hp)
        except Exception:                               # noqa: BLE001
            pass
    return sorted(((p, names.get(p, "?"), _proc_start_epoch(p)) for p in mine), key=lambda r: r[0])


def kill_owned(p):
    """Kill ONE spawned process AND its whole family (replaces bare p.kill() /
    p.terminate(), which left every child behind)."""
    close_job(getattr(p, "pid", 0) or 0)
    try:
        p.kill()
    except Exception:                                   # noqa: BLE001
        pass


def popen_breakaway(argv, **kw):
    """Popen that LEAVES the caller's job (see BREAKAWAY_OK above) - for the few
    processes that must outlive the worker that starts them. Outside any job the
    flag is ignored; inside a foreign job that forbids breakaway CreateProcess
    fails, and we retry without it rather than not start at all."""
    flags = kw.pop("creationflags", 0)
    if os.name != "nt":
        return subprocess.Popen(argv, **kw)
    try:
        return subprocess.Popen(argv, creationflags=flags | BREAKAWAY, **kw)
    except OSError:
        return subprocess.Popen(argv, creationflags=flags, **kw)


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
                           capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                proc.wait(timeout=grace)
            except Exception:
                pass
            if proc.poll() is None:                          # ignored -> force
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # confirm: reap surviving descendants one by one. Guarded by the
            # image check so a recycled pid can never hit an innocent process.
            try:
                alive = {p for p, _pp, _exe in _pid_table()}
            except Exception:
                alive = set()
            for cp in family:
                if cp in alive and _is_agent_pid(cp):
                    subprocess.run(["taskkill", "/F", "/PID", str(cp)],
                                   capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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


from daemon.paths import DATA_ROOT as _DAEMON_ROOT
_PIDFILE = os.path.join(_DAEMON_ROOT, "state", "driver_pids.json")
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
    """The one seam every driver already calls right after Popen: record the pid
    AND take ownership of its whole future family (adopt)."""
    adopt(pid)
    with _pid_lock:
        pids = _read_pids()
        pids[str(pid)] = spawn_time
        _write_pids(pids)


def _forget_pid(pid):
    """The worker is finished (exited, or just killed): everything it still
    owns goes with it - this is what ends the leak of a worker that dies on its
    own and leaves its tool shells and MCP children behind."""
    close_job(pid)
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
# (ops/docs/multi-engine-build-plan.md Cards 6/7) - unverified against real
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
                                   capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if r.returncode == 0:
                    killed += 1
            else:
                os.kill(pid, 9)
                killed += 1
        except Exception:
            pass
    return killed
