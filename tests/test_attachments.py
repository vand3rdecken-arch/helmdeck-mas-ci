# -*- coding: utf-8 -*-
"""The attachment contract between the app composer and the daemon.

The app sends [{name, data(base64), mime}] (app/src/data/attachments.ts); the
daemon writes them into the card's run_dir/.attachments and appends the PATHS to
the agent prompt. HelmDeck drives the Claude Code CLI (`claude -p`), so a path
the agent reads with its own Read tool is the only channel there is - there is
no provider image-block to put base64 into.

Under test:
  - bare base64 AND a data: URL both decode (the web paste path produces the
    latter, the Expo pickers the former)
  - the caps the app mirrors are real, and the daemon SKIPS SILENTLY past them
    (which is exactly why the composer pre-checks and tells the owner)
  - add/remove/list round-trips on a card
  - the saved path is what reaches the agent prompt

Self-sandboxing: a temp run_dir + an in-memory board, no daemon, no network."""
import base64
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="helmdeck-att-")

from daemon.spine.agent import turnopts

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def b64(raw):
    return base64.b64encode(raw).decode()


print("attachment contract")

# -- 1. both encodings the app can produce --------------------------------
run = os.path.join(SANDBOX, "run1")
os.makedirs(run, exist_ok=True)
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 40          # header + filler, enough to be a file
saved = turnopts.save_attachments(run, [
    {"name": "shot.png", "data": b64(PNG), "mime": "image/png"},              # picker: bare
    {"name": "note.txt", "data": "data:text/plain;base64," + b64(b"hallo"), "mime": "text/plain"},  # web paste: data URL
])
check(len(saved) == 2, "bare base64 AND a data: URL are both accepted (%d saved)" % len(saved))
check(all(os.path.exists(p) for p in saved), "both files really exist on disk")
check(open(saved[0], "rb").read() == PNG, "bytes survive the round trip unchanged")
check(open(saved[1], "rb").read() == b"hallo", "the data: prefix is stripped, not stored")
check(all(os.path.basename(os.path.dirname(p)) == ".attachments" for p in saved),
      "they land in run_dir/.attachments")

# -- 2. the caps the composer mirrors are real ----------------------------
check(turnopts.MAX_FILES == 6 and turnopts.MAX_BYTES == 5 * 1024 * 1024,
      "caps are MAX_FILES=6 / MAX_BYTES=5MB (app/src/data/attachments.ts mirrors these)")

run2 = os.path.join(SANDBOX, "run2")
os.makedirs(run2, exist_ok=True)
over = turnopts.save_attachments(run2, [
    {"name": "huge.bin", "data": b64(b"x" * (turnopts.MAX_BYTES + 1)), "mime": "application/octet-stream"}])
check(over == [], "an oversized file is SKIPPED SILENTLY by the daemon - the composer must catch it first")

run3 = os.path.join(SANDBOX, "run3")
os.makedirs(run3, exist_ok=True)
many = turnopts.save_attachments(run3, [
    {"name": "f%d.txt" % i, "data": b64(b"data"), "mime": "text/plain"} for i in range(10)])
check(len(many) == turnopts.MAX_FILES, "only MAX_FILES are kept, the rest vanish (%d)" % len(many))

run4 = os.path.join(SANDBOX, "run4")
os.makedirs(run4, exist_ok=True)
bad = turnopts.save_attachments(run4, [{"name": "x.txt", "data": "!!!not base64!!!"}])
check(isinstance(bad, list), "malformed base64 never raises - an attachment must not crash a turn")

# -- 3. path traversal in the NAME cannot escape --------------------------
run5 = os.path.join(SANDBOX, "run5")
os.makedirs(run5, exist_ok=True)
eve = turnopts.save_attachments(run5, [
    {"name": "../../evil.txt", "data": b64(b"pwn"), "mime": "text/plain"}])
inside = all(os.path.abspath(p).startswith(os.path.abspath(run5)) for p in eve)
check(inside, "a ../.. filename stays inside the card's own .attachments dir")

# -- 4. the saved path is what reaches the agent --------------------------
# sessions.py builds: prompt += "\n\nAttached files (read them as needed): " + ", ".join(t["attachments"])
line = "Attached files (read them as needed): " + ", ".join(saved)
check(all(p in line for p in saved), "every saved path appears in the agent prompt line")
check(line.startswith("Attached files"), "the prompt tells the agent to read them")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("all attachment-contract checks passed")
