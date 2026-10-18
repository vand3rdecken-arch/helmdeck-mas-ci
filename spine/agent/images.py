# -*- coding: utf-8 -*-
"""Images in the chat (owner 2026-10-18: "chat kann keine Bilder, screenshot etc zeigen").

Claude returns an image a tool produced or read (a screenshot, a Read on a .png) as a base64 `image` block
inside the tool_result. The stream parsers kept only the text blocks, so every image was dropped. Here an
image block becomes a FILE (the shape Paseo, Open WebUI and text-generation-webui settled on - base64 kept
inline makes long histories slow), named by its content hash so a repeated screenshot is stored once, and
the timeline / chat gets a small `image` item that points at it.

Serving is JSON (`{mime, data}`), not raw bytes: the phone reaches the daemon only through the E2EE relay,
whose envelope carries a JSON body - the same reason Paseo reads images through its file RPC.
"""
import base64
import hashlib
import os

ALLOWED = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
MAX_BYTES = 4 * 1024 * 1024          # per image; a bigger one is skipped, never truncated
MAX_PER_RESULT = 8
DIR = ".attachments"                  # next to the card's user attachments


def blocks(content):
    """The image blocks of a tool_result `content` (a list of typed blocks; a str has none)."""
    if not isinstance(content, list):
        return []
    out = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "image":
            out.append(b)
        elif isinstance(b, dict) and b.get("type") == "tool_result":      # nested results (MCP wrappers)
            out.extend(blocks(b.get("content")))
    return out


def save_tool_images(content, base_dir):
    """Write every image block of a tool_result to base_dir/.attachments as img-<sha16><ext>.
    Returns [{"name", "mime", "bytes"}]. Best-effort: a malformed block is skipped, never raised."""
    saved = []
    for b in blocks(content)[:MAX_PER_RESULT]:
        src = b.get("source") or {}
        mime = (src.get("media_type") or "").lower()
        if src.get("type") != "base64" or mime not in ALLOWED:
            continue
        try:
            raw = base64.b64decode(src.get("data") or "", validate=False)
        except Exception:                                    # noqa: BLE001
            continue
        if not raw or len(raw) > MAX_BYTES:
            continue
        name = "img-%s%s" % (hashlib.sha256(raw).hexdigest()[:16], ALLOWED[mime])
        out_dir = os.path.join(base_dir, DIR)
        try:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, name)
            if not os.path.exists(path):
                with open(path, "wb") as f:
                    f.write(raw)
        except OSError:
            continue
        saved.append({"name": name, "mime": mime, "bytes": len(raw)})
    return saved


def read_image(base_dir, name):
    """{mime, data} for an image stored by save_tool_images (or a user attachment) under base_dir/.attachments,
    or None. The name must be a bare file name inside that folder - no path escape - with an image type."""
    if not name or os.path.basename(name) != name or name.startswith("."):
        return None
    ext = os.path.splitext(name)[1].lower()
    mime = next((m for m, e in ALLOWED.items() if e == ext), None) or ("image/jpeg" if ext == ".jpeg" else None)
    if not mime:
        return None
    root = os.path.realpath(os.path.join(base_dir, DIR))
    path = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(path) != root or not os.path.isfile(path):
        return None
    if os.path.getsize(path) > MAX_BYTES * 2:
        return None
    with open(path, "rb") as f:
        return {"mime": mime, "data": base64.b64encode(f.read()).decode("ascii")}
