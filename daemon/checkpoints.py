# -*- coding: utf-8 -*-
"""Checkpoints - the program's own undo history. Every time a user changes the
SOFTWARE's configuration (settings/policy edits, connector installs/rollbacks,
template additions), the state as it was BEFORE the change is snapshotted:
settings.json + the connectors/ directory. Restoring a checkpoint first
checkpoints the current state, so restores are themselves reversible and no
version of the workspace is ever lost. Work data (tracks, events, recordings)
is never part of a restore - checkpoints roll back the machine, not history."""
import json, os, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
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
