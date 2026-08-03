# -*- coding: utf-8 -*-
"""HelmDeck Desktop - system-tray supervisor.

The "desktop" the phone reaches via the relay IS the local daemon (daemon/
swarm.py serve). A bare daemon dies on reboot / logout / crash and then the
phone shows "Desktop nicht erreichbar" (relay 503). This tray app is the small
always-on shell real desktop agents use (Docker/Ollama/Paseo-style):

  * lives in the system tray (no window),
  * SUPERVISES the daemon - starts it and restarts it whenever :8140 stops
    answering (crash, kill, first boot),
  * AUTO-LAUNCHES at login (HKCU Run key, toggleable from the menu),
  * shows status (Daemon / Relay) and opens the web UI to pair a phone.

Supervision is by HEALTH, not PID: if a daemon is already serving :8140 (e.g.
you started one by hand) the tray adopts it and only spawns its own when the
port goes quiet - so it never double-binds.

Run:  pythonw -3.12 desktop/tray.py     (pythonw = no console)
Later: ship as one HelmDeck.exe via PyInstaller (see build_exe.md).
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

try:
    import winreg
except ImportError:
    winreg = None

import pystray
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON_DIR = os.path.join(ROOT, "daemon")
SETTINGS = os.path.join(DAEMON_DIR, "settings.json")
PORT = 8140
HEALTH_URL = "http://127.0.0.1:%d/" % PORT
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "HelmDeck"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_proc = None                 # the daemon WE spawned (None if adopted/external)
_stop = threading.Event()
_state = {"daemon": False, "relay": "unbekannt"}


# ---------------------------------------------------------------- daemon health
def _health():
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as r:
            return getattr(r, "status", 200) == 200
    except Exception:
        return False


def _relay_status():
    """Read the (git-ignored) settings to report pairing without hitting the
    daemon: paired = a phone public key is pinned for the room."""
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            rel = (json.load(f).get("relay") or {})
        if not (rel.get("url") and rel.get("room")):
            return "nicht konfiguriert"
        return "gekoppelt" if rel.get("phone_pub") else "wartet auf Kopplung"
    except Exception:
        return "unbekannt"


def _python_for_daemon():
    # running as a script -> sys.executable is python.exe; when frozen we ship a
    # pythonw next to the exe, else fall back to the interpreter on PATH.
    exe = sys.executable or "python"
    if getattr(sys, "frozen", False):
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        return cand if os.path.exists(cand) else "pythonw"
    return exe


def _spawn_daemon():
    return subprocess.Popen(
        [_python_for_daemon(), "swarm.py", "serve"],
        cwd=DAEMON_DIR, creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _supervise(icon):
    """Keep exactly one daemon serving :8140. Health-driven so an already-running
    daemon is adopted and a dead one (ours or external) is (re)started."""
    global _proc
    while not _stop.is_set():
        up = _health()
        if not up and (_proc is None or _proc.poll() is not None):
            try:
                _proc = _spawn_daemon()
            except Exception:
                _proc = None
            for _ in range(20):                 # wait for it to bind
                if _stop.is_set() or _health():
                    break
                time.sleep(1)
            up = _health()
        new = {"daemon": up, "relay": _relay_status() if up else "Desktop aus"}
        if new != _state:
            _state.update(new)
            _apply_icon(icon)
        _stop.wait(4)


# ------------------------------------------------------------------- tray icon
def _icon_image(ok):
    """Rounded-square 'H' badge; ring is green when the daemon serves, red when
    it's down - the at-a-glance signal the phone cares about."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent = (47, 128, 237, 255)                 # HelmDeck blue
    ring = (52, 199, 89, 255) if ok else (255, 69, 58, 255)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=14, fill=accent)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=14, outline=ring, width=4)
    # a blocky H
    d.rectangle([22, 18, 27, 46], fill=(255, 255, 255, 255))
    d.rectangle([37, 18, 42, 46], fill=(255, 255, 255, 255))
    d.rectangle([22, 29, 42, 35], fill=(255, 255, 255, 255))
    return img


def _apply_icon(icon):
    icon.icon = _icon_image(_state["daemon"])
    icon.title = "HelmDeck - Daemon: %s | Relay: %s" % (
        "läuft" if _state["daemon"] else "aus", _state["relay"])
    try:
        icon.update_menu()
    except Exception:
        pass


# --------------------------------------------------------------- autostart (Run)
def _autostart_on():
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, RUN_NAME)
            return bool(v)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _autostart_cmd():
    exe = sys.executable or "pythonw"
    if getattr(sys, "frozen", False):
        return '"%s"' % exe                       # the packaged HelmDeck.exe
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    launcher = pyw if os.path.exists(pyw) else exe
    return '"%s" "%s"' % (launcher, os.path.abspath(__file__))


def _set_autostart(on):
    if not winreg:
        return
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _autostart_cmd())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


# ------------------------------------------------------------------- menu wiring
def _restart_daemon(icon, _item):
    global _proc
    def go():
        if _proc and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=8)
            except Exception:
                _proc.kill()
        _proc = None                              # supervisor respawns on next beat
    threading.Thread(target=go, daemon=True).start()


def _toggle_autostart(icon, _item):
    _set_autostart(not _autostart_on())
    icon.update_menu()


def _open_ui(_icon, _item):
    webbrowser.open(HEALTH_URL)


def _quit(icon, _item):
    _stop.set()
    global _proc
    if _proc and _proc.poll() is None:
        try:
            _proc.terminate()
        except Exception:
            pass
    icon.stop()


def _menu():
    return pystray.Menu(
        pystray.MenuItem(lambda i: "Daemon: %s" % ("läuft ✓" if _state["daemon"] else "aus ✕"), None, enabled=False),
        pystray.MenuItem(lambda i: "Relay: %s" % _state["relay"], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Web-UI / Handy koppeln", _open_ui, default=True),
        pystray.MenuItem("Daemon neu starten", _restart_daemon),
        pystray.MenuItem("Bei Anmeldung starten", _toggle_autostart,
                         checked=lambda i: _autostart_on()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Beenden", _quit),
    )


def main():
    # install = run once: register autostart so it's genuinely always-on.
    if not _autostart_on():
        _set_autostart(True)
    icon = pystray.Icon("HelmDeck", _icon_image(False), "HelmDeck", _menu())
    threading.Thread(target=_supervise, args=(icon,), daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
