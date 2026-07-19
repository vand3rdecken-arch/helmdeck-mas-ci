# -*- coding: utf-8 -*-
"""Local review/index server. The APK (the brain) pulls from here over LAN:
  /runs                     index of all runs (meta + step counts)
  /runs/<id>/timeline       the action timeline (JSON)
  /runs/<id>/video          screen.mp4 or browser.webm (Range supported by SimpleHTTP? no —
                            fine for v1: full-file; APK downloads then plays locally)
  /runs/<id>/playbook       playbook.md if distilled
  /live.jpg                 newest frame of the ACTIVE run (glance feed)
  /                         human review UI: timeline-first, video drill-down
"""
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from actionlog import read_timeline
from runs import REC, list_runs

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
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass

def serve(port=8140):
    print("SwarmDeck review server on http://localhost:%d  (APK pulls /runs, /live.jpg)" % port)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()

if __name__ == "__main__":
    serve()
