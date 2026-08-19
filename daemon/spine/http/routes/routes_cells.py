# -*- coding: utf-8 -*-
"""Cell source-read route - path-param, guard stays inline in server.py per
the routes_checkpoints.py precedent. GET /cells/<id>/source?file=<name>
serves ONE file's real text for the code-map UI (app/src/ui/cell_diagram.tsx),
strictly allowlisted to that cell's own declared metadata (see
daemon/cells.py's Cell.allowed_files()/read_source() - the actual security
boundary lives there, not here)."""
import json
from urllib.parse import parse_qs, urlparse


def cell_source_get(self, user, cid):
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from daemon.spine.registry import cells
    fname = (parse_qs(urlparse(self.path).query).get("file") or [""])[0]
    text = cells.read_source(cid, fname)
    if text is None:
        return self._send(404, json.dumps({"error": "not found"}))
    return self._send(200, json.dumps({"file": fname, "text": text}, ensure_ascii=False))
