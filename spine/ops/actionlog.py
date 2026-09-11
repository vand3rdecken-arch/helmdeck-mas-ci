# -*- coding: utf-8 -*-
"""The always-on action timeline. One JSONL file per run; every actor (agent wrapper,
teach-mode hooks, windows driver) appends timestamped steps through this. The timeline is
the PRIMARY review artifact - video is drill-down evidence keyed to these timestamps."""
import json, os, time, threading

class ActionLog:
    def __init__(self, run_dir):
        self.run_dir = run_dir
        self.path = os.path.join(run_dir, "actions.jsonl")
        self.t0 = time.time()
        self._lock = threading.Lock()
        self._n = 0

    def log(self, kind, detail, **extra):
        """kind: navigate|click|type|key|scroll|focus|shell|read|find|note|flag  detail: human-readable."""
        rec = {"i": self._n, "t": round(time.time() - self.t0, 3),
               "ta": time.time(),          # absolute epoch — the ONLY sound sort
               "ts": time.strftime("%H:%M:%S"), "kind": kind, "detail": detail}
        rec.update(extra)
        with self._lock:
            self._n += 1
            # run_dir can go missing out from under a live card (an external
            # wipe of daemon/recordings/, found live 2026-08-27: every steer/
            # answer/lane-move on an affected card crashed here with
            # FileNotFoundError instead of degrading, silently bricking the
            # card). Recreate it rather than let a housekeeping gap turn into
            # a dead card - this file is the primary review artifact, so
            # losing a write here is worse than a redundant makedirs.
            os.makedirs(self.run_dir, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

def read_timeline(run_dir):
    path = os.path.join(run_dir, "actions.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: out.append(json.loads(line))
                except ValueError: pass
    return out
