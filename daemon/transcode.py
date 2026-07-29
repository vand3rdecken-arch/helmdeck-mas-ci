# -*- coding: utf-8 -*-
"""Small screen-friendly copies of a recording, made ON THE USER'S OWN MACHINE.

Why here and not on the relay: the relay is a single shared box, so anything it
stores or computes becomes a per-user cost and eventually a wall. Transcoding in
the daemon distributes the work across as many machines as there are users, at
zero cost to whoever hosts the relay, and it shrinks what has to cross the wire
in the first place - a desktop capture is far larger than a phone or a 600x600
glasses display can use.

Profiles are derived once per recording and cached next to it, so repeat views
cost nothing. Without ffmpeg present the original file is served unchanged -
degraded, never broken.
"""
import os, shutil, subprocess, threading

# height, video bitrate, audio: what each surface actually needs
PROFILES = {
    "mobile":  {"height": 480, "vb": "700k",  "fps": 15, "audio": False},
    "glasses": {"height": 360, "vb": "350k",  "fps": 10, "audio": False},
    "full":    None,                      # the original, untouched
}

_locks = {}
_locks_guard = threading.Lock()


def ffmpeg_path():
    """ffmpeg from PATH, or a copy dropped next to the repo's tools/."""
    p = shutil.which("ffmpeg")
    if p:
        return p
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "ffmpeg", "ffmpeg.exe")
    return local if os.path.exists(local) else None


def available():
    return ffmpeg_path() is not None


def _lock_for(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def variant(src, profile):
    """Path to the requested rendition of `src`, building it once if needed.

    Returns `src` itself for the "full" profile, when ffmpeg is missing, or if
    the conversion fails - callers always get a playable file.
    """
    spec = PROFILES.get(profile)
    if not spec or not os.path.exists(src):
        return src
    exe = ffmpeg_path()
    if not exe:
        return src

    base, _ = os.path.splitext(src)
    out = "%s.%s.mp4" % (base, profile)
    # a finished rendition is reused; a zero-byte file means a previous run died
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out

    with _lock_for(out):                     # two viewers must not transcode twice
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
        tmp = out + ".part"
        cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
               "-vf", "scale=-2:%d" % spec["height"],
               "-r", str(spec["fps"]),
               "-c:v", "libx264", "-preset", "veryfast", "-b:v", spec["vb"],
               "-movflags", "+faststart"]     # index up front: playable while it streams
        cmd += ["-an"] if not spec["audio"] else ["-c:a", "aac", "-b:a", "64k"]
        cmd += [tmp]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=1800)
            if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, out)
                return out
        except (subprocess.SubprocessError, OSError):
            pass
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return src


def describe(src):
    """What renditions exist for a recording, for the UI to offer."""
    base, _ = os.path.splitext(src)
    out = {}
    for name in PROFILES:
        p = src if name == "full" else "%s.%s.mp4" % (base, name)
        if os.path.exists(p):
            out[name] = os.path.getsize(p)
    return out
