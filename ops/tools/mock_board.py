# -*- coding: utf-8 -*-
"""Throwaway mock daemon for a phone-UI screenshot judge (NOT shipped).
Serves representative /tracks + /dashboard/data + /settings over plain HTTP so
the emulator can render the board/cards/next-up/list against varied data
without pairing, auth, or touching the real relay. Run: py -3.12 ops/tools/mock_board.py
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TRACKS = [
    {"id": "1", "task": "Refactor the merge classifier into a pure function", "lane": "working",
     "status": "running", "priority": "high", "mode": "auto", "branch": "fix-merge", "turns": 3, "ai_cost": 0.42},
    {"id": "2", "task": "Add headless unit tests for drivers/nightshift", "lane": "working",
     "status": "needs_you", "priority": "urgent", "mode": "cowork", "branch": "tests-headless", "turns": 7,
     "ai_cost": 1.13, "last_reply": "Brauche deine Entscheidung: Emulator- oder JVM-Tests?"},
    {"id": "3", "task": "Expose automation config in the mobile app", "lane": "review",
     "status": "submitted", "priority": "medium", "mode": "human", "branch": "mobile-automation", "turns": 5,
     "due": "2026-08-02", "ai_cost": 0.88, "last_reply": "Panel steht, bereit zur Abnahme."},
    {"id": "4", "task": "Purge .fuse_hidden junk + add .gitignore", "lane": "backlog",
     "status": "bounced", "priority": "low", "mode": "auto", "branch": "cleanup", "turns": 2, "ai_cost": 0.05},
    {"id": "5", "task": "Pytest suite for pure-logic parsers (grades/JSON)", "lane": "backlog",
     "status": "queued", "priority": "medium", "mode": "auto", "branch": "", "turns": 0, "client": "Acme"},
    {"id": "6", "task": "Zombie 'running' status survives daemon restart", "lane": "done",
     "status": "accepted", "priority": "high", "mode": "auto", "branch": "zombie-sweep", "turns": 9,
     "ai_cost": 2.10, "updated": "09:02", "value": 400},
    {"id": "7", "task": "Feed order: transcript ts to LOCAL HH:MM:SS", "lane": "done",
     "status": "accepted", "priority": "medium", "mode": "teach", "branch": "feed-order", "turns": 4,
     "ai_cost": 0.51, "updated": "08:41"},
]
DASH = {"wip": 3, "wip_limit": 5, "touches": 12, "touch_budget": 40, "headroom": 28,
        "ai_cost": 5.09, "billed": 800, "margin": 794.91, "cards": [],
        "settings": {"policy": {"lane_labels": {"backlog": "Backlog", "working": "In Arbeit",
                     "review": "Review", "done": "Erledigt"}}}}
SETTINGS = {"policy": {"lane_labels": {"backlog": "Backlog", "working": "In Arbeit",
            "review": "Review", "done": "Erledigt"}}, "default_repo": "helmdeck"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/tracks": return self._send(TRACKS)
        if p == "/dashboard/data": return self._send(DASH)
        if p == "/settings": return self._send(SETTINGS)
        if p == "/me": return self._send({"role": "owner", "name": "owner"})
        return self._send([])
    def do_POST(self):
        self._send({"ok": True})


if __name__ == "__main__":
    print("mock board on :8199", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8199), H).serve_forever()
