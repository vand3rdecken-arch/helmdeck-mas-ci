# HelmDeck Desktop — packaging to a single .exe

`surfaces/desktop/tray.py` is the always-on system-tray shell that supervises the daemon
(`daemon/swarm.py serve`), auto-launches at login (HKCU `Run`), and shows
status + a pair link. Run it directly during dev:

```
py -3.12 -m pip install -r surfaces/desktop/requirements.txt
pythonw -3.12 surfaces/desktop/tray.py        # pythonw = no console window
```

The tray registers itself for login autostart on first run (toggle in the menu).

## Ship as one HelmDeck.exe (PyInstaller)

```
py -3.12 -m pip install pyinstaller
py -3.12 -m PyInstaller --noconsole --onefile --name HelmDeck surfaces/desktop/tray.py
# -> dist/HelmDeck.exe
```

`--noconsole` = no terminal window; `--onefile` = single exe. When frozen,
`tray.py` already switches its autostart command to the exe path and looks for a
`pythonw.exe` next to it to run the daemon.

### Note (follow-up for a fully self-contained installer)

`tray.py` launches the daemon with a Python interpreter (`_python_for_daemon`),
so today the packaged exe still needs the repo + a Python on the machine to run
`swarm.py serve`. For a true zero-dependency installer, bundle the daemon as a
second PyInstaller target (or add `daemon/` via `--add-data` and exec it with the
frozen interpreter) and point `_spawn_daemon` at that. Left as a follow-up — the
tray + supervision + autostart already make the desktop durable on this machine.
