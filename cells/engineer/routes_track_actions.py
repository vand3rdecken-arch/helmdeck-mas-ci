# -*- coding: utf-8 -*-
"""Track ACTION routes - the gate/dispatch-critical half of the tracks
cluster (see routes_tracks.py for the CRUD/read half; both are the 14th
slice of server.py's dispatch-table split, pattern from routes_auth.py).

These sit directly on sessions.py's gate/merge state machine
(lanemachine.py's move_lane -> _gate -> _merge_to_main - "the crown jewel"),
so they were kept in their OWN module and given extra end-to-end test
coverage rather than folded into routes_tracks.py: GET /tracks/<id>/stream
(live transcript SSE), POST /tracks/<id>/steer, /answer, /cancel, /lane.

Path-param routes keep their guard inline in server.py (same precedent as
routes_checkpoints.py) - only the route BODY moves here, verbatim. Bodies
are byte-identical to the inline blocks they replace.
"""
import json


def tracks_stream_get(self, user, tid):
    # per-card SSE: push the live turn transcript as the agent works. The
    # driver folds the timeline_store live as the agent works (Card 2), so we
    # watch ITS version and emit whenever it grows - real streaming, no
    # client poll, same shape as the board /stream above.
    import time as _t
    from cells.engineer import sessions
    from spine.agent import claude_sessions
    t = sessions.get_track(tid)
    if user["role"] == "client" and (not t or t.get("client") != user["name"]):
        return self._send(403, json.dumps({"error": "not your card"}))
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.end_headers()

    # Tick whenever the session .jsonl grows, the driver's
    # live_partial.txt grows (token streaming within a block, before
    # it's flushed to the .jsonl), OR the flight recorder gets a
    # lifecycle note. ONE token for both live paths - SSE and the
    # relay long-poll must agree on what "changed" means, or the
    # web feed silently misses what the phone gets. session_id is
    # resolved fresh inside so streaming starts on turn 1 (sidecar)
    # too. The client refetches the transcript on each tick.
    def combined():
        # Card 2 cutover: the client refetches /transcript on each tick, and
        # that route now serves timeline_store - this must watch the SAME
        # source's version, or SSE and the endpoint it triggers a refetch of
        # disagree about what "changed" means (see routes_tracks.py).
        return claude_sessions.transcript_store_version(t)

    def tick(v):
        self.wfile.write(("data: %d" % v).encode() + b"\n\n")
        self.wfile.flush()
    try:
        last = combined()
        tick(last)
        idle = 0
        while True:
            _t.sleep(0.3)
            size = combined()
            if size != last:
                last = size
                tick(size)
                idle = 0
            elif (idle := idle + 1) >= 45:   # ~13.5s keep-alive
                self.wfile.write(b": ping\n\n"); self.wfile.flush(); idle = 0
    except (ConnectionAbortedError, BrokenPipeError, OSError):
        return


def tracks_steer_post(self, user, body, tid):
    from cells.engineer import sessions
    text = body.get("text")
    if not text:
        return self._send(400, json.dumps({"error": "text required"}))
    if user["role"] == "client":
        t = sessions.get_track(tid)
        if not t or t.get("client") != user["name"]:
            return self._send(403, json.dumps({"error": "not your card"}))
    actor = user["name"]
    model = body.get("model", "")
    thinking = body.get("thinking", "")          # level string, "" = off
    attachments = body.get("attachments")
    # clients steer their own card but can't escalate the permission mode
    mode = body.get("mode") if user["role"] != "client" else None
    from spine.http import server
    server._bg("track:steer:" + tid, lambda: sessions.steer(
        tid, text, actor=actor, model=model, thinking=thinking,
        attachments=attachments, mode=mode))
    return self._send(200, json.dumps({"started": tid}))


def tracks_answer_post(self, user, body, tid):
    # Phase 2.4: the owner picks an option on the worker's pending
    # question. Backgrounded like /steer - it RUNS a turn (the
    # worker continues with the decision), so holding the request
    # would block the phone for the length of that turn.
    from cells.engineer import sessions
    if user["role"] == "client":
        t = sessions.get_track(tid)
        if not t or t.get("client") != user["name"]:
            return self._send(403, json.dumps({"error": "not your card"}))
    t = sessions.get_track(tid)
    if not t or not t.get("question"):
        return self._send(409, json.dumps({"error": "no pending question"}))
    # validate BEFORE backgrounding, so a bad/stale answer reports
    # the reason instead of failing invisibly on a worker thread
    from spine.ops import ask
    rid = body.get("request_id", "")
    if rid and rid != (t["question"] or {}).get("id"):
        return self._send(409, json.dumps(
            {"error": "this question was already answered or replaced"}))
    picks, err = ask.validate_answers(t["question"], body.get("answers") or {})
    if err:
        return self._send(400, json.dumps({"error": err}))
    actor = user["name"]
    answers = body.get("answers") or {}
    from spine.http import server
    server._bg("track:answer:" + tid, lambda: sessions.answer_question(
        tid, answers, request_id=rid, actor=actor))
    return self._send(200, json.dumps({"started": tid, "answered": True}))


def tracks_cancel_post(self, user, body, tid):
    from cells.engineer import sessions
    if user["role"] == "client":
        t = sessions.get_track(tid)
        if not t or t.get("client") != user["name"]:
            return self._send(403, json.dumps({"error": "not your card"}))
    return self._send(200, json.dumps(sessions.cancel_turn(tid, actor=user["name"])))


def tracks_lane_post(self, user, body, tid):
    from cells.engineer import sessions
    lane = body.get("lane")
    actor = user["name"]
    from spine.http import server
    if lane == "working":
        server._bg("track:dispatch:" + tid,
            lambda: sessions.move_lane(tid, "working", actor=actor))
        return self._send(200, json.dumps({"started": tid}))
    if lane in ("review", "done"):
        # Gate (subprocess, up to 600s) + merge + deploy hook. Held
        # inline this blocked the HTTP request for minutes, which is
        # what made an accept feel like invisible background work.
        # Background it like ->working; the card carries status
        # "gating" and every outcome is reported on the card, in the
        # chat (sessions._say_card) and by push.
        server._bg("track:gate:" + tid,
            lambda: sessions.move_lane(tid, lane, actor=actor))
        return self._send(200, json.dumps({"started": tid, "gating": True}))
    return self._send(200, json.dumps(sessions.move_lane(tid, lane, actor=actor)))
