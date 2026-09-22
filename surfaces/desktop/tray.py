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

Run:  pythonw -3.12 surfaces/desktop/tray.py     (pythonw = no console)
Later: ship as one HelmDeck.exe via PyInstaller (see build_exe.md).
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAEMON_DIR = os.path.join(ROOT, "daemon")
SETTINGS = os.path.join(DAEMON_DIR, "settings.json")        # legacy fallback, see _relay_status
RELAY_FEED = os.path.join(DAEMON_DIR, "relay_feed.json")    # spine/storage/events.RELAY_FEED
PORT = 8140
HEALTH_URL = "http://127.0.0.1:%d/" % PORT
# Probe a path that answers DIRECTLY (401, no redirect). "/" 302-redirects to
# the web UI (:3300), so probing it measured the WEB server's health, not the
# daemon's - see _health() below for the incident this caused.
PROBE_URL = "http://127.0.0.1:%d/system/health" % PORT
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "HelmDeck"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# ---- local relay fallback (debt 63) ----------------------------------------
# While the relay VM is down, surfaces/relay/relay.py + a cloudflared tunnel
# run on this PC. Until 2026-09-22 ops/deploy/relay_local.cmd started them from
# an HKCU Run entry as two MINIMIZED CONSOLE WINDOWS (focus-stealing at every
# login) with no respawn. They are supervised here now like the daemon:
# hidden, logged to daemon/relay_*.log, restarted when they die. Enabled when
# the cloudflared binary is present; HELMDECK_LOCAL_RELAY=0 turns it off.
RELAY_PORT = int(os.environ.get("HELMDECK_RELAY_PORT", "6790"))
RELAY_HEALTH_URL = "http://127.0.0.1:%d/health" % RELAY_PORT
RELAY_SCRIPT = os.path.join(ROOT, "surfaces", "relay", "relay.py")
TUNNEL_NAME = "helmdeck-relay"
CLOUDFLARED = os.path.join(os.path.expanduser("~"), "bin", "cloudflared.exe")
if not os.path.exists(CLOUDFLARED):
    CLOUDFLARED = shutil.which("cloudflared") or ""
LOCAL_RELAY = os.environ.get("HELMDECK_LOCAL_RELAY", "1") != "0" and bool(CLOUDFLARED)
LEGACY_RELAY_RUN_NAME = "HelmDeckRelay"      # the relay_local.cmd autostart, removed at start

_proc = None                 # the daemon WE spawned (None if adopted/external)
_relay_proc = None           # relay.py we spawned
_tunnel_proc = None          # cloudflared we spawned
_stop = threading.Event()
_state = {"daemon": False, "relay": "unbekannt", "update": "prüft …", "local_relay": "…"}


# ---------------------------------------------------------------- daemon health
def _health():
    # ANY HTTP reply means a daemon is listening - main.js daemonReachable
    # parity ("even 401"). The old probe hit "/" (which 302-redirects to the
    # web UI on :3300, urllib follows it) and demanded a 200 - so it measured
    # the WEB server, and an auth-gated reply counted as DOWN. A live daemon
    # thus looked dead whenever :3300 was closed, this supervisor spawned a
    # rival, and the rival's SINGLETON tree-kill evicted the healthy daemon -
    # the measured 2026-08-29 eviction war ("HelmDeck dead" with a daemon
    # running minutes before).
    try:
        with urllib.request.urlopen(PROBE_URL, timeout=2):
            return True
    except urllib.error.HTTPError:
        return True                    # the daemon answered (401/404) = alive
    except Exception:
        return False


def _relay_status():
    """Report pairing without hitting the daemon: paired = a phone public key
    is pinned for the room. Settings live in the db since the config
    consolidation (2026-09-03) - read via the daemon's own loader (WAL allows
    a concurrent reader process); the old settings.json file stays as the
    fallback for an install whose daemon never booted the new code, so the
    tray never claims 'unbekannt' on a machine that is actually paired."""
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from spine.storage import events
        rel = (events.settings().get("relay") or {})
    except Exception:
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                rel = (json.load(f).get("relay") or {})
        except Exception:
            return "unbekannt"
    if not (rel.get("url") and rel.get("room")):
        return "nicht konfiguriert"
    return "gekoppelt" if rel.get("phone_pub") else "wartet auf Kopplung"


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


# ------------------------------------------------------------ local relay fallback
def _relay_health():
    try:
        with urllib.request.urlopen(RELAY_HEALTH_URL, timeout=2):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _open_log(name):
    return open(os.path.join(DAEMON_DIR, name), "a", encoding="utf-8")


def _spawn_relay():
    return subprocess.Popen(
        [_python_for_daemon(), RELAY_SCRIPT], cwd=ROOT,
        creationflags=CREATE_NO_WINDOW, env=dict(os.environ, PYTHONUNBUFFERED="1"),
        stdout=_open_log("relay_console.out.log"), stderr=_open_log("relay_console.err.log"),
    )


def _spawn_tunnel():
    return subprocess.Popen(
        [CLOUDFLARED, "tunnel", "run", TUNNEL_NAME], cwd=ROOT,
        creationflags=CREATE_NO_WINDOW,
        stdout=_open_log("relay_tunnel.out.log"), stderr=_open_log("relay_tunnel.err.log"),
    )


def _tunnel_running_elsewhere():
    """A cloudflared connector already running OUTSIDE this supervisor (the
    legacy relay_local.cmd window, or one started by hand): adopt it rather
    than run a second connector for the same tunnel."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=10, creationflags=CREATE_NO_WINDOW)
        return "cloudflared.exe" in (r.stdout or "")
    except Exception:
        return False


def _public_relay_is_edge():
    """True once the PUBLIC relay URL is served by the Cloudflare Worker
    (surfaces/relay/worker - its /health carries "edge": true). From that
    moment the local relay.py + tunnel are obsolete: nothing on this PC must
    listen for the phone any more (2026-09-22, the reason the worker exists).
    Read the URL the daemon is paired to; fall back to the canonical host."""
    url = "https://relay.helmdeck.de"
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from spine.storage import events
        url = (events.settings().get("relay") or {}).get("url") or url
    except Exception:
        pass
    try:
        req = urllib.request.Request(url.rstrip("/") + "/health",
                                     headers={"User-Agent": "helmdeck-tray"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return bool((json.loads(r.read() or b"{}") or {}).get("edge"))
    except Exception:
        return False


def _supervise_relay(icon):
    """Same contract as _supervise: relay.py by HEALTH (adopt an existing one,
    spawn when :6790 goes quiet), cloudflared by process (adopt an external
    one, else keep ours alive). Stands down entirely while the public relay is
    the Cloudflare Worker (re-checked every 5 min, so a rollback to the local
    fallback is picked up without a restart)."""
    global _relay_proc, _tunnel_proc
    adopted_tunnel = _tunnel_running_elsewhere()
    edge_checked = 0.0
    edge = False
    while not _stop.is_set():
        if time.time() - edge_checked > 300:
            edge = _public_relay_is_edge()
            edge_checked = time.time()
        if edge:
            _stop_relay()                       # ours, if any - the worker serves now
            if _state["local_relay"] != "aus (Cloudflare Worker aktiv)":
                _state["local_relay"] = "aus (Cloudflare Worker aktiv)"
                _apply_icon(icon)
            _stop.wait(30)
            continue
        up = _relay_health()
        if not up and (_relay_proc is None or _relay_proc.poll() is not None):
            try:
                _relay_proc = _spawn_relay()
            except Exception:
                _relay_proc = None
            for _ in range(10):
                if _stop.is_set() or _relay_health():
                    break
                time.sleep(1)
            up = _relay_health()
        if adopted_tunnel and not _tunnel_running_elsewhere():
            adopted_tunnel = False                # the external one went away: take over
        ours = _tunnel_proc is not None and _tunnel_proc.poll() is None
        if not adopted_tunnel and not ours:
            try:
                _tunnel_proc = _spawn_tunnel()
                ours = True
            except Exception:
                _tunnel_proc = None
        tun = adopted_tunnel or ours
        new = "läuft" if (up and tun) else ("Relay aus" if not up else "Tunnel aus")
        if _state["local_relay"] != new:
            _state["local_relay"] = new
            _apply_icon(icon)
        _stop.wait(4)


def _stop_relay():
    for p in (_relay_proc, _tunnel_proc):
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass


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
    base = desktop_update.read_relay_url(RELAY_FEED) or desktop_update.DEFAULT_FEED
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
def _autostart_value():
    if not winreg:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, RUN_NAME)
            return v or None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _autostart_on():
    return _autostart_value() is not None


def _autostart_cmd():
    exe = sys.executable or "pythonw"
    if getattr(sys, "frozen", False):
        return '"%s"' % exe                       # the packaged HelmDeck.exe
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    launcher = pyw if os.path.exists(pyw) else exe
    return '"%s" "%s"' % (launcher, os.path.abspath(__file__))


def _remove_run_value(name):
    """Drop a legacy HKCU Run entry (the relay_local.cmd autostart, superseded
    by _supervise_relay). Idempotent."""
    if not winreg:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        pass
    except Exception:
        pass


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
    _stop_relay()
    icon.stop()


def _menu():
    return pystray.Menu(
        pystray.MenuItem(lambda i: "Daemon: %s" % ("läuft ✓" if _state["daemon"] else "aus ✕"), None, enabled=False),
        pystray.MenuItem(lambda i: "Relay: %s" % _state["relay"], None, enabled=False),
        pystray.MenuItem(lambda i: "Relay lokal: %s" % _state["local_relay"], None,
                         enabled=False, visible=LOCAL_RELAY),
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
    # Repair, don't just create: the measured 2026-08-29 outage was an EMPTY
    # Run value (autostart silently launched nothing), so any value that is
    # not exactly the current launch command gets rewritten.
    if _autostart_value() != _autostart_cmd():
        _set_autostart(True)
    if LOCAL_RELAY:
        _remove_run_value(LEGACY_RELAY_RUN_NAME)
    icon = pystray.Icon("HelmDeck", _icon_image(False), "HelmDeck", _menu())
    threading.Thread(target=_supervise, args=(icon,), daemon=True).start()
    if LOCAL_RELAY:
        threading.Thread(target=_supervise_relay, args=(icon,), daemon=True).start()
    threading.Thread(target=_update_loop, args=(icon,), daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
