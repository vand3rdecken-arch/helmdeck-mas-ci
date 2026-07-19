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

BOARD = """<!doctype html><meta charset=utf-8><title>SwarmDeck board</title>
<style>
body{font:14px/1.45 system-ui;background:#0b0f14;color:#dfe9f2;margin:0;padding:18px 20px}
h1{color:#7ef0b2;font-size:20px;margin:0 0 4px} .hint{color:#5d7488;font-size:12px;margin:0 0 14px}
#board{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;align-items:start}
.lane{background:#0e151d;border:1px solid #22303d;border-radius:12px;padding:10px;min-height:220px}
.lane h2{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#8fb0c9;margin:2px 4px 10px}
.lane h2 .n{color:#5d7488;font-weight:400}
.lane.drag{outline:2px dashed #2affc0;outline-offset:-4px}
.card{background:#111a24;border:1px solid #24303c;border-left:3px solid #6fb2e8;border-radius:9px;
      padding:9px 11px;margin-bottom:9px;cursor:grab}
.card.needs{border-left-color:#ffd166}.card.run{border-left-color:#6fb2e8}
.card.sub{border-left-color:#b78ef7}.card.acc{border-left-color:#2affc0}.card.q{border-left-color:#5d7488}
.card b{display:block;font-size:13.5px;margin-bottom:2px}
.card .m{font:11px ui-monospace,monospace;color:#5d7488}
.card .r{font-size:12px;color:#8fb0c9;margin-top:5px;max-height:54px;overflow:hidden}
#drawer{position:fixed;top:0;right:-560px;width:540px;height:100%;background:#0e151d;
        border-left:1px solid #22303d;transition:right .2s;padding:18px;box-sizing:border-box;
        display:flex;flex-direction:column}
#drawer.open{right:0}
#drawer h3{color:#7ef0b2;margin:0 0 2px}#dmeta{font:11px ui-monospace,monospace;color:#5d7488;margin-bottom:10px}
#hist{flex:1;overflow-y:auto;border:1px solid #22303d;border-radius:8px;padding:10px;font-size:12.5px}
.h-steer{color:#ffd166;margin:8px 0 2px}.h-reply{color:#dfe9f2;white-space:pre-wrap;margin:2px 0 8px}
.h-note{color:#5d7488;font:11px ui-monospace,monospace;margin:6px 0}
#steerrow{display:flex;gap:8px;margin-top:10px}
#steerbox{flex:1;background:#111a24;border:1px solid #24303c;border-radius:8px;color:#dfe9f2;padding:9px;font:13px system-ui}
button{background:rgba(42,255,192,.1);border:1px solid #2affc0;color:#2affc0;border-radius:8px;
       padding:8px 14px;font:600 13px system-ui;cursor:pointer}
button.sec{border-color:#6fb2e8;color:#6fb2e8;background:rgba(111,178,232,.08)}
#newrow{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
#newrow input{background:#111a24;border:1px solid #24303c;border-radius:8px;color:#dfe9f2;padding:8px;font:12.5px ui-monospace,monospace}
#nrepo{width:300px}#nbranch{width:160px}#ntask{flex:1;min-width:220px}
#toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#111a24;
       border:1px solid #2affc0;color:#2affc0;padding:8px 16px;border-radius:8px;display:none}
</style>
<h1>SwarmDeck — board</h1>
<p class=hint>drag a card: → Working dispatches it · → Review submits it · → Done accepts it. Click a card to open &amp; steer. <a href="/recorder" style="color:#6fb2e8">recordings</a></p>
<div id=newrow>
  <input id=nrepo placeholder="repo path (C:\\...)"><input id=nbranch placeholder="branch">
  <input id=ntask placeholder="what needs doing (the request)">
  <button onclick="fileReq()">+ File request</button>
</div>
<div id=board></div>
<div id=drawer>
  <h3 id=dtitle></h3><div id=dmeta></div>
  <div id=hist></div>
  <div id=steerrow><input id=steerbox placeholder="steer this session — context continues, no rebuild">
    <button onclick="sendSteer()">Send</button><button class=sec onclick="closeDrawer()">Close</button></div>
</div>
<div id=toast></div>
<script>
"use strict";
var LANES=[["backlog","Backlog"],["working","Working"],["review","Review"],["done","Done"]];
var CLS={queued:"q",running:"run",needs_you:"needs",submitted:"sub",accepted:"acc"};
var cur=null, tracks=[];
function toast(m){var t=document.getElementById('toast');t.textContent=m;t.style.display='block';
  setTimeout(function(){t.style.display='none'},2200)}
function load(){fetch('/tracks').then(function(r){return r.json()}).then(function(ts){tracks=ts;render()})}
function render(){
  var b=document.getElementById('board');b.innerHTML='';
  LANES.forEach(function(L){
    var lane=document.createElement('div');lane.className='lane';lane.dataset.lane=L[0];
    var inLane=tracks.filter(function(t){return (t.lane||'working')===L[0]});
    lane.innerHTML='<h2>'+L[1]+' <span class=n>'+inLane.length+'</span></h2>';
    inLane.forEach(function(t){
      var c=document.createElement('div');c.className='card '+(CLS[t.status]||'');c.draggable=true;
      c.innerHTML='<b>'+esc(t.task).slice(0,70)+'</b><div class=m>'+esc(t.branch)+' · '+t.turns+' turns · '+esc(t.status)+'</div>'
        +(t.last_reply?'<div class=r>'+esc(t.last_reply).slice(0,160)+'</div>':'');
      c.addEventListener('dragstart',function(e){e.dataTransfer.setData('text',t.id)});
      c.addEventListener('click',function(){openDrawer(t)});
      lane.appendChild(c);
    });
    lane.addEventListener('dragover',function(e){e.preventDefault();lane.classList.add('drag')});
    lane.addEventListener('dragleave',function(){lane.classList.remove('drag')});
    lane.addEventListener('drop',function(e){
      e.preventDefault();lane.classList.remove('drag');
      var id=e.dataTransfer.getData('text');
      fetch('/tracks/'+id+'/lane',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({lane:L[0]})}).then(function(){
          toast(L[0]==='working'?'dispatched — session starting':L[0]==='review'?'submitted for review':L[0]==='done'?'accepted':'queued');
          setTimeout(load,600)});
    });
    b.appendChild(lane);
  });
}
function esc(s){return String(s||'').replace(/</g,'&lt;')}
function openDrawer(t){cur=t;
  document.getElementById('dtitle').textContent=t.task.slice(0,80);
  document.getElementById('dmeta').textContent=t.branch+' · '+t.repo+' · session '+(t.session_id||'not started');
  document.getElementById('drawer').classList.add('open');
  fetch('/tracks/'+t.id+'/history').then(function(r){return r.json()}).then(function(h){
    var el=document.getElementById('hist');
    el.innerHTML=h.map(function(r){
      if(r.kind==='steer')return '<div class=h-steer>▸ '+esc(r.detail)+'</div>';
      if(r.kind==='reply')return '<div class=h-reply>'+esc(r.detail)+'</div>';
      return '<div class=h-note>'+esc(r.detail)+'</div>';
    }).join('');
    el.scrollTop=el.scrollHeight;});
}
function closeDrawer(){document.getElementById('drawer').classList.remove('open');cur=null}
function sendSteer(){var v=document.getElementById('steerbox').value.trim();if(!v||!cur)return;
  fetch('/tracks/'+cur.id+'/steer',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:v})}).then(function(){
      document.getElementById('steerbox').value='';toast('steer sent — session resuming');
      setTimeout(function(){if(cur)openDrawer(cur);load()},1500)})}
function fileReq(){
  var repo=document.getElementById('nrepo').value.trim(),br=document.getElementById('nbranch').value.trim(),
      task=document.getElementById('ntask').value.trim();
  if(!repo||!br||!task){toast('repo, branch and task needed');return}
  fetch('/tracks/new',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({repo:repo,branch:br,task:task,lane:'backlog'})}).then(function(){
      toast('request filed to backlog');document.getElementById('ntask').value='';load()})}
load();setInterval(load,5000);
</script>"""

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
                return self._send(200, BOARD, "text/html; charset=utf-8")
            if p == "/recorder":
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
                lane = body.get("lane", "working")
                if lane == "backlog":   # filing a request is instant, no session
                    return self._send(200, json.dumps(sessions.new_track(
                        repo, branch, task, body.get("perm", sessions.DEFAULT_PERM),
                        lane="backlog", client=body.get("client", ""))))
                def go():
                    sessions.new_track(repo, branch, task,
                                       body.get("perm", sessions.DEFAULT_PERM),
                                       lane="working", client=body.get("client", ""))
                _bg("track:new:" + branch, go)
                return self._send(200, json.dumps({"started": branch}))
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "steer":
                import sessions
                tid = parts[1]
                text = body.get("text")
                if not text:
                    return self._send(400, json.dumps({"error": "text required"}))
                _bg("track:steer:" + tid, lambda: sessions.steer(tid, text))
                return self._send(200, json.dumps({"started": tid}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "lane":
                import sessions
                tid = parts[1]
                lane = body.get("lane")
                if lane == "working":
                    _bg("track:dispatch:" + tid, lambda: sessions.move_lane(tid, "working"))
                    return self._send(200, json.dumps({"started": tid}))
                return self._send(200, json.dumps(sessions.move_lane(tid, lane)))
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
