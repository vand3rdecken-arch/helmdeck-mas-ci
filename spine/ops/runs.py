# -*- coding: utf-8 -*-
"""Runs: recordings/<run-id>/ holds the MEDIA of a run (video, live frame,
attachments); the run's RECORD is the `runs` row (state-into-db phase F,
2026-09-12; ledger step 9 imported every meta.json). Keep-all retention
(owner decision) - nothing here ever deletes a run."""
import os, time

from daemon.paths import DAEMON_ROOT as ROOT
REC = os.path.join(ROOT, "recordings")


def run_id_of(run_dir):
    """The run's id is its directory name - for a card that is the card id,
    so actions/timeline rows are scoped by exactly the key the card has."""
    return os.path.basename(os.path.normpath(run_dir)) if run_dir else ""


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
    from spine.storage import db
    meta = db.run_get(run_id_of(run_dir))
    if meta is None:
        raise FileNotFoundError("no run record for %s" % run_dir)
    return meta


def _write_meta(run_dir, meta):
    from spine.storage import db
    db.run_put(dict(meta, id=meta.get("id") or run_id_of(run_dir)))


def list_runs():
    from spine.storage import db
    return db.runs_all()
