# -*- coding: utf-8 -*-
"""Board-copilot action parsing AND execution - extracted from copilot.py
(god-file breakup, see daemon/spine/registry/debt.py daemon-god-files).
_parse_reply_actions/_strip_actions_live are pure text (splitting a reply
into prose + actions[]); _run_action is the EXECUTION half - one board
action in, its plain-language result out. Both halves genuinely belong
under "actions" (parse what the model said -> run what it asked for), so
this stayed one module rather than splitting parsing from execution.
copilot.py re-imports everything. Not monkeypatched."""
import json
import os
import re
import threading

_ACTIONS_FENCE = re.compile(r"```actions\s*(.*?)```", re.S)


def _strip_actions_live(partial):
    """The live view of a streaming reply: drop everything from the ```actions
    fence (or a lone ``` / a leading raw-JSON blob) onward, so the user watches
    PROSE stream in, not the raw action tail."""
    if not partial:
        return partial
    s = partial.lstrip()
    if s.startswith("{"):          # legacy JSON-blob reply - nothing prose to show yet
        return ""
    for marker in ("```actions", "```"):
        i = partial.find(marker)
        if i != -1:
            return partial[:i].rstrip()
    return partial


def _parse_reply_actions(txt):
    """(reply_prose, actions[]). New contract: prose reply + optional trailing
    ```actions [..]``` block. Falls back to the legacy {"reply","actions"} JSON
    blob, then to 'the whole text is the reply'."""
    txt = txt or ""
    mf = _ACTIONS_FENCE.search(txt)
    if mf:
        reply = txt[:mf.start()].strip()
        try:
            acts = json.loads(mf.group(1).strip())
            acts = [acts] if isinstance(acts, dict) else acts
            return reply, (acts if isinstance(acts, list) else [])
        except ValueError:
            return reply, []
    mb = re.search(r"\{.*\}", txt, re.S)      # legacy blob
    if mb:
        try:
            o = json.loads(mb.group(0))
            if isinstance(o, dict) and ("reply" in o or "actions" in o):
                return o.get("reply", ""), (o.get("actions") or [])
        except ValueError:
            pass
    return txt.strip(), []


def _find_card(frag):
    from daemon.cells.engineer import sessions
    frag = frag.lower()
    hits = [t for t in sessions.list_tracks()
            if frag in t["id"].lower() or frag in t["branch"].lower()
            or frag in t["task"].lower()]
    return hits[0] if len(hits) == 1 else (hits if hits else None)


ALLOWED_CONFIG = {"policy", "capacity", "value_per_card", "default_repo",
                  "registration", "dashboard", "prices", "currency", "appearance", "jira"}


# -- never dead-end: every refusal carries the route that IS open -------------
# Same rule the PM coordinator follows (pm._unblock_proposal) and the card
# agents follow (harness/agents/card-worker.md): a boundary must produce a pointer to the
# workflow, not a full stop. These helpers make the ACTION layer obey it too -
# the model can be prompted to be helpful, but the code must not answer a
# missed card reference with "failed." and nothing else.

def _card_hint(kind, frag, hits):
    """A miss on a card reference, answered with the actual candidates so the
    owner's next message resolves it in one move."""
    from daemon.cells.engineer import sessions
    if hits:
        opts = "; ".join("%s (%s, %s)" % (t["branch"], t["id"], t.get("lane"))
                         for t in hits[:6])
        return ("%s: '%s' passt auf %d Karten - welche? %s" % (kind, frag, len(hits), opts))
    near = [t for t in sessions.list_tracks() if t.get("lane") != "done"][:6]
    opts = "; ".join("%s (%s)" % (t["branch"], t.get("lane")) for t in near) or "keine offenen Karten"
    return ("%s: keine Karte passt auf '%s'. Offen sind gerade: %s" % (kind, frag, opts))


def _denied(kind, role, roles, key, extra=""):
    """A role refusal, answered with the exact policy key that opens it."""
    return ("%s ist fuer die Rolle '%s' gesperrt (erlaubt: %s). Der Owner kann das mit "
            "%s aendern%s." % (kind, role, "/".join(roles), key, (" - " + extra) if extra else ""))


def _run_action(a, actor, role="operator"):
    from daemon.cells.engineer import sessions
    from daemon.cells.process import processes
    from daemon.spine.storage import events
    kind = a.get("type")
    if kind == "configure":
        allowed_roles = (events.settings().get("policy") or {}).get("chat_configure_roles", ["owner"])
        if role not in allowed_roles:
            return _denied("configure", role, allowed_roles, "policy.chat_configure_roles")
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
            # a fixed key is harness, not policy - but that is a ROUTE, not a wall:
            # the harness is changed by changing its code, which is a card.
            return ("%s ist Teil des Harness (Auth/Audit/Gate/Driver), nicht der Policy - "
                    "per Chat nicht schaltbar. Wenn es sich wirklich aendern soll, ist das "
                    "eine Code-Aenderung: sag 'leg eine Karte dafuer an', dann baut ein Agent "
                    "es mit Gate und deiner Abnahme. Die restlichen Keys kann ich sofort setzen."
                    % ", ".join(sorted(bad)))
        from daemon.spine.storage import events as _ev
        _ev.save_settings(patch, actor=actor, reason="via chat")
        _ev.emit("config", "-", actor=actor, patch=patch)
        return "policy updated: " + json.dumps(patch)[:300]
    if kind == "machine_task":
        # The board reaching the PC. The chat executes nothing itself - it
        # dispatches an agent into a real folder on this machine (see
        # sessions.new_machine_task). Owner-gated, audited, no merge path.
        pol = sessions.machine_policy()
        roles = pol.get("roles") or ["owner"]
        if not pol.get("enabled", True):
            return ("Maschinen-Aufgaben sind aus (policy.machine.enabled=false). Der Owner "
                    "kann sie mit policy.machine.enabled=true wieder freigeben.")
        if role not in roles:
            return _denied("machine_task", role, roles, "policy.machine.roles")
        task = (a.get("task") or "").strip()
        if not task:
            return "machine_task: sag mir in einem Satz, was auf dem Rechner passieren soll."
        try:
            t = sessions.new_machine_task(
                a.get("cwd") or os.path.expanduser("~"), task, actor=actor,
                priority=a.get("priority", "medium"),
                dispatch=a.get("dispatch", True) is not False)
        except RuntimeError as e:
            return "machine_task: %s" % e
        return ("Maschinen-Aufgabe gestartet (%s, Ordner %s) - der Agent arbeitet auf dem "
                "Rechner, du siehst alles auf der Karte." % (t["id"], t.get("worktree")))
    if kind == "direct_task":
        # Paseo-style direct build: the repo's LIVE tree is the workplace (see
        # sessions.new_direct_task - no worktree/branch/merge/gate, serialized
        # per tree). Same policy switch/roles as machine work - it IS work on
        # the owner's machine, just aimed at the repo.
        pol = sessions.machine_policy()
        roles = pol.get("roles") or ["owner"]
        if not pol.get("enabled", True):
            return ("Direkt-Builds sind aus (policy.machine.enabled=false). Der Owner "
                    "kann sie mit policy.machine.enabled=true wieder freigeben.")
        if role not in roles:
            return _denied("direct_task", role, roles, "policy.machine.roles")
        task = (a.get("task") or "").strip()
        if not task:
            return "direct_task: sag mir in einem Satz, was direkt gebaut werden soll."
        repo = a.get("repo") or events.settings().get("default_repo")
        if not repo:
            return ("direct_task: kein Repo bekannt - settings default_repo setzen "
                    "(configure) oder das Repo explizit mitgeben.")
        try:
            t = sessions.new_direct_task(
                repo, task, actor=actor,
                priority=a.get("priority", "medium"),
                dispatch=a.get("dispatch", True) is not False)
        except RuntimeError as e:
            return "direct_task: %s" % e
        return ("Direkt-Build gestartet (%s) - der Agent arbeitet OHNE Worktree direkt "
                "im Baum %s. Kein Gate, kein Merge: was er ändert, ist sofort da."
                % (t["id"], t.get("worktree")))
    if kind == "file_card":
        repo = events.settings().get("default_repo")
        if not repo:
            return ("file_card: es ist kein default_repo gesetzt. Entweder settings "
                    "default_repo auf das Projekt setzen (configure), oder ich mache es "
                    "als machine_task auf dem Rechner - sag mir welches.")
        branch = "chat-" + "".join(ch if ch.isalnum() else "-" for ch in a["task"].lower())[:24]
        t = sessions.new_track(repo, branch, a["task"],
                               lane="working" if a.get("dispatch") else "backlog",
                               value=a.get("value"), driver=a.get("driver", "claude"),
                               actor=actor, priority=a.get("priority", "medium"),
                               due=a.get("due", ""))
        return "filed card %s (%s)" % (t["id"], t["lane"])
    if kind in ("move", "steer", "delete", "archive"):
        t = _find_card(a.get("card", ""))
        if t is None or isinstance(t, list):
            return _card_hint(kind, a.get("card", ""), t if isinstance(t, list) else [])
        # admin gate: MOVING / DELETING / ARCHIVING a card is a structural change -
        # only authorized roles may (policy.chat_admin_roles, default owner+operator).
        # steer stays open (clients steer their own cards).
        if kind in ("move", "delete", "archive"):
            admin_roles = (events.settings().get("policy") or {}).get("chat_admin_roles", ["owner", "operator"])
            if role not in admin_roles:
                return _denied(kind, role, admin_roles, "policy.chat_admin_roles",
                               "steuern (steer) darfst du die Karte aber jederzeit")
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
            return _denied("resolve_blocker", role, admin_roles, "policy.chat_admin_roles")
        t = _find_card(a.get("card", ""))
        if t is None or isinstance(t, list):
            return _card_hint("resolve_blocker", a.get("card", ""), t if isinstance(t, list) else [])
        return sessions.park_and_retry_merge(t["id"], actor=actor)
    if kind == "resolve_conflict":
        # A REAL <<<<<< merge conflict: set up/reuse markers in the worker's own
        # worktree and STEER the card's agent to merge them by plain editing. The
        # chat never edits code, but it can dispatch the card's agent to. Admin-
        # gated like steer-that-changes-state.
        admin_roles = (events.settings().get("policy") or {}).get("chat_admin_roles", ["owner", "operator"])
        if role not in admin_roles:
            return _denied("resolve_conflict", role, admin_roles, "policy.chat_admin_roles")
        t = _find_card(a.get("card", ""))
        if t is None or isinstance(t, list):
            return _card_hint("resolve_conflict", a.get("card", ""), t if isinstance(t, list) else [])
        return sessions.dispatch_conflict_resolution(t["id"], actor=actor)
    if kind == "fast_track":
        # Per-card FAST-TRACK: a flagged card with a green gate + clean merge lands
        # + deploys automatically (no human accept). Scoped to THIS card; every
        # other card stays human-gated. The gate still guards. Admin-gated.
        admin_roles = (events.settings().get("policy") or {}).get("chat_admin_roles", ["owner", "operator"])
        if role not in admin_roles:
            return _denied("fast_track", role, admin_roles, "policy.chat_admin_roles")
        t = _find_card(a.get("card", ""))
        if t is None or isinstance(t, list):
            return _card_hint("fast_track", a.get("card", ""), t if isinstance(t, list) else [])
        on = a.get("on", True)
        sessions.update_track(t["id"], {"fast_track": bool(on)}, actor=actor)
        return (("%s ist jetzt im Fast-Track: gruenes Gate -> auto-merge + auto-deploy (OTA), ohne Abnahme. "
                 "Rotes Gate bounct weiterhin." % t["branch"]) if on
                else "%s: Fast-Track aus - wieder human-gated (Abnahme durch dich)." % t["branch"])
    if kind == "set_driver":
        # Capability grant (windows-mcp/GUI control), not a cosmetic setting -
        # admin-gated like fast_track, and update_track itself refuses an
        # unknown driver or a change mid-turn (sessions.update_track).
        admin_roles = (events.settings().get("policy") or {}).get("chat_admin_roles", ["owner", "operator"])
        if role not in admin_roles:
            return _denied("set_driver", role, admin_roles, "policy.chat_admin_roles")
        t = _find_card(a.get("card", ""))
        if t is None or isinstance(t, list):
            return _card_hint("set_driver", a.get("card", ""), t if isinstance(t, list) else [])
        driver = a.get("driver") or ""
        try:
            sessions.update_track(t["id"], {"driver": driver}, actor=actor)
        except (RuntimeError, ValueError) as e:
            return "set_driver failed: %s" % e
        return "%s: Treiber auf '%s' gesetzt." % (t["branch"], driver)
    if kind == "build_integration":
        from daemon.cells.connectors import connectors
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
        from daemon.cells.connectors import connectors
        made = connectors.run_connector(a.get("name", ""), actor=actor)
        return "connector ran: %d new backlog cards" % len(made)
    if kind == "rollback_connector":
        from daemon.cells.connectors import connectors
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
        from daemon.spine.ops import importers
        p2 = importers.url_import(a.get("url", ""), client=a.get("client", ""),
                                  due=a.get("due", ""), actor=actor)
        return "imported %s - agent is deriving the process steps" % a.get("url")
    if kind == "import_jira":
        from daemon.spine.ops import importers
        made = importers.jira_import(a.get("jql", ""), actor=actor)
        return "imported %d Jira issues into the backlog" % len(made)
    if kind == "clarify_goal":
        # The owner answered a PM open_question / corrected a plan fact IN CHAT.
        # brief() previously never read chat, only the goal text + board - so the
        # answer was heard but the next plan repeated the same question. This
        # folds it into the planner's ground truth (pm.add_clarification) and
        # re-plans NOW, one turn, so the chat is a real answer channel, not a
        # dead end that still requires editing the Ziel field by hand.
        from daemon.cells.pm import pm
        text = (a.get("text") or "").strip()
        if not text:
            return "clarify_goal: kein Text übergeben"
        if not pm.get_goal():
            return "clarify_goal: kein Ziel gesetzt - nichts zum Klarstellen"
        pm.add_clarification(text, actor=actor)
        try:
            pm.brief()
        except Exception as e:
            return "Notiert: „%s“ - Re-Plan ist fehlgeschlagen (%s), läuft beim nächsten Mal mit." % (
                text[:120], str(e)[:150])
        return "Notiert: „%s“ - Plan neu gerechnet." % text[:150]
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
    # NEVER DROP THE REQUEST: an unimplemented action type is almost always the
    # model reaching for a capability the board has no verb for (open an app,
    # fix the printer, tidy a folder). That is what a machine task is - route it
    # there instead of answering "unknown action type" and losing what was asked.
    payload = " ".join(str(a[k]) for k in ("task", "text", "request", "prompt", "spec",
                                           "instruction", "command") if a.get(k))
    if payload.strip():
        routed = dict(a, type="machine_task", task=payload.strip())
        return ("'%s' ist keine eingebaute Aktion - ich hab sie als Maschinen-Aufgabe "
                "weitergegeben. %s" % (kind, _run_action(routed, actor, role)))
    return ("'%s' kann ich nicht direkt ausfuehren. Ich kann: Karten anlegen/steuern/"
            "verschieben, Aufgaben auf dem Rechner erledigen lassen (machine_task), "
            "Blocker und Merge-Konflikte aufloesen, Prozesse anlegen, Policy setzen, "
            "Connectoren bauen und laufen lassen. Sag mir in einem Satz, was passieren "
            "soll - ich such den Weg." % kind)
