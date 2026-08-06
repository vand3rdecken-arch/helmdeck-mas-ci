# Sandbox daemon bootstrap for the release-build smoke (run once, from repo root):
#   py -3.12 .smoke/setup_sandbox.py https://<tunnel>.trycloudflare.com
# Creates a fresh owner in the WORKTREE-LOCAL users.json/helmdeck.db (git-ignored,
# separate from the owner's real daemon), points settings.relay.url at the tunnel,
# and seeds a few backlog cards so the paired board has content.
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "daemon"))
import auth
import events
import sessions

tunnel = sys.argv[1].rstrip("/")
if not tunnel.startswith("https://"):
    raise SystemExit("tunnel url must be https://")

try:
    auth.create_user("owner", "smoke-owner-pw1", "owner")
    print("owner: created")
except ValueError as e:
    print("owner:", e)

events.save_settings({"relay": {"url": tunnel}})
print("relay.url =", tunnel)

seeded = {t["task"] for t in __import__("db").tracks_all()}
for branch, task in [
    ("smoke-pairing", "Release-Smoke: Pairing über TLS/Tunnel verifizieren"),
    ("smoke-ota", "Release-Smoke: OTA Check-on-Resume verifizieren"),
    ("smoke-rollback", "Release-Smoke: Rollback auf Embedded verifizieren"),
]:
    if task in seeded:
        print("card exists:", branch)
        continue
    t = sessions.new_track(ROOT, branch, task, lane="backlog", actor="owner")
    print("card:", json.dumps(t.get("id") if isinstance(t, dict) else t))
