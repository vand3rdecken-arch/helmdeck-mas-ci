# -*- coding: utf-8 -*-
"""Windows screen capture via the imageio-ffmpeg bundled ffmpeg (no system install).
One ffmpeg process, two outputs: screen.mp4 (the recording) and live.jpg (newest frame,
overwritten ~1/s - the Herald-cast-style glance feed the APK/glasses viewer reads)."""
import json, os, signal, subprocess, threading
import imageio_ffmpeg

from daemon.paths import DAEMON_ROOT as _DAEMON_ROOT

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# Orphan-reaping (drivers.py's reap_orphans pattern, applied here - found live
# 2026-08-14): _turn's `finally: wincap.stop(rec)` only runs if the PYTHON
# PROCESS hosting that finally block is still alive to run it. A SINGLETON
# eviction (taskkill /F /T on the previous daemon, every restart) does not
# reliably cascade to a grandchild ffmpeg subprocess - `finally` cannot run
# in a process that was itself just force-killed. The result: an orphaned
# ffmpeg silently records the desktop forever (a real incident - one ran ~90
# minutes unsupervised) AND holds an open handle inside the card's worktree
# (gdigrab captures the whole desktop, but the process's cwd stays the
# run_dir it was spawned in, which pinned an app/ subdirectory against
# deletion until found and killed by hand). Track pids the same pid-reuse-
# safe way drivers.py does; reap on the next boot.
_PIDFILE = os.path.join(_DAEMON_ROOT, "state", "recorder_pids.json")
_pid_lock = threading.Lock()


def _read_pids():
    try:
        with open(_PIDFILE, encoding="utf-8") as f:
            return {str(k): v for k, v in (json.load(f) or {}).items()}
    except Exception:
        return {}


def _write_pids(pids):
    try:
        tmp = _PIDFILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pids, f)
        os.replace(tmp, _PIDFILE)
    except Exception:
        pass


def start(run_dir, fps=8):
    """Start capturing the whole desktop. Returns the Popen; stop with stop()."""
    mp4 = os.path.join(run_dir, "screen.mp4")
    live = os.path.join(run_dir, "live.jpg")
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "gdigrab", "-framerate", str(fps), "-i", "desktop",
           # recording: modest fps + fast preset keeps CPU low on long runs
           "-map", "0:v", "-vf", "scale=1280:-2", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", mp4,
           # glance feed: 1 fps, small, atomically overwritten
           "-map", "0:v", "-r", "1", "-vf", "scale=800:-2",
           "-update", "1", "-q:v", "7", live]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    from spine.agent import drivers
    with _pid_lock:
        pids = _read_pids()
        pids[str(proc.pid)] = drivers._proc_start_epoch(proc.pid)
        _write_pids(pids)
    return proc

def stop(proc):
    """Graceful stop so the mp4 gets its trailer written."""
    with _pid_lock:
        pids = _read_pids()
        if pids.pop(str(proc.pid), "absent") != "absent":
            _write_pids(pids)
    if proc.poll() is not None:
        return
    try:
        proc.stdin.write(b"q")   # ffmpeg's own quit key - clean finalize
        proc.stdin.flush()
        proc.wait(timeout=10)
    except Exception:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()


def reap_orphans():
    """On daemon start, kill any recorder left running by a PREVIOUS daemon
    (crash/eviction) - drivers.reap_orphans' exact pattern, pid-reuse-safe via
    the same OS-reported start-time check. Only pids WE recorded are touched."""
    from spine.agent import drivers
    with _pid_lock:
        rec = _read_pids()
        _write_pids({})
    killed = 0
    for pid_s, spawn in rec.items():
        try:
            pid = int(pid_s)
            if not drivers._is_ours(pid, spawn):
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
