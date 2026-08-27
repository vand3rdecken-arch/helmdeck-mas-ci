# -*- coding: utf-8 -*-
"""Run folders: recordings/<run-id>/ with meta.json, actions.jsonl, video files.
Keep-all retention (owner decision) - nothing here ever deletes a run."""
import json, os, time

from daemon.paths import DAEMON_ROOT as ROOT
REC = os.path.join(ROOT, "recordings")

def new_run(kind, title):
    """kind: agent|teach|test"""
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + kind
    d = os.path.join(REC, rid)
    os.makedirs(d, exist_ok=True)
    meta = {"id": rid, "kind": kind, "title": title,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "running"}
    _write_meta(d, meta)
    return rid, d

def finish_run(run_dir, status="done", **extra):
    meta = load_meta(run_dir)
    meta["status"] = status
    meta["ended"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta.update(extra)
    _write_meta(run_dir, meta)

def load_meta(run_dir):
    with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as f:
        return json.load(f)

def _write_meta(run_dir, meta):
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

def list_runs():
    if not os.path.isdir(REC):
        return []
    out = []
    for rid in sorted(os.listdir(REC), reverse=True):
        d = os.path.join(REC, rid)
        if os.path.isfile(os.path.join(d, "meta.json")):
            try: out.append(load_meta(d))
            except Exception: pass
    return out
