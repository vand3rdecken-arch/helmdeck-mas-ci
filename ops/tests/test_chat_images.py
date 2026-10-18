# -*- coding: utf-8 -*-
"""Images in the chat (owner 2026-10-18: "chat kann keine Bilder, screenshot etc zeigen").

  1. an image block in a tool_result is stored as a content-addressed file (the same screenshot twice = one
     file); a wrong type, an oversized or a malformed block is skipped, never raised;
  2. read_image serves only a bare name inside the folder - no path escape, no non-image file;
  3. the REAL stream parser (drivers.fold_timeline_event) turns a tool_result with an image into an `image`
     timeline item pointing at /tracks/<card>/image/<name>;
  4. GET /tracks/<id>/image/<name> returns {mime, data} to the card's owner and 403 to anyone else;
     GET /chat/image/<name> serves only the caller's own Henry folder.

Sandboxed folders + db; no daemon.  Run: py -3.12 ops/tests/test_chat_images.py
"""
import base64
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.storage import db                                  # noqa: E402

db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-img-"), "test.db")
db.init()
from spine.agent import images, drivers, timeline_store       # noqa: E402

_fails = []
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def block(raw=PNG, mime="image/png"):
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(raw).decode()}}


class Req:
    def __init__(self):
        self.sent = None

    def _send(self, code, body, *a):
        self.sent = (code, json.loads(body))


def main():
    base = tempfile.mkdtemp(prefix="hd-img-card-")
    saved = images.save_tool_images([{"type": "text", "text": "shot"}, block(), block()], base)
    names = {s["name"] for s in saved}
    files = os.listdir(os.path.join(base, ".attachments"))
    check(len(names) == 1 and len(files) == 1 and files[0].startswith("img-") and files[0].endswith(".png"),
          "the same screenshot twice is ONE content-addressed file (%s)" % files)
    check(images.save_tool_images([block(mime="image/svg+xml")], base) == [], "an svg (script-capable) is not stored")
    check(images.save_tool_images([block(raw=b"x" * (images.MAX_BYTES + 1))], base) == [], "an oversized image is skipped, not truncated")
    check(images.save_tool_images([{"type": "image", "source": {"type": "url", "url": "http://x"}}], base) == [],
          "a non-base64 source is skipped")
    check(images.save_tool_images("plain text result", base) == [], "a plain-text result has no images")

    got = images.read_image(base, files[0])
    check(got and got["mime"] == "image/png" and base64.b64decode(got["data"]) == PNG, "read_image returns the bytes as {mime, data}")
    open(os.path.join(base, "secret.txt"), "w").write("x")
    for bad in ("../secret.txt", "..\\secret.txt", "secret.txt", ".attachments", files[0] + "/../../secret.txt"):
        check(images.read_image(base, bad) is None, "no escape / no non-image: %r" % bad)

    # the real stream parser
    run_dir = os.path.join(tempfile.mkdtemp(prefix="hd-img-rec-"), "20261018-120000-direct")
    os.makedirs(run_dir)
    drivers.fold_timeline_event(run_dir, {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "tu1", "content": [{"type": "text", "text": "screenshot taken"}, block()]}]}})
    items = timeline_store.read(run_dir)
    img = [i for i in items if i.get("kind") == "image"]
    check(len(img) == 1 and img[0]["url"] == "/tracks/20261018-120000-direct/image/" + img[0]["name"]
          and img[0]["mime"] == "image/png", "the stream parser keeps the image as a timeline item with its URL (%s)" % img)
    tool = [i for i in items if i.get("result") is not None]
    check(tool and tool[0]["result"] == "screenshot taken", "...and the tool's text result is unchanged")

    # the routes
    from cells.engineer.routes import routes_tracks
    from cells.engineer.cards import sessions
    from spine.auth import auth
    card = {"id": "C1", "run_dir": run_dir, "client": "owner"}
    sessions.get_track = lambda tid: card if tid == "C1" else None
    auth.owns_card = lambda user, t: user.get("name") == "owner"
    r = Req(); routes_tracks.tracks_image_get(r, {"name": "owner", "role": "owner"}, "C1", img[0]["name"])
    check(r.sent[0] == 200 and r.sent[1]["mime"] == "image/png", "the card's owner gets the image")
    r = Req(); routes_tracks.tracks_image_get(r, {"name": "member", "role": "client"}, "C1", img[0]["name"])
    check(r.sent[0] == 403, "someone else gets 403")
    r = Req(); routes_tracks.tracks_image_get(r, {"name": "owner", "role": "owner"}, "C1", "..%2F..%2Fsecret.txt")
    check(r.sent[0] == 404, "an encoded path escape is a 404")

    from cells.copilot.chat import copilot
    from cells.copilot.routes import routes_copilot
    hroot = tempfile.mkdtemp(prefix="hd-img-henry-")
    copilot.henry_image_dir = lambda user: os.path.join(hroot, user)
    hn = images.save_tool_images([block()], os.path.join(hroot, "owner"))[0]["name"]
    r = Req(); routes_copilot.chat_image_get(r, {"name": "owner", "role": "owner"}, hn)
    check(r.sent[0] == 200, "Henry's image is served to its own account")
    r = Req(); routes_copilot.chat_image_get(r, {"name": "ops", "role": "operator"}, hn)
    check(r.sent[0] in (403, 404), "another account looks only in ITS folder - the owner's image is unreachable")
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("chat images: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
