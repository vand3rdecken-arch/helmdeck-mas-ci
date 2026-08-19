# -*- coding: utf-8 -*-
"""Run/recording routes - Nth slice of server.py's dispatch-table split (see
routes_auth.py for the pattern/rationale). GET /runs (list), GET /live.jpg
(current live frame), and the /runs/<id>/{timeline,playbook,video,videochunk}
path-param sub-router (parts[0]=="runs" guard stays inline in server.py per
the /processes/<id>/step and routes_checkpoints.py precedent - only the route
BODY moves here, verbatim, as one dispatcher keyed on `what`). Bodies are
byte-identical to the inline blocks they replace.
"""
import json, os
from urllib.parse import parse_qs, urlparse
from actionlog import read_timeline
from runs import REC, list_runs


def runs_get(self, user):
    runs = list_runs()
    for m in runs:
        m["steps"] = len(read_timeline(os.path.join(REC, m["id"])))
    return self._send(200, json.dumps(runs))


def live_jpg_get(self, user):
    import server
    lp = server._active_live()
    if not lp:
        return self._send(404, b"no active run", "text/plain")
    with open(lp, "rb") as f:
        return self._send(200, f.read(), "image/jpeg")


def runs_item_get(self, user, rid, what):
    # Returns True if `what` was a recognized sub-route (response already
    # sent), False otherwise - server.py's caller only falls through to the
    # rest of the if-chain on False, matching the original inline behaviour
    # (self._send() itself returns None, so that can't double as the signal).
    d = os.path.join(REC, os.path.basename(rid))
    if what == "timeline":
        self._send(200, json.dumps(read_timeline(d)))
        return True
    if what == "playbook":
        fp = os.path.join(d, "playbook.md")
        if os.path.exists(fp):
            with open(fp, "rb") as f:
                self._send(200, f.read(), "text/markdown; charset=utf-8")
            return True
        self._send(404, b"not distilled", "text/plain")
        return True
    if what == "video":
        for name, ct in (("screen.mp4", "video/mp4"), ("browser.webm", "video/webm")):
            fp = os.path.join(d, name)
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    self._send(200, f.read(), ct)
                return True
        self._send(404, b"no video", "text/plain")
        return True
    if what == "videochunk":
        # Ranged, base64-in-JSON slices of the recording. The mobile
        # app reaches the daemon through an end-to-end encrypted
        # relay that carries TEXT frames, so a raw binary stream
        # cannot pass; slicing keeps recordings watchable on the
        # phone without weakening the tunnel or loading a whole
        # video into memory.
        import base64 as _b64, transcode
        q = parse_qs(urlparse(self.path).query)
        try:
            off = max(0, int((q.get("offset") or ["0"])[0]))
            ln = int((q.get("len") or ["262144"])[0])
        except ValueError:
            self._send(400, json.dumps({"error": "bad offset/len"}))
            return True
        ln = max(1, min(ln, 1_048_576))          # 1 MiB ceiling per slice
        # A phone or a 600x600 glasses display cannot use a full
        # desktop capture; serving a small rendition cuts the bytes
        # that have to cross the relay by roughly an order of
        # magnitude. Made once on THIS machine, then cached.
        profile = (q.get("profile") or ["mobile"])[0]
        for name, ct in (("screen.mp4", "video/mp4"), ("browser.webm", "video/webm")):
            fp = os.path.join(d, name)
            if not os.path.exists(fp):
                continue
            fp = transcode.variant(fp, profile)
            if fp.endswith(".mp4"):
                ct = "video/mp4"
            size = os.path.getsize(fp)
            with open(fp, "rb") as f:
                f.seek(off)
                blob = f.read(ln)
            self._send(200, json.dumps({
                "size": size, "mime": ct, "offset": off,
                "profile": profile, "scaled": transcode.available(),
                "eof": off + len(blob) >= size,
                "data": _b64.b64encode(blob).decode()}))
            return True
        self._send(404, json.dumps({"error": "no video"}))
        return True
    return False


GET_ROUTES = {
    "/runs": runs_get,
    "/live.jpg": live_jpg_get,
}
