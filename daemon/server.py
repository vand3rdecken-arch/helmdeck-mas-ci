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
<p class=hint>drag a card: → Working dispatches it · → Review runs the gate &amp; submits · → Done accepts. Click a card to open &amp; steer.
  <a href="/recorder" style="color:#6fb2e8">recordings</a> · <a href="/dashboard" style="color:#6fb2e8">dashboard</a></p>
<div id=cap class=hint style="margin:0 0 10px"></div>
<div id=newrow>
  <input id=nrepo placeholder="repo path (C:\\...)"><input id=nbranch placeholder="branch">
  <input id=ntask placeholder="what needs doing (the request)">
  <input id=nvalue placeholder="value €" style="width:70px">
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
var cur=null, tracks=[], met=null;
function toast(m,ms){var t=document.getElementById('toast');t.textContent=m;t.style.display='block';
  setTimeout(function(){t.style.display='none'},ms||2200)}
function load(){
  fetch('/tracks').then(function(r){return r.json()}).then(function(ts){tracks=ts;render()});
  fetch('/dashboard/data').then(function(r){return r.json()}).then(function(m){met=m;
    var c=m.capacity;
    document.getElementById('cap').innerHTML=
      'capacity: <b style="color:'+(c.wip>=c.wip_limit?'#ffd166':'#7ef0b2')+'">'+c.wip+'/'+c.wip_limit+' WIP</b>'
      +' · touches today '+c.touches_today+'/'+c.touch_budget_day
      +' · headroom '+c.headroom+' cards'
      +' &nbsp;&nbsp; <span style="color:#458cc7">■</span> AI $ · <span style="color:#a8842d">■</span> human touches';
    render()});
}
function cardEcon(t){
  if(!met)return '';
  var c=null;met.cards.forEach(function(x){if(x.id===t.id)c=x});
  if(!c)return '';
  var maxA=0.01,maxH=1;met.cards.forEach(function(x){if(x.ai_cost>maxA)maxA=x.ai_cost;if(x.touches>maxH)maxH=x.touches});
  var wa=Math.round(100*c.ai_cost/maxA), wh=Math.round(100*c.touches/maxH);
  return '<div class=m>€'+c.value+' · AI $'+c.ai_cost.toFixed(2)+' · '+c.touches+' touch'+(c.touches===1?'':'es')
    +(c.mode?' · '+c.mode:'')+'</div>'
    +'<div title="AI $'+c.ai_cost.toFixed(2)+' vs '+c.touches+' human touch units" style="margin-top:4px">'
    +'<div style="height:4px;border-radius:2px;background:#458cc7;width:'+Math.max(wa,2)+'%"></div>'
    +'<div style="height:4px;border-radius:2px;background:#a8842d;width:'+Math.max(wh,2)+'%;margin-top:2px"></div></div>';
}
function render(){
  var b=document.getElementById('board');b.innerHTML='';
  LANES.forEach(function(L){
    var lane=document.createElement('div');lane.className='lane';lane.dataset.lane=L[0];
    var inLane=tracks.filter(function(t){return (t.lane||'working')===L[0]});
    lane.innerHTML='<h2>'+L[1]+' <span class=n>'+inLane.length+'</span></h2>';
    inLane.forEach(function(t){
      var c=document.createElement('div');c.className='card '+(CLS[t.status]||'');c.draggable=true;
      c.innerHTML='<b>'+esc(t.task).slice(0,70)+'</b><div class=m>'+esc(t.branch)+' · '+t.turns+' turns · '+esc(t.status)+'</div>'
        +cardEcon(t)
        +(t.gate_report?'<div class=r style="color:#ffd166">gate: '+esc(t.gate_report.join(' | ')).slice(0,160)+'</div>':'')
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
        body:JSON.stringify({lane:L[0]})}).then(function(r){return r.json()}).then(function(res){
          if(res&&res.gate_failed){
            toast('GATE FAILED — bounced back: '+(res.gate_report||[]).map(function(p){return p.split('\\n')[0]}).join(' | '),5000);
          }else{
            toast(L[0]==='working'?'dispatched — session starting':L[0]==='review'?'gate passed — submitted for review':L[0]==='done'?'accepted':'queued');
          }
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
      task=document.getElementById('ntask').value.trim(),val=document.getElementById('nvalue').value.trim();
  if(!task){toast('task needed (repo/branch optional if default_repo preset)');return}
  fetch('/tracks/new',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({repo:repo,branch:br,task:task,lane:'backlog',value:val?parseFloat(val):null})}).then(function(){
      toast('request filed to backlog');document.getElementById('ntask').value='';load()})}
load();setInterval(load,5000);
</script>"""

DASH = """<!doctype html><meta charset=utf-8><title>SwarmDeck — dashboard</title>
<style>
body{font:14px/1.45 system-ui;background:#0b0f14;color:#dfe9f2;margin:0;padding:18px 20px}
h1{color:#7ef0b2;font-size:20px;margin:0 0 4px}.hint{color:#5d7488;font-size:12px;margin:0 0 16px}
h2{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#8fb0c9;margin:22px 0 8px}
#tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile{background:#0e151d;border:1px solid #22303d;border-radius:12px;padding:12px 14px}
.tile .v{font-size:24px;font-weight:700;color:#dfe9f2}.tile .l{font-size:11px;color:#8fb0c9;margin-top:2px}
.meter{background:#111a24;border:1px solid #24303c;border-radius:6px;height:14px;overflow:hidden;margin-top:6px}
.meter i{display:block;height:100%;background:#a8842d;border-radius:4px}
.bar{display:flex;align-items:center;gap:8px;margin:4px 0}
.bar .lbl{width:280px;font:12px ui-monospace,monospace;color:#8fb0c9;text-align:right;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .trk{flex:1}.bar .trk i{display:block;height:12px;border-radius:0 4px 4px 0;background:#458cc7}
.bar .n{font:12px ui-monospace,monospace;color:#dfe9f2;width:30px}
table{border-collapse:collapse;font-size:12.5px;width:100%}
th,td{text-align:left;padding:5px 10px;border-bottom:1px solid #22303d}
th{color:#8fb0c9;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.08em}
td.num,th.num{text-align:right;font-family:ui-monospace,monospace}
.split{display:inline-block;width:110px;vertical-align:middle}
.split i{display:block;height:4px;border-radius:2px}
.leg{font-size:12px;color:#8fb0c9}.leg b{font-weight:400}
a{color:#6fb2e8}
</style>
<h1>SwarmDeck — company dashboard</h1>
<p class=hint>fixed-capacity humans, variable-cost AI. <a href="/">board</a> · <a href="/settings" onclick="alert('GET/POST /settings (JSON): capacity, prices, value_per_card');return false">settings</a></p>
<div id=tiles></div>
<h2>Capacity — take more work, or automate?</h2><div id=capbox class=tile style="max-width:520px"></div>
<h2>Gate-failure histogram — what to fix in the harness next</h2><div id=gates></div>
<h2>Work done: <span class=leg><b style="color:#458cc7">■</b> AI ($) · <b style="color:#a8842d">■</b> human (touch units)</span></h2>
<div style="overflow-x:auto"><table id=cards></table></div>
<script>
"use strict";
function esc(s){return String(s||'').replace(/</g,'&lt;')}
fetch('/dashboard/data').then(function(r){return r.json()}).then(function(m){
  var cur=m.settings.currency==='EUR'?'\\u20ac':'$';
  var y=m.yield_first_pass,a=m.automation,T=m.totals;
  var tiles=[
    [cur+T.value_delivered,'value delivered'],
    ['$'+T.ai_spend.toFixed(2),'AI spend'],
    [cur+T.margin,'margin (value − AI)'],
    [(y[1]? Math.round(100*y[0]/y[1])+'%':'—'),'first-pass yield ('+y[0]+'/'+y[1]+' gated)'],
    [(a[1]? Math.round(100*a[0]/a[1])+'%':'—'),'automation rate ('+a[0]+'/'+a[1]+' done auto)'],
    [cur+T.leverage_per_touch,'leverage: value per touch unit']];
  document.getElementById('tiles').innerHTML=tiles.map(function(t){
    return '<div class=tile><div class=v>'+t[0]+'</div><div class=l>'+t[1]+'</div></div>'}).join('');
  var c=m.capacity,pct=Math.min(100,Math.round(100*c.touches_today/(c.touch_budget_day||1)));
  document.getElementById('capbox').innerHTML=
    '<div class=l style="color:#8fb0c9;font-size:12px">today: '+c.touches_today+'/'+c.touch_budget_day
    +' touch units ('+pct+'% loaded) · WIP '+c.wip+'/'+c.wip_limit+' · headroom <b style="color:#7ef0b2">'
    +c.headroom+' cards</b></div><div class=meter><i style="width:'+pct+'%"></i></div>'
    +'<div class=l style="color:#5d7488;font-size:11px;margin-top:6px">'
    +(pct<80&&c.headroom>0?'below capacity \\u2192 intake more work: marginal cost of one more card is tokens only'
      :'at capacity \\u2192 don\\u2019t take more; automate: fix the top gate failure below to free headroom')+'</div>';
  var g=m.gate_failures,gx=document.getElementById('gates');
  if(!g.length){gx.innerHTML='<p class=hint>no gate failures recorded yet</p>'}
  else{var mx=g[0][1];gx.innerHTML=g.map(function(kv){
    return '<div class=bar title="'+esc(kv[0])+' \\u2014 '+kv[1]+' failures"><div class=lbl>'+esc(kv[0])
      +'</div><div class=trk><i style="width:'+Math.max(3,Math.round(100*kv[1]/mx))+'%"></i></div><div class=n>'+kv[1]+'</div></div>'}).join('')}
  var maxA=0.01,maxH=1;m.cards.forEach(function(x){if(x.ai_cost>maxA)maxA=x.ai_cost;if(x.touches>maxH)maxH=x.touches});
  document.getElementById('cards').innerHTML=
    '<tr><th>card</th><th>lane</th><th>model</th><th class=num>tokens in/out</th><th class=num>AI $</th>'
    +'<th class=num>touches</th><th>split</th><th class=num>value</th><th class=num>margin</th><th>mode</th></tr>'
    +m.cards.map(function(x){
      var wa=Math.max(2,Math.round(100*x.ai_cost/maxA)),wh=Math.max(2,Math.round(100*x.touches/maxH));
      return '<tr><td>'+esc(x.task)+'</td><td>'+x.lane+'</td><td>'+esc((x.models[0]||'\\u2014').replace('claude-',''))
        +'</td><td class=num>'+x.tokens_in+'/'+x.tokens_out+'</td><td class=num>'+x.ai_cost.toFixed(2)
        +'</td><td class=num>'+x.touches+'</td><td><span class=split title="AI $'+x.ai_cost.toFixed(2)+' vs '
        +x.touches+' touch units"><i style="background:#458cc7;width:'+wa+'%"></i>'
        +'<i style="background:#a8842d;width:'+wh+'%;margin-top:2px"></i></span></td>'
        +'<td class=num>'+cur+x.value+'</td><td class=num>'+cur+(x.value-x.ai_cost).toFixed(2)
        +'</td><td>'+(x.mode||'\\u2014')+'</td></tr>'}).join('');
});
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

    # HTML shells + the auth endpoints are public; every data/control route
    # needs a logged-in session (cookie) or a per-user device token.
    OPEN = ("/", "/classic", "/auth/state", "/auth/login", "/auth/logout",
            "/auth/setup", "/auth/register")

    def _sid(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sd_session":
                return v
        return None

    def _user(self):
        import auth
        tok = ""
        h = self.headers.get("Authorization") or ""
        if h.startswith("Bearer "):
            tok = h[7:].strip()
        if not tok and "token=" in self.path:
            tok = self.path.split("token=")[1].split("&")[0]
        return auth.resolve(sid=self._sid(), token=tok or None)

    def _send_cookie(self, code, body, sid=None, clear=False):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if sid:
            self.send_header("Set-Cookie",
                "sd_session=%s; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000" % sid)
        if clear:
            self.send_header("Set-Cookie", "sd_session=; Path=/; Max-Age=0")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode("utf-8"))

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            user = self._user()
            if p == "/auth/state":
                import auth, events
                reg = events.settings().get("registration") or {}
                return self._send(200, json.dumps(
                    {"setup_needed": not auth.list_users(), "user": user,
                     "registration": bool(reg.get("open") or reg.get("invite_code")),
                     "registration_open": bool(reg.get("open"))}))
            if p not in self.OPEN and not user:
                return self._send(401, json.dumps({"error": "auth required"}))
            if p == "/users":
                import auth
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                return self._send(200, json.dumps([
                    {"name": u["name"], "role": u["role"], "created": u.get("created"),
                     "tokens": [{"label": t["label"], "token": t["token"],
                                 "created": t.get("created")} for t in u.get("tokens", [])]}
                    for u in auth.list_users()]))
            if p == "/":
                fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "app.html")
                if os.path.exists(fp):   # the Plane-tokened app; read per request so edits are live
                    with open(fp, "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                return self._send(200, BOARD, "text/html; charset=utf-8")
            if p == "/classic":
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
                ts = sessions.list_tracks()
                if user["role"] == "client":   # clients see only their own cards
                    ts = [t for t in ts if t.get("client") == user["name"]]
                return self._send(200, json.dumps(ts))
            # --- company instrumentation: settings + CEO dashboard ---
            if p == "/chat/history":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import copilot
                return self._send(200, json.dumps(copilot.history(user["name"])))
            if p == "/debt":
                import debt
                return self._send(200, json.dumps(debt.list_debt()))
            if p == "/charter":
                import charter, events
                return self._send(200, json.dumps(
                    {"core": charter.CHARTER,
                     "house_rules": (events.settings().get("policy") or {}).get("house_rules", "")}))
            if p == "/checkpoints":
                import checkpoints
                return self._send(200, json.dumps(checkpoints.list_checkpoints()))
            if p == "/history":
                # the git audit trail: main line + every card branch's commits.
                import subprocess, sessions, events
                repo = events.settings().get("default_repo")
                if not repo:
                    return self._send(200, json.dumps({"main": [], "branches": []}))
                def git(*args):
                    r = subprocess.run(["git", "-C", repo, *args],
                                       capture_output=True, text=True, timeout=20)
                    return r.stdout.strip() if r.returncode == 0 else ""
                def parse(log):
                    out = []
                    for line in log.splitlines():
                        bits = line.split("")
                        if len(bits) >= 4:
                            out.append({"h": bits[0], "msg": bits[1][:100],
                                        "author": bits[2], "date": bits[3]})
                    return out
                fmt = "--pretty=format:%h%s%an%ad"
                head = git("rev-parse", "--abbrev-ref", "HEAD") or "main"
                main = parse(git("log", "-n", "40", "--date=short", fmt, head))
                tmap = {}
                for t in sessions.list_tracks():
                    tmap.setdefault(t["branch"], t)
                branches = []
                for br in git("branch", "--format=%(refname:short)").splitlines():
                    br = br.strip()
                    if not br or br == head:
                        continue
                    commits = parse(git("log", "--date=short", fmt, "-n", "20",
                                        "%s..%s" % (head, br)))
                    t = tmap.get(br)
                    branches.append({
                        "name": br, "commits": commits,
                        "track": t["id"] if t else None,
                        "task": t["task"][:70] if t else "",
                        "lane": t.get("lane") if t else None,
                        "client": t.get("client") if t else "",
                    })
                branches.sort(key=lambda b: (b["track"] is None, b["name"]))
                return self._send(200, json.dumps(
                    {"head": head, "main": main, "branches": branches[:40]}))
            if p == "/connectors":
                import connectors
                return self._send(200, json.dumps(connectors.list_connectors()))
            if p == "/processes":
                import processes
                try:
                    processes.sync()
                except Exception:
                    pass
                return self._send(200, json.dumps(processes.list_processes(
                    client=user["name"] if user["role"] == "client" else None)))
            if p == "/me":
                return self._send(200, json.dumps({"name": user["name"], "role": user["role"]}))
            if p == "/settings":
                import events
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                return self._send(200, json.dumps(events.settings()))
            if p == "/dashboard/data":
                import events, sessions
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                m = events.metrics(sessions.list_tracks())
                if user["role"] != "owner":
                    m.pop("settings", None)
                return self._send(200, json.dumps(m))
            if p == "/dashboard":
                return self._send(200, DASH, "text/html; charset=utf-8")
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "live":
                # the card's own glance feed: newest frame while its agent's
                # turn is being screen-recorded (fresh = written in last 20s)
                import sessions, time as _t
                t = sessions.get_track(parts[1])
                if user["role"] == "client" and (not t or t.get("client") != user["name"]):
                    return self._send(403, b"not your card", "text/plain")
                fp = os.path.join(t["run_dir"], "live.jpg") if t else ""
                if fp and os.path.exists(fp) and _t.time() - os.path.getmtime(fp) < 20:
                    with open(fp, "rb") as f:
                        return self._send(200, f.read(), "image/jpeg")
                return self._send(404, b"no live frame", "text/plain")
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "history":
                import sessions
                if user["role"] == "client":
                    t = sessions.get_track(parts[1])
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
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
            import auth
            user = self._user()
            # ---- auth endpoints (public) ----
            if p == "/auth/setup":
                if auth.list_users():
                    return self._send(403, json.dumps({"error": "already set up"}))
                try:
                    auth.create_user(body.get("name", ""), body.get("password", ""), "owner")
                except ValueError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
                sid = auth.login(body["name"], body["password"])
                return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)
            if p == "/auth/register":
                import events, secrets as _s
                reg = events.settings().get("registration") or {}
                code = (body.get("invite") or "").strip()
                if not reg.get("open"):
                    want = reg.get("invite_code") or ""
                    if not want or not code or not _s.compare_digest(code, want):
                        return self._send(403, json.dumps({"error": "valid invite code required"}))
                try:
                    auth.create_user(body.get("name", ""), body.get("password", ""),
                                     reg.get("default_role", "client"))
                except ValueError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
                sid = auth.login(body["name"], body["password"])
                return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)
            if p == "/auth/login":
                sid = auth.login(body.get("name", ""), body.get("password", ""))
                if not sid:
                    return self._send(401, json.dumps({"error": "wrong name or password"}))
                return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)
            if p == "/auth/logout":
                if self._sid():
                    auth.logout(self._sid())
                return self._send_cookie(200, json.dumps({"ok": True}), clear=True)
            if not user:
                return self._send(401, json.dumps({"error": "auth required"}))
            # ---- user management (owner only) ----
            parts = p.strip("/").split("/")
            if parts[0] == "users":
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                try:
                    if len(parts) == 1:
                        return self._send(200, json.dumps(auth.create_user(
                            body.get("name", ""), body.get("password", ""),
                            body.get("role", "operator"))))
                    name, action = parts[1], parts[2] if len(parts) > 2 else ""
                    if action == "password":
                        auth.set_password(name, body.get("password", ""))
                    elif action == "role":
                        auth.set_role(name, body.get("role", ""))
                    elif action == "tokens":
                        return self._send(200, json.dumps(
                            {"token": auth.issue_token(name, body.get("label", ""))}))
                    elif action == "revoke":
                        auth.revoke_token(name, body.get("token", ""))
                    elif action == "delete":
                        auth.delete_user(name)
                    else:
                        return self._send(404, json.dumps({"error": "?"}))
                    return self._send(200, json.dumps({"ok": True}))
                except ValueError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if user["role"] == "client" and p not in ("/tracks/new", "/processes/new") \
               and not (p.startswith("/tracks/") and p.endswith("/steer")):
                return self._send(403, json.dumps({"error": "clients can file and comment only"}))
            if p == "/chat":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import copilot
                text = body.get("text", "").strip()
                if not text:
                    return self._send(400, json.dumps({"error": "text required"}))
                try:
                    return self._send(200, json.dumps(copilot.chat(user["name"], text, role=user["role"], model=body.get("model", ""))))
                except Exception as e:
                    return self._send(500, json.dumps({"error": str(e)[:300]}))
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "checkpoints" and parts[2] == "restore":
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                import checkpoints
                try:
                    checkpoints.restore(parts[1], actor=user["name"])
                    return self._send(200, json.dumps({"restored": parts[1]}))
                except Exception as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}))
            if len(parts) == 3 and parts[0] == "connectors" and parts[2] == "rollback":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import connectors, events
                try:
                    prev = connectors.rollback(parts[1])
                    events.emit("connector", "-", action="rollback", name=parts[1], actor=user["name"])
                    return self._send(200, json.dumps({"restored": prev}))
                except Exception as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}))
            if len(parts) == 3 and parts[0] == "connectors" and parts[2] == "run":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import connectors
                try:
                    made = connectors.run_connector(parts[1], actor=user["name"])
                    return self._send(200, json.dumps({"cards": len(made)}))
                except Exception as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}))
            if len(parts) == 3 and parts[0] == "debt" and parts[2] == "fix":
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import debt, sessions, events
                item = next((d for d in debt.DEBT if d["id"] == parts[1]), None)
                if not item:
                    return self._send(404, json.dumps({"error": "unknown debt id"}))
                repo = events.settings().get("default_repo")
                t = sessions.new_track(repo, "debt-" + item["id"], debt.fix_task(item),
                                       lane="backlog", actor=user["name"], priority="high")
                return self._send(200, json.dumps(t))
            if p in ("/import/jira", "/import/url"):
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                import importers
                try:
                    if p.endswith("jira"):
                        made = importers.jira_import(body.get("jql", ""), actor=user["name"])
                        return self._send(200, json.dumps({"imported": len(made), "ids": made}))
                    pr = importers.url_import(body.get("url", ""), client=body.get("client", ""),
                                              due=body.get("due", ""), actor=user["name"])
                    return self._send(200, json.dumps(pr))
                except Exception as e:
                    return self._send(400, json.dumps({"error": str(e)[:300]}))
            # ---- processes: propose -> adjust -> accept into cards ----
            if p == "/processes/new":
                import processes
                req = body.get("request")
                if not req:
                    return self._send(400, json.dumps({"error": "request required"}))
                client = user["name"] if user["role"] == "client" else body.get("client", "")
                return self._send(200, json.dumps(processes.create(
                    req, client=client, due=body.get("due", ""), actor=user["name"])))
            parts = p.strip("/").split("/")
            if parts[0] == "processes" and len(parts) >= 3:
                import processes, events
                pid = parts[1]
                try:
                    if parts[2] == "step":
                        act = body.get("action")
                        idx = int(body.get("idx", -1))
                        if act == "accept":
                            repo = body.get("repo") or events.settings().get("default_repo")
                            if not repo:
                                return self._send(400, json.dumps({"error": "no default_repo preset"}))
                            return self._send(200, json.dumps(
                                processes.accept_step(pid, idx, repo, actor=user["name"])))
                        if act == "update":
                            return self._send(200, json.dumps(
                                processes.update_step(pid, idx, body.get("patch") or {})))
                        if act == "remove":
                            return self._send(200, json.dumps(processes.remove_step(pid, idx)))
                        if act == "add":
                            return self._send(200, json.dumps(processes.add_step(
                                pid, body.get("title", "new step"), body.get("mode", "do"))))
                        if act == "accept_all":
                            repo = body.get("repo") or events.settings().get("default_repo")
                            pr = processes.get(pid)
                            for i in range(len(pr["steps"])):
                                if not pr["steps"][i].get("track"):
                                    pr = processes.accept_step(pid, i, repo, actor=user["name"])
                            return self._send(200, json.dumps(pr))
                    return self._send(404, json.dumps({"error": "?"}))
                except (RuntimeError, ValueError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
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
            if p == "/settings":
                import events
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                return self._send(200, json.dumps(events.save_settings(body, actor=user["name"])))
            # --- orchestrator control ---
            if p == "/tracks/new":
                import sessions, events
                repo = body.get("repo") or events.settings().get("default_repo")
                branch = body.get("branch"); task = body.get("task")
                if task and not branch:   # preset flow: task alone is enough
                    branch = "req-" + "".join(ch if ch.isalnum() else "-" for ch in task.lower())[:24]
                if not (repo and branch and task):
                    return self._send(400, json.dumps({"error": "task required (+ repo unless default_repo is set in settings)"}))
                lane = body.get("lane", "working")
                client = user["name"] if user["role"] == "client" else body.get("client", "")
                driver = body.get("driver", "claude")
                if user["role"] == "client":
                    driver = "claude"   # clients don't pick desktop-driving agents
                if lane == "backlog":   # filing a request is instant, no session
                    return self._send(200, json.dumps(sessions.new_track(
                        repo, branch, task, body.get("perm", sessions.DEFAULT_PERM),
                        lane="backlog", client=client, value=body.get("value"),
                        driver=driver, actor=user["name"],
                        priority=body.get("priority", "medium"),
                        due=body.get("due", ""))))
                def go():
                    sessions.new_track(repo, branch, task,
                                       body.get("perm", sessions.DEFAULT_PERM),
                                       lane="working", client=client,
                                       value=body.get("value"),
                                       driver=driver, actor=user["name"],
                                       priority=body.get("priority", "medium"),
                                       due=body.get("due", ""))
                _bg("track:new:" + branch, go)
                return self._send(200, json.dumps({"started": branch}))
            parts = p.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "archive":
                import sessions
                if user["role"] == "client":
                    return self._send(403, json.dumps({"error": "owner/operator only"}))
                try:
                    return self._send(200, json.dumps(sessions.archive_track(
                        parts[1], on=bool(body.get("on", True)), actor=user["name"])))
                except RuntimeError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "delete":
                import sessions
                if user["role"] != "owner":
                    return self._send(403, json.dumps({"error": "owner only"}))
                try:
                    return self._send(200, json.dumps(sessions.delete_track(
                        parts[1], actor=user["name"])))
                except RuntimeError as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "update":
                import sessions
                if user["role"] == "client":
                    t = sessions.get_track(parts[1])
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                try:
                    return self._send(200, json.dumps(
                        sessions.update_track(parts[1], body, actor=user["name"])))
                except (RuntimeError, ValueError) as e:
                    return self._send(400, json.dumps({"error": str(e)}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "steer":
                import sessions
                tid = parts[1]
                text = body.get("text")
                if not text:
                    return self._send(400, json.dumps({"error": "text required"}))
                if user["role"] == "client":
                    t = sessions.get_track(tid)
                    if not t or t.get("client") != user["name"]:
                        return self._send(403, json.dumps({"error": "not your card"}))
                actor = user["name"]
                _bg("track:steer:" + tid, lambda: sessions.steer(tid, text, actor=actor))
                return self._send(200, json.dumps({"started": tid}))
            if len(parts) == 3 and parts[0] == "tracks" and parts[2] == "lane":
                import sessions
                tid = parts[1]
                lane = body.get("lane")
                actor = user["name"]
                if lane == "working":
                    _bg("track:dispatch:" + tid,
                        lambda: sessions.move_lane(tid, "working", actor=actor))
                    return self._send(200, json.dumps({"started": tid}))
                return self._send(200, json.dumps(sessions.move_lane(tid, lane, actor=actor)))
            self._send(404, b"?", "text/plain")
        except (ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

def serve(port=8140):
    import auth, events
    if auth.migrate_legacy(events.settings().get("users")):
        print("AUTH: legacy token-users migrated to users.json; old tokens still work as device tokens.")
        print("      Set real passwords via the Users panel (owner).")
    if not auth.list_users():
        print("AUTH: no users yet - the web app will show the create-owner setup screen.")
    import processes, connectors
    processes.start_chain_poller()
    connectors.start_scheduler()
    print("SwarmDeck review server on http://localhost:%d  (APK pulls /runs, /live.jpg)" % port)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()

if __name__ == "__main__":
    serve()
