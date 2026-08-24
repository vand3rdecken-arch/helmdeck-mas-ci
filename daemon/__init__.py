"""HelmDeck daemon - thin launcher + runtime-data home. The code lives at the
repo root since the two-mains split (2026-08-24): spine/ = shared
infrastructure no cell owns; cells/<id>/ = each agentic system's own logic.
daemon/ keeps the entrypoint (`python -m daemon.swarm`), paths.py (the decreed
never-moves path anchor) and the machine-local runtime state (db, settings,
events) - so the desktop tray's spawn command and every data path survived the
split unchanged."""
