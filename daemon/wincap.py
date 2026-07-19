# -*- coding: utf-8 -*-
"""Windows screen capture via the imageio-ffmpeg bundled ffmpeg (no system install).
One ffmpeg process, two outputs: screen.mp4 (the recording) and live.jpg (newest frame,
overwritten ~1/s — the Herald-cast-style glance feed the APK/glasses viewer reads)."""
import os, signal, subprocess
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

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
    return subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW)

def stop(proc):
    """Graceful stop so the mp4 gets its trailer written."""
    if proc.poll() is not None:
        return
    try:
        proc.stdin.write(b"q")   # ffmpeg's own quit key — clean finalize
        proc.stdin.flush()
        proc.wait(timeout=10)
    except Exception:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
