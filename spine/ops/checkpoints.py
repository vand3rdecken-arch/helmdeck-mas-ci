# -*- coding: utf-8 -*-
"""Checkpoints - the program's own undo history. Every time a user changes the
SOFTWARE's configuration (settings/policy edits, connector installs/rollbacks,
template additions), the state as it was BEFORE the change is snapshotted:
the workspace CONFIG rows (workspace_config + the live policy_doc) and the
connectors/ directory. Restoring a checkpoint first checkpoints the current
state, so restores are themselves reversible and no version of the workspace
is ever lost. Work data (tracks, events, recordings) is never part of a
restore - checkpoints roll back the machine, not history.

SHAPE (kept, by decision - debt order 32): a checkpoint IS a directory
snapshot (recordings-style artifact), because half of it is a copytree of
connectors/ - code files that importlib loads. What CHANGED in state-into-db
phase G (2026-09-12): the config half. It used to copy daemon/settings.json,
which config-consolidation phase 2 stopped writing on 2026-09-03 - so every
checkpoint since silently held NO config and diff()/restore() rolled back
nothing but connectors. The config is read from its store now (the db rows)
into <checkpoint>/config.json, and restore() writes those rows back."""
import json, os, shutil, time
from daemon.paths import DAEMON_ROOT as ROOT
CPDIR = os.path.join(ROOT, "checkpoints")
os.makedirs(CPDIR, exist_ok=True)
KEEP = 60


def _connectors_dir():
    return os.path.join(ROOT, "connectors")


def _live_config():
    """The workspace config as it is RIGHT NOW: every workspace_config row plus
    the live policy document - the exact rows a restore writes back."""
    from spine.storage import db
    return {"workspace_config": db.workspace_config_all(),
            "policy_doc": db.policy_doc_get()}


def create(actor="system", reason=""):
    cid = time.strftime("%Y%m%d-%H%M%S") + "-%03d" % (int(time.time() * 1000) % 1000)
    d = os.path.join(CPDIR, cid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
        json.dump(_live_config(), f, ensure_ascii=False, indent=1)
    src = _connectors_dir()
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(d, "connectors"),
                        ignore=shutil.ignore_patterns("_versions", "__pycache__"))
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"id": cid, "actor": actor, "reason": reason[:200],
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    _prune()
    return cid


def _prune():
    cps = sorted(os.listdir(CPDIR))
    for old in cps[:-KEEP]:
        shutil.rmtree(os.path.join(CPDIR, old), ignore_errors=True)


def list_checkpoints():
    out = []
    for cid in sorted(os.listdir(CPDIR), reverse=True):
        mp = os.path.join(CPDIR, cid, "meta.json")
        try:
            with open(mp, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            pass
    return out[:KEEP]


def _read_config(dpath):
    """A checkpoint's config snapshot as ONE flat-able dict: the workspace
    rows plus the policy document under 'policy_doc'."""
    try:
        with open(os.path.join(dpath, "config.json"), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    out = dict(doc.get("workspace_config") or {})
    if doc.get("policy_doc") is not None:
        out["policy_doc"] = doc["policy_doc"]
    return out


def _flat(d, prefix=""):
    """Flatten nested config to dotted keys so a change reads like
    'appearance.backdrop'. Lists/scalars are leaves."""
    out = {}
    for k, v in (d or {}).items():
        key = prefix + str(k)
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def _conn_files(dpath):
    c = os.path.join(dpath, "connectors")
    if not os.path.isdir(c):
        return set()
    skip = {"__pycache__", "_versions", "_state.json"}   # noise, not connectors
    return {f for f in os.listdir(c) if f not in skip}


def _live_as_dir_view():
    """The live state in the same shape a checkpoint dir yields."""
    cfg = dict(_live_config()["workspace_config"])
    pd = _live_config()["policy_doc"]
    if pd is not None:
        cfg["policy_doc"] = pd
    return cfg


def diff(cid):
    """What actually changed AT this checkpoint. A checkpoint holds the state
    BEFORE its change; the 'after' is the next checkpoint's snapshot, or the
    live config if this is the most recent one. Returns per-field
    before -> after plus connector files added/removed."""
    cid = os.path.basename(cid)
    cids = sorted(os.listdir(CPDIR))            # chronological, oldest first
    if cid not in cids:
        raise RuntimeError("no such checkpoint: " + cid)
    idx = cids.index(cid)
    before = _read_config(os.path.join(CPDIR, cid))
    if idx + 1 < len(cids):
        after_dir = os.path.join(CPDIR, cids[idx + 1])
        after, ca = _read_config(after_dir), _conn_files(after_dir)
    else:
        after, ca = _live_as_dir_view(), _conn_files(ROOT)
    fb, fa = _flat(before), _flat(after)
    fields = [{"key": k, "before": fb.get(k), "after": fa.get(k)}
              for k in sorted(set(fb) | set(fa)) if fb.get(k) != fa.get(k)]
    cb = _conn_files(os.path.join(CPDIR, cid))
    return {"id": cid, "settings": fields,
            "connectors": {"added": sorted(ca - cb), "removed": sorted(cb - ca)}}


def restore(cid, actor="owner"):
    """Roll the workspace config back to this checkpoint. Current state is
    checkpointed first - a restore can always be un-restored."""
    src = os.path.join(CPDIR, os.path.basename(cid))
    if not os.path.isdir(src):
        raise RuntimeError("no such checkpoint: " + cid)
    create(actor=actor, reason="pre-restore of " + cid)
    try:
        with open(os.path.join(src, "config.json"), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict):
        from spine.storage import db
        if isinstance(doc.get("workspace_config"), dict):
            db.workspace_config_replace(doc["workspace_config"])
        if isinstance(doc.get("policy_doc"), dict):
            db.policy_doc_put(doc["policy_doc"])
    s = os.path.join(src, "connectors")
    if os.path.isdir(s):
        dst = _connectors_dir()
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(s):
            shutil.copy2(os.path.join(s, f), os.path.join(dst, f))
    from spine.storage import events
    events.emit("checkpoint", "-", action="restored", checkpoint=cid, actor=actor)
    return cid
