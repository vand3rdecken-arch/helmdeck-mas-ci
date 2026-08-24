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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desktop_update   # Paseo auto-update engine (see its docstring)

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
_state = {"daemon": False, "relay": "unbekannt", "update": "prüft …"}


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


def _open_daemon_log():
    # stdout/stderr into the SAME daemon.out.log the Electron shell appends to
    # (single log regardless of which supervisor started this run) - a crash
    # under DEVNULL left zero trace anywhere, which is what made "it keeps
    # crashing" unfalsifiable. If the canonical name is pinned by a lingering
    # process that outlived whatever set it (main.js parity: a reboot clears
    # it, but a supervisor must not go dark until then), fall back to a
    # PID-suffixed file instead of losing capture for this whole run.
    canonical = os.path.join(DAEMON_DIR, "daemon.out.log")
    try:
        return open(canonical, "a", encoding="utf-8")
    except OSError:
        fallback = os.path.join(DAEMON_DIR, "daemon.out.%d.log" % os.getpid())
        f = open(fallback, "a", encoding="utf-8")
        f.write("[tray] daemon.out.log unavailable (held by another process) - "
                "logging here instead\n")
        return f


def _spawn_daemon():
    out = _open_daemon_log()
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    # daemon/ is a real Python package now (absolute `spine`/
    # `cells.<id>` imports, not a sys.path trick) - it must be
    # launched as a module from the REPO ROOT, not as a bare script from
    # inside daemon/ (see daemon/debt.py sys-path-trick-to-real-package-
    # imports).
    return subprocess.Popen(
        [_python_for_daemon(), "-m", "daemon.swarm", "serve"],
        cwd=ROOT, creationflags=CREATE_NO_WINDOW, env=env,
        stdout=out, stderr=out,
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


# ------------------------------------------------------------ desktop auto-update
# Paseo's auto-update, hooked into the always-on supervisor (this tray) so the
# desktop follows every published update even when the Electron window is never
# opened or never closed. Timing IS Paseo's (desktop_update.py cites the exact
# source files): silent check at start + every 30 min, 10 s retry while a
# download is pending, silent apply - never a dialog. The supervise loop above
# is untouched; this runs in its own thread.

def _packaged_appdist():
    """Where the installed Electron shell keeps the bundle it serves. Derived
    from the NSIS installer's own uninstall registration (evidence, not a
    guessed path). electron-builder's NSIS omits InstallLocation and the owner
    installs to a custom dir (allowToChangeInstallationDirectory), so the
    install dir comes from the UninstallString/DisplayIcon paths that key
    records. Fallback: the default per-user dir. None when no packaged install
    exists - then there is nothing to update here."""
    cands = []
    if winreg:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Uninstall")
        except OSError:
            k = None
        if k:
            try:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i); i += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(k, sub) as sk:
                            name, _ = winreg.QueryValueEx(sk, "DisplayName")
                            if not str(name).strip().lower().startswith("helmdeck"):
                                continue
                            for val in ("InstallLocation", "UninstallString", "DisplayIcon"):
                                try:
                                    v, _ = winreg.QueryValueEx(sk, val)
                                except OSError:
                                    continue
                                p = str(v).strip().strip('"').split('"')[0].strip()
                                d = p if val == "InstallLocation" else os.path.dirname(p)
                                if d:
                                    cands.append(os.path.join(d, "resources", "app-dist"))
                    except OSError:
                        continue
            finally:
                k.Close()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(os.path.join(local, "Programs", "HelmDeck", "resources", "app-dist"))
    for c in cands:
        if os.path.isdir(c):
            return c
    return None


def _update_once():
    """One silent cycle. Returns (status-text, retry-soon)."""
    base = desktop_update.read_relay_url(SETTINGS)
    if not base:
        return "aus (kein Relay gekoppelt)", False
    target = _packaged_appdist()
    if not target:
        return "aus (keine Desktop-App installiert)", False
    try:
        # while the Electron shell serves, only STAGE - the shell swaps on its
        # own quit/start (Paseo installs on quit, never under a live app)
        r = desktop_update.sync_target(base, target,
                                       allow_swap=lambda: not desktop_update.shell_busy())
        return {"up-to-date": "aktuell",
                "staged": "bereit – App übernimmt beim Beenden",
                "applied": "angewendet ✓"}.get(r, r), False
    except Exception as e:
        # Paseo: a failed SILENT check is logged and retried, never surfaced
        return "Fehler, neuer Versuch: %s" % str(e)[:60], True


def _update_loop(icon):
    while not _stop.is_set():
        text, retry = _update_once()
        if _state["update"] != text:
            _state["update"] = text
            _apply_icon(icon)
        _stop.wait(desktop_update.PENDING_RECHECK if retry else desktop_update.CHECK_INTERVAL)


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
        pystray.MenuItem(lambda i: "Update: %s" % _state["update"], None, enabled=False),
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
    threading.Thread(target=_update_loop, args=(icon,), daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
