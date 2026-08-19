# -*- coding: utf-8 -*-
"""Data flows in: pull work from other systems onto the board.

  jira_import(jql)  - Jira Cloud REST API v3 -> backlog cards. Credentials
                      live in settings.jira {base, email, api_token}; priority,
                      due date and project->client are mapped; the Jira key is
                      kept in the task so cards are traceable back.
  url_import(url)   - fetch a web page, strip it to text, hand it to the
                      process proposer: the agent turns the page's ask into a
                      step chain you can adjust and accept.
"""
import base64, json, re, urllib.request

PRIO_MAP = {"highest": "urgent", "high": "high", "medium": "medium",
            "low": "low", "lowest": "low"}

def _jira_get(cfg, path):
    req = urllib.request.Request(cfg["base"].rstrip("/") + path, headers={
        "Authorization": "Basic " + base64.b64encode(
            ("%s:%s" % (cfg["email"], cfg["api_token"])).encode()).decode(),
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def _adf_text(node):
    """Flatten Jira's ADF description to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    out = []
    if isinstance(node, dict):
        if node.get("text"):
            out.append(node["text"])
        for c in node.get("content", []):
            out.append(_adf_text(c))
    elif isinstance(node, list):
        out = [_adf_text(c) for c in node]
    return " ".join(x for x in out if x)

def jira_import(jql, actor="owner", limit=50):
    from daemon.spine import events
    from daemon.cells.engineer import sessions
    cfg = events.settings().get("jira") or {}
    if not (cfg.get("base") and cfg.get("email") and cfg.get("api_token")):
        raise RuntimeError("configure settings.jira first (base, email, api_token)")
    repo = events.settings().get("default_repo")
    if not repo:
        raise RuntimeError("no default_repo preset")
    q = "/rest/api/3/search/jql?jql=%s&maxResults=%d&fields=summary,description,priority,duedate,project,key" % (
        urllib.parse.quote(jql or "order by created DESC"), min(limit, 100))
    data = _jira_get(cfg, q)
    made = []
    for iss in data.get("issues", []):
        f = iss.get("fields", {})
        task = "[%s] %s" % (iss.get("key"), f.get("summary") or "")
        desc = _adf_text(f.get("description"))[:600]
        if desc:
            task += "\n\n" + desc
        prio = PRIO_MAP.get(((f.get("priority") or {}).get("name") or "").lower(), "medium")
        t = sessions.new_track(
            repo, "jira-" + (iss.get("key") or "x").lower(), task,
            lane="backlog", client=(f.get("project") or {}).get("key", "jira"),
            actor=actor, priority=prio, due=f.get("duedate") or "")
        made.append(t["id"])
    events.emit("import", "-", source="jira", jql=jql, count=len(made), actor=actor)
    return made

def url_import(url, client="", due="", actor="owner"):
    from daemon.spine import events
    from daemon.cells.process import processes
    if not re.match(r"^https?://", url):
        raise RuntimeError("http(s) URL required")
    req = urllib.request.Request(url, headers={"User-Agent": "HelmDeck/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read(400_000).decode("utf-8", "replace")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()[:4000]
    p = processes.create(
        "Imported from %s - derive the actionable work from this page:\n\n%s" % (url, text),
        client=client, due=due, actor=actor)
    events.emit("import", p["id"], source="url", url=url, actor=actor)
    return p
