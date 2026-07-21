# -*- coding: utf-8 -*-
"""Plane bridge - Plane (self-hosted, localhost:8090) is the UI, SwarmDeck stays
the brain. Tickets need NO repo path: each Plane project is preset to a repo in
settings.json ("plane.repos": {project-name: repo-path}, "plane.default_repo"
as fallback). The bridge polls the Plane REST API and maps both ways:

  Plane -> SwarmDeck: issue in Backlog/Todo  -> track filed (backlog)
                      issue in In Progress   -> dispatched (worktree + session)
                      issue in Done          -> accepted (economics recorded)
                      new human comment      -> steer to the live session
  SwarmDeck -> Plane: agent reply            -> posted as a comment
                      gate result            -> comment (green: ready to review,
                                                red: punch list)

Link state lives in plane_links.json. Auth: personal API token (X-API-Key),
created once in Plane under Settings > API tokens, stored in settings.json
as plane.api_token."""
import json, os, threading, time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
LINKS = os.path.join(ROOT, "plane_links.json")

def _cfg():
    import events
    s = events.settings()
    p = s.get("plane") or {}
    p.setdefault("base", "http://localhost:8090")
    p.setdefault("api_token", "")
    p.setdefault("workspace", "")
    p.setdefault("repos", {})
    p.setdefault("default_repo", "")
    p.setdefault("poll_secs", 20)
    return p

def _api(p, path, method="GET", body=None):
    url = p["base"].rstrip("/") + "/api/v1" + path
    req = urllib.request.Request(url, method=method,
        headers={"X-API-Key": p["api_token"], "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")

def _paged(p, path):
    out, cursor = [], None
    while True:
        d = _api(p, path + ("&" if "?" in path else "?") + "per_page=100"
                 + (("&cursor=" + cursor) if cursor else ""))
        if isinstance(d, list):
            return d
        out += d.get("results", [])
        if not d.get("next_page_results"):
            return out
        cursor = d.get("next_cursor")

def _links():
    if not os.path.exists(LINKS):
        return {}
    try:
        with open(LINKS, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        return {}

def _save_links(l):
    tmp = LINKS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(l, f, indent=2)
    os.replace(tmp, LINKS)

def _comment(p, ws, proj, issue, html):
    try:
        _api(p, "/workspaces/%s/projects/%s/issues/%s/comments/" % (ws, proj, issue),
             "POST", {"comment_html": html})
    except Exception as e:
        print("plane-bridge: comment failed:", e)

def _esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;")

def _sync_once():
    import sessions
    p = _cfg()
    if not p["api_token"]:
        return "no plane.api_token in settings.json - bridge idle"
    ws = p["workspace"]
    if not ws:
        w = _paged(p, "/workspaces/") if False else _api(p, "/workspaces/")
        items = w.get("results", w) if isinstance(w, dict) else w
        if not items:
            return "no workspace"
        ws = items[0]["slug"]
        import events
        events.save_settings({"plane": dict(p, workspace=ws)})
    links = _links()
    tracks = {t["id"]: t for t in sessions.list_tracks()}
    for proj in _paged(p, "/workspaces/%s/projects/" % ws):
        pid, pname = proj["id"], proj["name"]
        repo = p["repos"].get(pname) or p["default_repo"]
        if not repo:
            continue
        states = {s["id"]: s for s in _paged(p, "/workspaces/%s/projects/%s/states/" % (ws, pid))}
        for iss in _paged(p, "/workspaces/%s/projects/%s/issues/" % (ws, pid)):
            iid = iss["id"]
            group = (states.get(iss.get("state")) or {}).get("group", "backlog")
            L = links.get(iid)
            if group == "cancelled":
                continue
            # -- new issue: file it, repo comes from the project preset --
            if not L:
                branch = "plane-" + (iss.get("name") or "task")[:24]
                task = (iss.get("name") or "") + "\n\n" + _strip_html(iss.get("description_html") or "")
                t = sessions.new_track(repo, branch, task.strip(), lane="backlog")
                links[iid] = L = {"track": t["id"], "project": pid, "last_comment": "",
                                  "group": group, "notified": ""}
                _save_links(links)
                _comment(p, ws, pid, iid,
                         "<p>SwarmDeck: filed as track <code>%s</code> on repo <code>%s</code></p>"
                         % (t["id"], _esc(repo)))
            t = tracks.get(L["track"]) or sessions.get_track(L["track"])
            if not t:
                continue
            # -- state moved in Plane: drive the lane --
            if group != L.get("group"):
                try:
                    if group == "started" and t["lane"] in ("backlog",):
                        threading.Thread(target=sessions.move_lane,
                                         args=(t["id"], "working"), daemon=True).start()
                    elif group == "completed" and t["lane"] != "done":
                        sessions.move_lane(t["id"], "done")
                except Exception as e:
                    print("plane-bridge: lane sync failed:", e)
                L["group"] = group
                _save_links(links)
            # -- new human comments -> steer --
            try:
                cs = _paged(p, "/workspaces/%s/projects/%s/issues/%s/comments/" % (ws, pid, iid))
            except Exception:
                cs = []
            fresh = []
            seen = L.get("last_comment") or ""
            for c in sorted(cs, key=lambda c: c.get("created_at", "")):
                if c.get("created_at", "") <= seen:
                    continue
                txt = _strip_html(c.get("comment_html") or "")
                if txt.startswith("SwarmDeck:") or not txt.strip():
                    continue
                if not c.get("actor_detail", {}).get("is_bot"):
                    fresh.append((c.get("created_at", ""), txt))
            if fresh:
                L["last_comment"] = fresh[-1][0]
                _save_links(links)
                text = "\n".join(f[1] for f in fresh)
                def _steer(tid=t["id"], text=text, pid=pid, iid=iid, ws=ws, p=p):
                    try:
                        r = sessions.steer(tid, text)
                        _comment(p, ws, pid, iid, "<p>SwarmDeck: <b>agent</b></p><p>%s</p>"
                                 % _esc(r.get("last_reply", ""))[:4000])
                    except Exception as e:
                        _comment(p, ws, pid, iid, "<p>SwarmDeck: steer failed: %s</p>" % _esc(e))
                threading.Thread(target=_steer, daemon=True).start()
            # -- agent finished a turn we haven't reported -> comment + gate --
            stamp = t.get("updated", "")
            if t.get("status") == "needs_you" and stamp and stamp != L.get("notified"):
                L["notified"] = stamp
                _save_links(links)
                if not fresh:   # steer thread already posts its own reply
                    _comment(p, ws, pid, iid, "<p>SwarmDeck: <b>agent</b></p><p>%s</p>"
                             % _esc(t.get("last_reply", ""))[:4000])
                ok, problems = sessions._gate(t)
                if ok:
                    sessions.move_lane(t["id"], "review")
                    _comment(p, ws, pid, iid,
                             "<p>SwarmDeck: gate GREEN - submitted, ready for your review. "
                             "Move the ticket to Done to accept.</p>")
                else:
                    _comment(p, ws, pid, iid, "<p>SwarmDeck: gate RED - %s</p>"
                             % _esc(" | ".join(x.split("\n")[0] for x in problems))[:1000])
    return "ok"

def _strip_html(h):
    import re
    return re.sub(r"<[^>]+>", " ", h or "").replace("&amp;", "&").replace("&lt;", "<").strip()

def loop():
    print("plane-bridge: polling", _cfg()["base"])
    while True:
        try:
            msg = _sync_once()
            if msg != "ok":
                print("plane-bridge:", msg)
        except Exception as e:
            print("plane-bridge error:", e)
        time.sleep(_cfg()["poll_secs"])

def start_thread():
    threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    loop()
