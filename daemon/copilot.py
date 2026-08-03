# -*- coding: utf-8 -*-
"""Board copilot - steer HelmDeck by chatting. Each message runs one Claude
turn (resumable per user, so the conversation has memory) with a fresh board
snapshot; the model answers with JSON: a reply for the human plus zero or more
ACTIONS the daemon executes (file cards, move lanes, steer sessions, create
processes, accept steps). Text in, board changes out."""
import json, os, re, shutil, subprocess, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))
SESS = os.path.join(ROOT, "copilot_sessions.json")
CHATLOG = os.path.join(ROOT, "copilot_log.json")
CLAUDE = (os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")

SYSTEM = """You are the HelmDeck board copilot. The user steers an agent-execution
kanban (cards = agent/human work in lanes backlog/working/review/done; processes =
step chains that auto-advance). You get a live board snapshot each message.

Reply with ONLY JSON:
{"reply": "short helpful answer for the user",
 "actions": [ ...zero or more of:
   {"type": "file_card", "task": "...", "value": 50, "due": "YYYY-MM-DD", "priority": "urgent|high|medium|low", "driver": "claude|claude-desktop", "dispatch": false}
   {"type": "move", "card": "<id or unique branch/task fragment>", "lane": "backlog|working|review|done"}  (admin: policy.chat_admin_roles)
   {"type": "delete", "card": "<id or fragment>"}  - permanently remove a card (admin: policy.chat_admin_roles)
   {"type": "archive", "card": "<id or fragment>"}  - archive a card out of the board (admin: policy.chat_admin_roles)
   {"type": "steer", "card": "<id or fragment>", "text": "instruction for that card's agent"}
   {"type": "resolve_blocker", "card": "<id or fragment>"}  - a card stuck on Review whose "merge conflict" is really an uncommitted (dirty) tree in the shared repo checkout ("your local changes ... would be overwritten"), NOT a <<<<<< conflict. Parks that uncommitted work on a wip-* branch (NOTHING lost, non-destructive) and re-runs the review check. The sandboxed card worker cannot do this - it's board-level, which is why the worker hands it up. Use ONLY when the owner explicitly asks to unblock / park / resolve the blocker (admin: policy.chat_admin_roles).
   {"type": "new_process", "request": "...", "client": "", "due": "YYYY-MM-DD"}
   {"type": "accept_steps", "process": "<id or fragment>", "steps": "all"}
   {"type": "configure", "patch": {..}}  (roles per policy.chat_configure_roles)
   {"type": "import_url", "url": "https://...", "client": "", "due": ""}  - fetch a page, agent derives a process from it
   {"type": "import_jira", "jql": "project = X AND status = 'To Do'"}  - pull Jira issues into backlog cards (needs settings.jira)
   {"type": "build_integration", "name": "kebab-name", "spec": "what it should pull and map"}  - an AGENT writes the connector as a card; after the gate + human accept it becomes runnable. Chat never installs code directly.
   {"type": "run_connector", "name": "<installed connector>"}  - run it now; items become backlog cards
   {"type": "rollback_connector", "name": "..."}  - restore the previous version (originals are always archived)
   {"type": "schedule_connector", "name": "...", "every_minutes": 60}  - or 0 to unschedule
 ]}

configure may ONLY touch these keys (the flexible half of the workspace):
  policy.lane_labels {backlog,working,review,done: "label"} - rename lanes
  policy.auto_dispatch_modes ["do","prepare",...] - which step modes the chain starts alone
  policy.auto_accept_green true|false - green gate auto-accepts (autonomy) vs human accepts (control)
  policy.auto_dispatch_priority ""|"urgent"|"high" - backlog at/above this priority self-dispatches within WIP headroom
  capacity {wip_limit, touch_budget_day, tariff{steer,review,bounce}}
  value_per_card, default_repo, registration {open, invite_code, default_role}
  currency "EUR"|"USD"
  prices {<model-substring>: {in: $/Mtok, out: $/Mtok}, default: {...}} - AI cost table
  appearance {backdrop: "mesh"|"aurora"|"ember"|"forest"|"mono"} - ambient background theme
  dashboard {tiles: [...], panels: [...]} - what the economics dashboard shows, in order.
    tiles vocabulary: value_delivered, ai_spend, margin, yield, automation, leverage
    panels vocabulary: capacity, gates, work
Everything else (auth, users, drivers, audit, the gate itself) is FIXED - refuse
politely and explain it is part of the harness, not policy.

CAPABILITY CHARTER: connectors are read-only toward the world, create-only
toward the board, stdlib-only. NEVER commission builds that edit/delete
existing work, touch auth/users/audit, execute shells or processes, write or
read local files, read env secrets, produce UI code, or alter drivers -
refuse such build requests and explain the charter. Off-charter code is also
blocked at install time by static screening; do not try to work around it.
If policy.house_rules is present in POLICY, apply those additional
restrictions too.

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
    pol = events.settings().get("policy") or {}
    lines = ["POLICY: " + json.dumps(pol)]
    lines += ["CAPACITY: WIP %d/%d, headroom %d cards" % (
        m["capacity"]["wip"], m["capacity"]["wip_limit"], m["capacity"]["headroom"])]
    # Cards span MULTIPLE repos (projects). The repo is shown so a question about
    # one project (e.g. "what's left for HelmDeck") is scoped to THAT repo only -
    # without it the model mixed Seekingalpha/immo-deal-scanner cards into HelmDeck.
    lines.append("CARDS (each belongs to ONE repo; a question about a specific "
                 "project/repo must include ONLY that repo's cards):")
    for t in sessions.list_tracks():
        repo = os.path.basename((t.get("repo") or "").replace("\\", "/").rstrip("/")) or "?"
        lines.append("- id=%s repo=%s branch=%s lane=%s status=%s prio=%s due=%s mode=%s ai=$%.2f task=%s%s" % (
            t["id"], repo, t["branch"], t.get("lane"), t.get("status"), t.get("priority", "-"),
            t.get("due") or "-", t.get("mode") or "-", t.get("ai_cost", 0),
            t["task"][:90].replace("\n", " "),
            (" last_reply=" + t.get("last_reply", "")[:150].replace("\n", " ")) if t.get("status") == "needs_you" else ""))
    try:
        import connectors as _c
        cs = _c.list_connectors()
        if cs:
            lines.append("INSTALLED CONNECTORS: " + ", ".join(
                "%s (%s)" % (c["name"], c["description"][:40]) for c in cs))
    except Exception:
        pass
    try:
        import debt as _d
        open_items = [d for d in _d.list_debt() if d["status"] != "paid"]
        if open_items:
            lines.append("STRUCTURAL DEBT (open, ordered): " + "; ".join(
                "%s - %s (bites when: %s)" % (d["id"], d["title"], d["trigger"])
                for d in open_items))
    except Exception:
        pass
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

ALLOWED_CONFIG = {"policy", "capacity", "value_per_card", "default_repo",
                  "registration", "dashboard", "prices", "currency", "appearance", "jira"}

def _run_action(a, actor, role="operator"):
    import sessions, processes, events
    kind = a.get("type")
    if kind == "configure":
        allowed_roles = (events.settings().get("policy") or {}).get("chat_configure_roles", ["owner"])
        if role not in allowed_roles:
            return "configure denied: policy allows roles %s" % ", ".join(allowed_roles)
        raw = a.get("patch") or {}
        patch = {}
        for k, v in raw.items():   # accept both {"policy": {...}} and "policy.x"
            if "." in k:
                top, _, sub = k.partition(".")
                patch.setdefault(top, {})
                if isinstance(patch[top], dict):
                    patch[top][sub] = v
            elif isinstance(v, dict) and k in patch and isinstance(patch[k], dict):
                patch[k].update(v)
            else:
                patch[k] = v
        bad = set(patch) - ALLOWED_CONFIG
        if bad:
            return "configure denied for fixed keys: %s (harness, not policy)" % ", ".join(sorted(bad))
        import events as _ev
        _ev.save_settings(patch, actor=actor, reason="via chat")
        _ev.emit("config", "-", actor=actor, patch=patch)
        return "policy updated: " + json.dumps(patch)[:300]
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
    if kind in ("move", "steer", "delete", "archive"):
        t = _find_card(a.get("card", ""))
        if t is None:
            return "%s failed: no card matches '%s'" % (kind, a.get("card"))
        if isinstance(t, list):
            return "%s failed: '%s' is ambiguous (%d matches)" % (kind, a.get("card"), len(t))
        # admin gate: MOVING / DELETING / ARCHIVING a card is a structural change -
        # only authorized roles may (policy.chat_admin_roles, default owner+operator).
        # steer stays open (clients steer their own cards).
        if kind in ("move", "delete", "archive"):
            admin_roles = (events.settings().get("policy") or {}).get("chat_admin_roles", ["owner", "operator"])
            if role not in admin_roles:
                return "%s denied: needs role %s (you are '%s')" % (kind, "/".join(admin_roles), role)
        if kind == "move":
            r = sessions.move_lane(t["id"], a["lane"], actor=actor)
            # gate_report / merge_report are curated, self-contained instruction
            # strings (fixed template + file list) - show them whole, no char cap
            # (a slice cut the resolve steer off mid-word).
            if r.get("gate_failed"):
                return "gate BOUNCED %s: %s" % (t["branch"], " | ".join(r.get("gate_report", [])))
            if r.get("merge_failed"):
                return "%s bleibt auf Review (%s): %s" % (t["branch"], r.get("merge_kind"), r.get("merge_report") or "")
            return "moved %s -> %s" % (t["branch"], a["lane"])
        if kind == "delete":
            sessions.delete_track(t["id"], actor=actor)
            return "deleted card %s (%s)" % (t["branch"], t["id"])
        if kind == "archive":
            sessions.archive_track(t["id"], on=True, actor=actor)
            return "archived card %s" % t["branch"]
        import threading
        threading.Thread(target=sessions.steer, args=(t["id"], a["text"]),
                         kwargs={"actor": actor, "source": "board copilot"}, daemon=True).start()
        return "steer sent to %s (agent working in background)" % t["branch"]
    if kind == "resolve_blocker":
        # Unblock a card whose merge is blocked by an uncommitted (dirty) tree in
        # the shared repo checkout - a cross-cutting fix the sandboxed worker
        # can't do. Park the dirty work on a wip-* branch (nothing lost) + retry.
        # Structural + touches the shared checkout -> admin gate, like move.
        admin_roles = (events.settings().get("policy") or {}).get("chat_admin_roles", ["owner", "operator"])
        if role not in admin_roles:
            return "resolve_blocker denied: needs role %s (you are '%s')" % ("/".join(admin_roles), role)
        t = _find_card(a.get("card", ""))
        if t is None:
            return "resolve_blocker failed: no card matches '%s'" % a.get("card")
        if isinstance(t, list):
            return "resolve_blocker failed: '%s' is ambiguous (%d matches)" % (a.get("card"), len(t))
        return sessions.park_and_retry_merge(t["id"], actor=actor)
    if kind == "build_integration":
        import connectors
        name = re.sub(r"[^a-z0-9-]", "-", (a.get("name") or "connector").lower())[:24]
        repo = events.settings().get("default_repo")
        if not repo:
            return "build_integration failed: no default_repo preset"
        t = sessions.new_track(repo, "connector-" + name,
                               connectors.build_task(name, a.get("spec", "")),
                               lane="working", actor=actor, priority="high")
        tracks = sessions._load(); tt = sessions._find(tracks, t["id"])
        tt["connector"] = name; sessions._save(tracks)
        return ("integration card dispatched (%s) - the agent is writing the connector; "
                "gate + your accept installs it" % t["id"])
    if kind == "run_connector":
        import connectors
        made = connectors.run_connector(a.get("name", ""), actor=actor)
        return "connector ran: %d new backlog cards" % len(made)
    if kind == "rollback_connector":
        import connectors
        prev = connectors.rollback(a.get("name", ""))
        events.emit("connector", "-", action="rollback", name=a.get("name"), actor=actor)
        return "rolled back %s to %s" % (a.get("name"), prev)
    if kind == "schedule_connector":
        mins = int(a.get("every_minutes") or 0)
        sched = events.settings().get("connectors") or {}
        if mins > 0:
            sched[a.get("name", "")] = {"every_minutes": mins}
        else:
            sched.pop(a.get("name", ""), None)
        events.save_settings({"connectors": sched})
        return "connector schedule updated: %s" % json.dumps(sched)
    if kind == "import_url":
        import importers
        p2 = importers.url_import(a.get("url", ""), client=a.get("client", ""),
                                  due=a.get("due", ""), actor=actor)
        return "imported %s - agent is deriving the process steps" % a.get("url")
    if kind == "import_jira":
        import importers
        made = importers.jira_import(a.get("jql", ""), actor=actor)
        return "imported %d Jira issues into the backlog" % len(made)
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

def _log():
    try:
        with open(CHATLOG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def _append_log(user, entries):
    d = _log()
    d.setdefault(user, []).extend(entries)
    d[user] = d[user][-80:]
    tmp = CHATLOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, CHATLOG)

def history(user):
    """The user's persisted copilot transcript (the same Claude session the
    backend resumes - session id in copilot_sessions.json, resumable even from
    a terminal via `claude --resume <id>`)."""
    return {"messages": _log().get(user, []),
            "session_id": _sessions().get(user)}

# live copilot subprocess per user, so the chat's Stop button can kill a turn.
_running = {}
_cancelled = set()


def cancel(user):
    """Stop this user's in-flight copilot turn (the chat Stop button)."""
    _cancelled.add(user)
    p = _running.get(user)
    if p:
        try:
            p.terminate()
        except Exception:
            pass
    return bool(p)


def chat(user, message, role="operator", model="", thinking="", attachments=None, card=None):
    """One copilot turn for this user. Returns {reply, actions, cost, usage}.
    model/thinking/attachments come from the shared composer and resolve through
    turnopts (same whitelist + Auto routing the card chat uses). `card` = the id of
    a card the user is currently viewing, so 'this card' / 'it' resolves to it -
    the same free agent, reachable from within a card."""
    import turnopts
    sess = _sessions()
    sid = sess.get(user)
    paths = turnopts.save_attachments(os.path.join(ROOT, ".copilot_attachments", user),
                                      attachments)
    cli_model, _ = turnopts.resolve_model(model, message, bool(paths))
    body = turnopts.augment_prompt(message, thinking, paths)
    focus = ""
    if card:
        ct = _find_card(card)
        if ct and not isinstance(ct, list):
            focus = ("\n\nCURRENT CARD (the user is viewing this - resolve 'this card' / 'it' "
                     "to it; a plain work instruction means steer it): %s | %s | %s"
                     % (ct["id"], ct.get("branch"), (ct.get("task") or "")[:80]))
    prompt = SYSTEM + "\n\nBOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M") \
        + _snapshot() + focus + "\n\nUSER (%s): %s" % (user, body)
    cmd = ["cmd", "/c", CLAUDE, "-p", "--output-format", "json",
           "--permission-mode", "plan"]
    if cli_model:              # whitelist only - no arbitrary model ids from the client
        cmd += ["--model", cli_model]
    if sid:
        cmd += ["--resume", sid]
    # encoding="utf-8" is REQUIRED: without it Windows decodes claude's UTF-8
    # output as cp1252 and mangles em dashes / arrows into mojibake in the chat.
    _cancelled.discard(user)
    p = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    _running[user] = p
    try:
        stdout, stderr = p.communicate(input=prompt, timeout=300)
    finally:
        _running.pop(user, None)
    if user in _cancelled:                 # Stop was pressed
        _cancelled.discard(user)
        return {"reply": "(stopped)", "actions": [], "cost": None, "usage": None}
    if not (stdout or "").strip():
        raise RuntimeError("copilot no output: " + (stderr or "").strip()[:200])
    d = json.loads(stdout)
    if d.get("session_id"):
        sess[user] = d["session_id"]
        _save_sessions(sess)
    txt = d.get("result", "")
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        out = json.loads(m.group(0)) if m else {"reply": txt, "actions": []}
    except ValueError:
        out = {"reply": txt, "actions": []}
    u = d.get("usage") or {}
    usage = {"in": (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0)),
             "out": u.get("output_tokens", 0), "cost": d.get("total_cost_usd")}
    acts = out.get("actions", [])[:6]
    # Persist the exchange NOW and return immediately, so the chat is responsive.
    # Actions (moves, MERGES, steers - potentially minutes) run in the BACKGROUND
    # and append their results to the transcript as they land; the chat polls, so
    # you see them live. This is why 'move 4 cards to done' no longer freezes.
    _append_log(user, [{"cls": "you", "text": message, "ts": time.strftime("%H:%M")},
                       {"cls": "bot", "text": out.get("reply", ""), "ts": time.strftime("%H:%M"), "usage": usage}])
    if acts:
        def _run_bg():
            done = []
            for a in acts:
                try:
                    done.append(_run_action(a, user, role))
                except Exception as e:
                    done.append("action failed: %s" % str(e)[:200])
            if done:
                _append_log(user, [{"cls": "act", "text": r} for r in done])
        threading.Thread(target=_run_bg, daemon=True, name="copilot-actions").start()
    return {"reply": out.get("reply", ""), "actions": [],
            "cost": d.get("total_cost_usd"), "usage": usage}
