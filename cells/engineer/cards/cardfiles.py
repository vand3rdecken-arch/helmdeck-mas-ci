# -*- coding: utf-8 -*-
"""A card's code, as an OUTSIDER may see it (spine/http/mcp.py card_files /
card_read / card_diff / card_propose) - read-only, and only what git knows.

THE FENCE (one place, every outside read goes through visible()):
  - only files git TRACKS or would track (ls-files --cached --others
    --exclude-standard): everything .gitignore'd - settings.json, users.json,
    helmdeck.db, tokens, node_modules, build output - does not exist here.
  - plus a denylist for secrets that are sometimes committed by mistake
    (.env*, *.pem, *.key, id_rsa*, credentials/secrets files, .netrc/.npmrc).
  - a path is matched against that set EXACTLY (no '..', no absolute paths,
    no symlink escapes: the file is opened at the resolved path only if it
    still lies inside the tree).

The tree is the card's working tree: its worktree, or for a build-in-place
card the repo itself (t.worktree or t.repo - turnrunner's rule).

WRITES never happen here. A proposal (propose()) is only CHECKED against the
tree (git apply --check, nothing touched) and handed to the card's own worker
as a steer: the worker - the one owner of that tree - applies what is sound,
and the work lands through the card's gate and review like any other
(gate-before-review, CLAUDE.md laws).
"""
import fnmatch
import os
import subprocess

from spine.git.gitutil import _git_try

MAX_FILES = 3000
MAX_READ = 200 * 1024
MAX_DIFF = 300 * 1024
MAX_PATCH = 60 * 1024
DENY = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
        "credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml",
        ".netrc", ".npmrc", ".pypirc", "*.sqlite", "*.db", "*.db-wal", "*.db-shm")


def tree_of(t):
    return (t or {}).get("worktree") or (t or {}).get("repo") or ""


def _denied(path):
    name = path.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatch(name, pat) for pat in DENY)


def visible(t):
    """The set of repo-relative paths an outsider may see, or None."""
    root = tree_of(t)
    if not root or not os.path.isdir(root):
        return None
    rc, out, _ = _git_try(root, "ls-files", "--cached", "--others", "--exclude-standard")
    if rc != 0:
        return None
    return {p for p in out.splitlines() if p and not _denied(p)}


def files(t, prefix=""):
    """Sorted visible paths (optionally under `prefix`), capped."""
    vis = visible(t)
    if vis is None:
        raise ValueError("this card has no readable code tree")
    prefix = (prefix or "").strip().lstrip("/").replace("\\", "/")
    out = sorted(p for p in vis if not prefix or p.startswith(prefix))
    return {"files": out[:MAX_FILES], "total": len(out), "truncated": len(out) > MAX_FILES}


def read(t, path, offset=0, limit=MAX_READ):
    vis = visible(t)
    if vis is None:
        raise ValueError("this card has no readable code tree")
    path = (path or "").strip().lstrip("/").replace("\\", "/")
    if path not in vis:
        # same answer for "ignored", "denied" and "does not exist"
        raise ValueError("no such file in this card: %s" % path)
    root = os.path.realpath(tree_of(t))
    full = os.path.realpath(os.path.join(root, path))
    if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
        raise ValueError("no such file in this card: %s" % path)
    size = os.path.getsize(full)
    limit = max(1, min(int(limit or MAX_READ), MAX_READ))
    offset = max(0, int(offset or 0))
    with open(full, "rb") as f:
        f.seek(offset)
        raw = f.read(limit)
    if b"\x00" in raw[:8000]:
        return {"path": path, "size": size, "binary": True, "text": ""}
    return {"path": path, "size": size, "offset": offset,
            "text": raw.decode("utf-8", "replace"), "more": offset + len(raw) < size}


def diff(t):
    """What this card changed: commits on its branch since its base, plus
    uncommitted edits. Build-in-place cards have no branch of their own, so
    only their uncommitted edits show (turnrunner's 'known ceiling')."""
    root = tree_of(t)
    if not root or not os.path.isdir(root):
        raise ValueError("this card has no readable code tree")
    parts = []
    base, branch = t.get("base_branch"), t.get("branch")
    if t.get("worktree") and base and branch:
        rc, committed, _ = _git_try(root, "diff", "%s...HEAD" % base)
        if rc == 0 and committed:
            parts.append(committed)
    rc, dirty, _ = _git_try(root, "diff", "HEAD")
    if rc == 0 and dirty:
        parts.append(dirty)
    text = "\n".join(parts)
    # never ship a hunk of a denied file
    keep, skip = [], False
    for line in text.splitlines():
        if line.startswith("diff --git "):
            p = line.split(" b/", 1)[-1]
            skip = _denied(p)
        if not skip:
            keep.append(line)
    text = "\n".join(keep)
    return {"base": base or "HEAD", "diff": text[:MAX_DIFF], "truncated": len(text) > MAX_DIFF}


def check_patch(t, patch):
    """Would this unified diff apply to the card's tree? Touches nothing.
    Returns (ok, message). A patch that touches an invisible/denied path is
    refused before git ever sees it."""
    if not patch or not patch.strip():
        return False, "empty patch"
    if len(patch.encode("utf-8")) > MAX_PATCH:
        return False, "patch too large (max %d KB)" % (MAX_PATCH // 1024)
    vis = visible(t) or set()
    for line in patch.splitlines():
        if line.startswith(("--- ", "+++ ")):
            p = line[4:].strip().split("\t")[0]
            if p == "/dev/null":
                continue
            p = p[2:] if p[:2] in ("a/", "b/") else p
            if ".." in p.split("/") or p.startswith("/") or _denied(p):
                return False, "patch touches a path it may not: %s" % p
            if line.startswith("--- ") and p not in vis:
                return False, "patch edits a file this card does not have: %s" % p
    root = tree_of(t)
    try:
        r = subprocess.run(["git", "-C", root, "apply", "--check", "--whitespace=nowarn", "-"],
                           input=patch.encode("utf-8"), capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, "cannot check the patch: %s" % e
    if r.returncode != 0:
        return False, "patch does not apply: %s" % r.stderr.decode("utf-8", "replace").strip()[:400]
    return True, "applies cleanly"
