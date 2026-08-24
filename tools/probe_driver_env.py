# -*- coding: utf-8 -*-
"""Prove what a card's agent process actually inherits.

A card runs isolated in a worktree; that isolation used to leave the agent
without any build toolchain, so `gradle`/`java` were simply absent and builds
failed before they started. Run this after changing drivers.env in settings to
confirm the agent really sees the toolchain:

    py -3.12 tools/probe_driver_env.py
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from spine.agent import drivers  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "..", "daemon", "settings.json")


def probe(label, cfg, command):
    t = {"id": "probe", "worktree": os.getcwd(), "session_id": None}
    _, out, _ = drivers.run(dict(cfg, type="cmd", command=command), t, "")
    first = next((l.strip() for l in out.splitlines() if l.strip()), "(no output)")
    print("  %-28s %s" % (label, first[:90]))


def main():
    env = (json.load(open(SETTINGS)).get("drivers", {}).get("claude", {}) or {}).get("env") or {}
    print("driver env configured:", "yes" if env else "NO - agents cannot build")
    print("\nwith the driver env (what a card gets now):")
    probe("java -version", {"env": env}, "java -version")
    probe("gradle wrapper reachable", {"env": env}, "if exist gradlew.bat (echo yes) else (echo n/a here)")
    print("\nwithout it (the old behaviour):")
    probe("java -version", {}, "java -version")


if __name__ == "__main__":
    main()
