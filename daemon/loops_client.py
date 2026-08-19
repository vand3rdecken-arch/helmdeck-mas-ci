# -*- coding: utf-8 -*-
"""Loops (loops.so) contact enrichment for new testers - creates a contact
and fires the "Contact added to audience" welcome workflow. Enrichment
only: never touches auth/user data paths (auth.create_user, users.json)
and never blocks or fails a signup if Loops is unreachable or
LOOPS_API_KEY isn't set - card stays parked until the owner has a key.

LOOPS_API_KEY lives in the repo-root .env (git-ignored, same file
deploy/*.sh sources) - read directly here since the daemon process itself
doesn't source .env."""
import json
import os
import urllib.error
import urllib.request

from _subpaths import REPO_ROOT as _ROOT
_ENV = os.path.join(_ROOT, ".env")
API = "https://app.loops.so/api/v1"


def _key():
    key = os.environ.get("LOOPS_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(_ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("LOOPS_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def enabled():
    return bool(_key())


def signup_contact(email, name="", source="helmdeck-signup"):
    """Create/update a Loops contact for a new tester (userGroup=tester),
    which fires the Loops "Contact added to audience" welcome workflow.
    Best-effort: returns True/False, never raises."""
    key = _key()
    if not key or not email:
        return False
    req = urllib.request.Request(
        API + "/contacts/create",
        data=json.dumps({
            "email": email,
            "firstName": name,
            "userGroup": "tester",
            "source": source,
            "subscribed": True,
        }).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 # Loops' WAF 403s the default "Python-urllib/x.y" UA.
                 "User-Agent": "HelmDeck-Daemon/1.0"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            json.loads(r.read().decode("utf-8"))
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return False
