# -*- coding: utf-8 -*-
"""Local review/index + CONTROL server. The APK is a full-capability client (owner
decision: mobile = same capabilities), so besides pulling it can drive:

  GET  /runs, /runs/<id>/timeline, /runs/<id>/video, /runs/<id>/playbook, /live.jpg, /
  POST /control/teach/start   {"title": "..."}      arm a demo recording on the PC
  POST /control/teach/stop                          finalize it (phone stop button)
  POST /control/distill       {"id": "<run-id>"}    demo -> playbook (background)
  POST /control/demo                                scripted browser demo run (background)
  GET  /control/state                               {"teach": <run-id>|null, "busy": [...]}
"""
import json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from actionlog import read_timeline
from runs import REC, list_runs

_ctl = {"teach": None, "busy": []}   # current TeachSession + background job names
_ctl_lock = threading.Lock()

def _bg(name, fn):
    """Run a control job in the background; the phone polls /control/state."""
    def wrap():
        try: fn()
        finally:
            with _ctl_lock:
                if name in _ctl["busy"]:
                    _ctl["busy"].remove(name)
    with _ctl_lock:
        _ctl["busy"].append(name)
    threading.Thread(target=wrap, daemon=True).start()

def _active_live():
    for m in list_runs():
        if m.get("status") == "running":
            p = os.path.join(REC, m["id"], "live.jpg")
            if os.path.exists(p):
                return p
    return None

PAGE = """<!doctype html><meta charset=utf-8><title>SwarmDeck review</title>
<style>body{font:15px/1.5 system-ui;background:#0b0f14;color:#dfe9f2;margin:0;padding:24px}
h1{color:#7ef0b2}.run{border:1px solid #24303c;border-radius:10px;padding:12px 16px;margin:12px 0}
.k{color:#8fb6d9;font-family:monospace}.steps{margin:8px 0 0;padding-left:0;list-style:none}
.steps li{padding:2px 0;border-left:3px solid #24303c;padding-left:10px;margin:2px 0;font-family:monospace;font-size:13px}
.steps li.flag{border-color:#ffd166;background:#2a2410}.t{color:#5d7284;margin-right:8px}
video{max-width:640px;display:block;margin-top:8px}</style>
<h1>SwarmDeck — runs</h1><div id=out>loading…</div>
<script>
fetch('/runs').then(r=>r.json()).then(async runs=>{
  const out=document.getElementById('out');out.innerHTML='';
  if(!runs.length){out.textContent='No runs yet — record a demo (swarm.py teach) or start a task (swarm.py browser-demo).';return}
  for(const m of runs){
    const d=document.createElement('div');d.className='run';
    const tl=await fetch('/runs/'+m.id+'/timeline').then(r=>r.json()).catch(()=>[]);
    d.innerHTML='<b>'+m.title+'</b> <span class=k>'+m.id+' · '+m.kind+' · '+m.status+' · '+tl.length+' steps</span>'
      +'<ul class=steps>'+tl.map(s=>'<li'+(s.kind==='flag'?' class=flag':'')+'><span class=t>'
      +s.t.toFixed(1)+'s</span>'+s.kind+' — '+s.detail+'</li>').join('')+'</ul>'
      +'<video controls preload=none src="/runs/'+m.id+'/video"></video>';
    out.appendChild(d)}
});
</script>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode("utf-8"))

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if p == "/runs":
                runs = list_runs()
                for m in runs:
                    m["steps"] = len(read_timeline(os.path.join(REC, m["id"])))
                return self._send(200, json.dumps(runs))
            if p == "/live.jpg":
                lp = _active_live()
                if not lp:
                    return self._send(404, b"no active run", "text/plain")
                with open(lp, "rb") as f:
                    return self._send(200, f.read(), "image/jpeg")
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "runs":
                rid, what = parts[1], parts[2]
                d = os.path.join(REC, os.path.basename(rid))
                if what == "timeline":
                    return self._send(200, json.dumps(read_timeline(d)))
                if what == "playbook":
                    fp = os.path.join(d, "playbook.md")
                    if os.path.exists(fp):
                        with open(fp, "rb") as f:
                            return self._send(200, f.read(), "text/markdown; charset=utf-8")
                    return self._send(404, b"not distilled", "text/plain")
                if what == "video":
                    for name, ct in (("screen.mp4", "video/mp4"), ("browser.webm", "video/webm")):
                        fp = os.path.join(d, name)
                        if os.path.exists(fp):
                            with open(fp, "rb") as f:
                                return self._send(200, f.read(), ct)
                    return self._send(404, b"no video", "text/plain")
            if p == "/control/state":
                with _ctl_lock:
                    s = _ctl["teach"]
                    return self._send(200, json.dumps(
                        {"teach": s.rid if s and not s.stopped.is_set() else None,
                         "busy": list(_ctl["busy"])}))
            # --- orchestrator: branches/sessions (the Paseo half) ---
            if p == "/tracks":
                import sessions
                return self._send(200, json.dumps(sessions.list_tracks()))
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "history":
                import sessions
                return self._send(200, json.dumps(sessions.history(parts[1])))
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            body = {}
        try:
            if p == "/control/teach/start":
                from teach import TeachSession
                with _ctl_lock:
                    if _ctl["teach"] and not _ctl["teach"].stopped.is_set():
                        return self._send(409, json.dumps({"error": "already recording",
                                                           "id": _ctl["teach"].rid}))
                    s = TeachSession(body.get("title") or "unnamed task").start()
                    _ctl["teach"] = s
                return self._send(200, json.dumps({"id": s.rid}))
            if p == "/control/teach/stop":
                with _ctl_lock:
                    s = _ctl["teach"]
                if not s:
                    return self._send(404, json.dumps({"error": "not recording"}))
                rid = s.stop()
                return self._send(200, json.dumps({"id": rid}))
            if p == "/control/distill":
                rid = os.path.basename(body.get("id") or "")
                if not rid:
                    return self._send(400, json.dumps({"error": "id required"}))
                from distill import distill
                _bg("distill:" + rid, lambda: distill(rid))
                return self._send(200, json.dumps({"started": rid}))
            if p == "/control/demo":
                import swarm
                _bg("demo", swarm.browser_demo)
                return self._send(200, json.dumps({"started": "browser-demo"}))
            # --- orchestrator control ---
            if p == "/tracks/new":
                import sessions
                repo = body.get("repo"); branch = body.get("branch"); task = body.get("task")
                if not (repo and branch and task):
                    return self._send(400, json.dumps({"error": "repo, branch, task required"}))
                out = {}
                def go():
                    out["t"] = sessions.new_track(repo, branch, task,
                                                  body.get("perm", sessions.DEFAULT_PERM))
                _bg("track:new:" + branch, go)
                return self._send(200, json.dumps({"started": branch}))
            if len(p.strip("/").split("/")) == 3 and p.strip("/").split("/")[2] == "steer":
                import sessions
                tid = p.strip("/").split("/")[1]
                text = body.get("text")
                if not text:
                    return self._send(400, json.dumps({"error": "text required"}))
                _bg("track:steer:" + tid, lambda: sessions.steer(tid, text))
                return self._send(200, json.dumps({"started": tid}))
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

def serve(port=8140):
    print("SwarmDeck review server on http://localhost:%d  (APK pulls /runs, /live.jpg)" % port)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()

if __name__ == "__main__":
    serve()
