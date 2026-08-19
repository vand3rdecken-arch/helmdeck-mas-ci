# -*- coding: utf-8 -*-
"""Checkpoints - the program's own undo history. Every time a user changes the
SOFTWARE's configuration (settings/policy edits, connector installs/rollbacks,
template additions), the state as it was BEFORE the change is snapshotted:
settings.json + the connectors/ directory. Restoring a checkpoint first
checkpoints the current state, so restores are themselves reversible and no
version of the workspace is ever lost. Work data (tracks, events, recordings)
is never part of a restore - checkpoints roll back the machine, not history."""
import json, os, shutil, time

from _subpaths import DAEMON_ROOT as ROOT
CPDIR = os.path.join(ROOT, "checkpoints")
os.makedirs(CPDIR, exist_ok=True)
KEEP = 60

def _snapshot_targets():
    return {"settings.json": os.path.join(ROOT, "settings.json"),
            "connectors": os.path.join(ROOT, "connectors")}

def create(actor="system", reason=""):
    cid = time.strftime("%Y%m%d-%H%M%S") + "-%03d" % (int(time.time() * 1000) % 1000)
    d = os.path.join(CPDIR, cid)
    os.makedirs(d, exist_ok=True)
    for name, src in _snapshot_targets().items():
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(d, name),
                            ignore=shutil.ignore_patterns("_versions", "__pycache__"))
        elif os.path.exists(src):
            shutil.copy2(src, os.path.join(d, name))
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

def _read_settings(dpath):
    try:
        with open(os.path.join(dpath, "settings.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def _flat(d, prefix=""):
    """Flatten nested settings to dotted keys so a change reads like
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

def diff(cid):
    """What actually changed AT this checkpoint. A checkpoint holds the state
    BEFORE its change; the 'after' is the next checkpoint's snapshot, or the
    live settings if this is the most recent one. Returns per-field
    before -> after plus connector files added/removed."""
    cid = os.path.basename(cid)
    cids = sorted(os.listdir(CPDIR))            # chronological, oldest first
    if cid not in cids:
        raise RuntimeError("no such checkpoint: " + cid)
    idx = cids.index(cid)
    after_dir = os.path.join(CPDIR, cids[idx + 1]) if idx + 1 < len(cids) else ROOT
    before, after = _read_settings(os.path.join(CPDIR, cid)), _read_settings(after_dir)
    fb, fa = _flat(before), _flat(after)
    fields = [{"key": k, "before": fb.get(k), "after": fa.get(k)}
              for k in sorted(set(fb) | set(fa)) if fb.get(k) != fa.get(k)]
    cb, ca = _conn_files(os.path.join(CPDIR, cid)), _conn_files(after_dir)
    return {"id": cid, "settings": fields,
            "connectors": {"added": sorted(ca - cb), "removed": sorted(cb - ca)}}

def restore(cid, actor="owner"):
    """Roll the workspace config back to this checkpoint. Current state is
    checkpointed first - a restore can always be un-restored."""
    src = os.path.join(CPDIR, os.path.basename(cid))
    if not os.path.isdir(src):
        raise RuntimeError("no such checkpoint: " + cid)
    create(actor=actor, reason="pre-restore of " + cid)
    for name, dst in _snapshot_targets().items():
        s = os.path.join(src, name)
        if os.path.isdir(s):
            for f in os.listdir(s):
                shutil.copy2(os.path.join(s, f), os.path.join(dst, f))
        elif os.path.exists(s):
            shutil.copy2(s, dst)
    import events
    events.emit("checkpoint", "-", action="restored", checkpoint=cid, actor=actor)
    return cid
