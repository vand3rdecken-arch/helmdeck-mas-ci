# -*- coding: utf-8 -*-
"""Board copilot - steer SwarmDeck by chatting. Each message runs one Claude
turn (resumable per user, so the conversation has memory) with a fresh board
snapshot; the model answers with JSON: a reply for the human plus zero or more
ACTIONS the daemon executes (file cards, move lanes, steer sessions, create
processes, accept steps). Text in, board changes out."""
import json, os, re, shutil, subprocess, time

ROOT = os.path.dirname(os.path.abspath(__file__))
SESS = os.path.join(ROOT, "copilot_sessions.json")
CLAUDE = (os.environ.get("SWARMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")

SYSTEM = """You are the SwarmDeck board copilot. The user steers an agent-execution
kanban (cards = agent/human work in lanes backlog/working/review/done; processes =
step chains that auto-advance). You get a live board snapshot each message.

Reply with ONLY JSON:
{"reply": "short helpful answer for the user",
 "actions": [ ...zero or more of:
   {"type": "file_card", "task": "...", "value": 50, "due": "YYYY-MM-DD", "priority": "urgent|high|medium|low", "driver": "claude|claude-desktop", "dispatch": false}
   {"type": "move", "card": "<id or unique branch/task fragment>", "lane": "backlog|working|review|done"}
   {"type": "steer", "card": "<id or fragment>", "text": "instruction for that card's agent"}
   {"type": "new_process", "request": "...", "client": "", "due": "YYYY-MM-DD"}
   {"type": "accept_steps", "process": "<id or fragment>", "steps": "all"}
 ]}

Rules: answer status questions from the snapshot with NO actions. Only act when
the user clearly asks for a change. Prefer one precise action over many. When a
card reference is ambiguous, act on nothing and ask in the reply. Moving to
review runs the quality gate (may bounce); moving to done accepts and advances
the process chain. dispatch:true files AND starts the card immediately."""

def _sessions():
    try:
        with open(SESS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def _save_sessions(d):
    tmp = SESS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, SESS)

def _snapshot():
    import sessions, processes, events
    m = events.metrics(sessions.list_tracks())
    lines = ["CAPACITY: WIP %d/%d, headroom %d cards" % (
        m["capacity"]["wip"], m["capacity"]["wip_limit"], m["capacity"]["headroom"])]
    lines.append("CARDS:")
    for t in sessions.list_tracks():
        lines.append("- id=%s branch=%s lane=%s status=%s prio=%s due=%s mode=%s ai=$%.2f task=%s%s" % (
            t["id"], t["branch"], t.get("lane"), t.get("status"), t.get("priority", "-"),
            t.get("due") or "-", t.get("mode") or "-", t.get("ai_cost", 0),
            t["task"][:90].replace("\n", " "),
            (" last_reply=" + t.get("last_reply", "")[:150].replace("\n", " ")) if t.get("status") == "needs_you" else ""))
    lines.append("PROCESSES:")
    for p in processes.list_processes():
        lines.append("- id=%s status=%s client=%s due=%s request=%s" % (
            p["id"], p["status"], p.get("client") or "-", p.get("due") or "-", p["request"][:80]))
        for i, s in enumerate(p.get("steps", [])):
            lines.append("    step[%d] state=%s mode=%s title=%s" % (
                i, s.get("state", "proposed"), s["mode"], s["title"][:70]))
    return "\n".join(lines)

def _find_card(frag):
    import sessions
    frag = frag.lower()
    hits = [t for t in sessions.list_tracks()
            if frag in t["id"].lower() or frag in t["branch"].lower()
            or frag in t["task"].lower()]
    return hits[0] if len(hits) == 1 else (hits if hits else None)

def _run_action(a, actor):
    import sessions, processes, events
    kind = a.get("type")
    if kind == "file_card":
        repo = events.settings().get("default_repo")
        if not repo:
            return "file_card failed: no default_repo preset"
        branch = "chat-" + "".join(ch if ch.isalnum() else "-" for ch in a["task"].lower())[:24]
        t = sessions.new_track(repo, branch, a["task"],
                               lane="working" if a.get("dispatch") else "backlog",
                               value=a.get("value"), driver=a.get("driver", "claude"),
                               actor=actor, priority=a.get("priority", "medium"),
                               due=a.get("due", ""))
        return "filed card %s (%s)" % (t["id"], t["lane"])
    if kind in ("move", "steer"):
        t = _find_card(a.get("card", ""))
        if t is None:
            return "%s failed: no card matches '%s'" % (kind, a.get("card"))
        if isinstance(t, list):
            return "%s failed: '%s' is ambiguous (%d matches)" % (kind, a.get("card"), len(t))
        if kind == "move":
            r = sessions.move_lane(t["id"], a["lane"], actor=actor)
            if r.get("gate_failed"):
                return "gate BOUNCED %s: %s" % (t["branch"], " | ".join(r.get("gate_report", []))[:200])
            return "moved %s -> %s" % (t["branch"], a["lane"])
        import threading
        threading.Thread(target=sessions.steer, args=(t["id"], a["text"]),
                         kwargs={"actor": actor}, daemon=True).start()
        return "steer sent to %s (agent working in background)" % t["branch"]
    if kind == "new_process":
        p = processes.create(a["request"], client=a.get("client", ""),
                             due=a.get("due", ""), actor=actor)
        return "process %s filed - agent is proposing steps" % p["id"]
    if kind == "accept_steps":
        frag = (a.get("process") or "").lower()
        ps = [p for p in processes.list_processes()
              if frag in p["id"].lower() or frag in p["request"].lower()]
        if len(ps) != 1:
            return "accept_steps failed: process ref ambiguous or not found"
        repo = events.settings().get("default_repo")
        p = ps[0]
        for i in range(len(p["steps"])):
            if not p["steps"][i].get("track"):
                p = processes.accept_step(p["id"], i, repo, actor=actor)
        return "accepted all steps of %s into cards" % p["id"]
    return "unknown action type: " + str(kind)

def _branchless_slug_fix():
    pass  # new_track slugs empty branch to 'track'; acceptable

def chat(user, message):
    """One copilot turn for this user. Returns {reply, actions: [results]}."""
    sess = _sessions()
    sid = sess.get(user)
    prompt = SYSTEM + "\n\nBOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M") \
        + _snapshot() + "\n\nUSER (%s): %s" % (user, message)
    cmd = ["cmd", "/c", CLAUDE, "-p", "--output-format", "json",
           "--permission-mode", "plan"]
    if sid:
        cmd += ["--resume", sid]
    r = subprocess.run(cmd, cwd=ROOT, input=prompt, capture_output=True,
                       text=True, timeout=300)
    if not r.stdout.strip():
        raise RuntimeError("copilot no output: " + r.stderr.strip()[:200])
    d = json.loads(r.stdout)
    if d.get("session_id"):
        sess[user] = d["session_id"]
        _save_sessions(sess)
    txt = d.get("result", "")
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        out = json.loads(m.group(0)) if m else {"reply": txt, "actions": []}
    except ValueError:
        out = {"reply": txt, "actions": []}
    results = []
    for a in out.get("actions", [])[:6]:
        try:
            results.append(_run_action(a, user))
        except Exception as e:
            results.append("action failed: %s" % str(e)[:200])
    return {"reply": out.get("reply", ""), "actions": results,
            "cost": d.get("total_cost_usd")}
