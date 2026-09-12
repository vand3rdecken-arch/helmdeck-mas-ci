# -*- coding: utf-8 -*-
"""The always-on action timeline. One append-only record stream per run; every
actor (agent wrapper, teach-mode hooks, windows driver) appends timestamped
steps through this. The timeline is the PRIMARY review artifact - video is
drill-down evidence keyed to these timestamps.

STORE (state-into-db phase F, 2026-09-12): the `actions` table, scoped by
run_id = the run directory's basename (a card's id). Ledger step 9 imported
every recordings/<run>/actions.jsonl. The old writer recreated the run dir
before each append because an external wipe of recordings/ once bricked
every affected card with FileNotFoundError - a row append has no directory
to lose."""
import time, threading

from spine.ops.runs import run_id_of


class ActionLog:
    def __init__(self, run_dir):
        self.run_dir = run_dir
        self.run_id = run_id_of(run_dir)
        self.t0 = time.time()
        self._lock = threading.Lock()
        self._n = 0

    def log(self, kind, detail, **extra):
        """kind: navigate|click|type|key|scroll|focus|shell|read|find|note|flag  detail: human-readable."""
        rec = {"i": self._n, "t": round(time.time() - self.t0, 3),
               "ta": time.time(),          # absolute epoch - the ONLY sound sort
               "ts": time.strftime("%H:%M:%S"), "kind": kind, "detail": detail}
        rec.update(extra)
        with self._lock:
            self._n += 1
        from spine.storage import db
        db.action_append(self.run_id, rec)
        return rec


def read_timeline(run_dir):
    from spine.storage import db
    rid = run_id_of(run_dir)
    return db.actions_for(rid) if rid else []
