# -*- coding: utf-8 -*-
"""Board-copilot action parsing AND execution - extracted from copilot.py
(god-file breakup, see spine/registry/debt.py daemon-god-files).
_parse_reply_actions/_strip_actions_live are pure text (splitting a reply
into prose + actions[]); _run_action is the EXECUTION half - one board
action in, its plain-language result out. Both halves genuinely belong
under "actions" (parse what the model said -> run what it asked for), so
this stayed one module rather than splitting parsing from execution.
copilot.py re-imports everything. Not monkeypatched."""
import json
import os
import re

_ACTIONS_FENCE = re.compile(r"```actions\s*(.*?)```", re.S)


def _strip_actions_live(partial):
    """The live view of a streaming reply: drop everything from the ```actions
    fence (or a lone ``` / a leading raw-JSON blob / a memory sentinel tag)
    onward, so the user watches PROSE stream in, never a raw action tail or a
    half-typed <memory-save> block (henry-memory-db-authority phase 1 - same
    flicker copilot_memory.parse cleans up in the FINISHED reply; this is the
    streaming counterpart, spine/ops/ask.strip_stream's own reason for being)."""
    if not partial:
        return partial
    s = partial.lstrip()
    if s.startswith("{"):          # legacy JSON-blob reply - nothing prose to show yet
        return ""
    # the EARLIEST marker wins, not the first one checked: a memory block can
    # precede the ```actions fence in a reply, and a first-match-wins scan
    # would let it leak into the live view whole before the later fence cut it.
    cuts = [partial.find(m) for m in ("```actions", "```", "<memory-save", "<memory-delete")]
    cuts = [i for i in cuts if i != -1]
    if cuts:
        return partial[:min(cuts)].rstrip()
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
    from cells.engineer.cards import sessions
    frag = frag.lower()
    tracks = sessions.list_tracks()
    # AN EXACT ID IS NOT A GUESS, so it is not put to a vote.
    #
    # Card ids are unique by construction: a needle that IS one names exactly
    # one card, even when other cards happen to QUOTE it in their task text.
    # Measured on the owner's board (2026-08-30): a FINISHED card whose brief
    # opened "Kontext: Karte 20260830-081301-direct hat gerade ..." made every
    # steer at the RUNNING card of that id ambiguous. His watch-dictated
    # instruction reached Henry, bounced here with "passt auf 2 Karten" and
    # never reached the card - which from the wrist is indistinguishable from
    # the message never arriving in the system at all.
    #
    # Checked BEFORE the substring sweep, which is the whole fix: that sweep is
    # a convenience for a human naming a card loosely, and it must never
    # outrank an identifier that already names one exactly.
    for t in tracks:
        if (t.get("id") or "").lower() == frag:
            return t
    hits = [t for t in tracks
            if frag in t["id"].lower() or frag in t["branch"].lower()
            or frag in t["task"].lower()]
    return hits[0] if len(hits) == 1 else (hits if hits else None)


ALLOWED_CONFIG = {"policy", "capacity", "value_per_card", "default_repo",
                  "registration", "dashboard", "prices", "currency", "appearance", "jira"}


# -- never dead-end: every refusal carries the route that IS open -------------
# Same rule the PM coordinator follows (pm._unblock_proposal) and the card
# agents follow (cells/engineer/harness/agents/card-worker.md): a boundary must produce a pointer to the
# workflow, not a full stop. These helpers make the ACTION layer obey it too -
# the model can be prompted to be helpful, but the code must not answer a
# missed card reference with "failed." and nothing else.

def _card_hint(kind, frag, hits):
    """A miss on a card reference, answered with the actual candidates so the
    owner's next message resolves it in one move."""
    from cells.engineer.cards import sessions
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


# -- the repo-template verbs' helpers ----------------------------------------
# The refusals below are the reason set_station is not a generic key setter.
# "Schalt das Gate ab" is the ambiguous sentence the decree itself used as the
# test case: it can mean three different things (PRD §4.3.3), and answering it
# with "no" would be wrong for two of them. So the refusal NAMES the readings and
# offers the one that is actually doable - amber question, not red wall.
_STATION_LAW = {
    "backlog": ("Das Backlog ist der Eingang - da kommen Karten an. Es gibt nichts "
                "abzuschalten. Wenn du meinst 'nichts soll von selbst starten': das "
                "ist policy.auto_dispatch_priority, sag es und ich setz es."),
    "working": ("'Arbeit' ist die Station, in der der Agent laeuft - ohne sie gaebe es "
                "keine Karte. Wenn du meinst 'ohne eigenen Worktree arbeiten': das "
                "haengt an der Repo-Vorlage (Dokumente arbeitet direkt im Ordner)."),
    "gate": ("Das Gate ist Harness-Gesetz (gate-before-review) - per Chat nicht "
             "abschaltbar. Drei Dinge koenntest du meinen:\n"
             "1. 'Es soll mich nicht aufhalten' - in einem Doku-Repo laeuft es ohnehin "
             "leer und meldet PASS. Da ist nichts abzuschalten.\n"
             "2. 'Ich will nicht auf die Freigabe warten' - das ist "
             "policy.auto_accept_green. Machbar, sofort, sag Bescheid.\n"
             "3. 'gate-before-review soll ganz weg' - das ist Code, nicht Policy. "
             "Sag 'leg eine Karte dafuer an', dann baut es ein Agent mit Gate und "
             "deiner Abnahme."),
    "review": ("Die Review IST deine Abnahme - sie abzuschalten hiesse, dass Arbeit "
               "ungesehen durchgeht. Was ich anbieten kann: policy.auto_accept_green. "
               "Dann wartet nichts mehr auf dich, geprueft wird trotzdem."),
}


def _station_is_law(station):
    return _STATION_LAW.get(station, "Diese Station ist fest und laesst sich nicht "
                                     "abschalten - nur Deploy ist schaltbar.")


def _pipeline_answer(repo, headline):
    """Confirm a change by DESCRIBING THE RESULTING PIPELINE, not by echoing a key.

    The whole point of the redesign is *sehen statt konfigurieren*: the owner
    asked in words, so the answer is the station row in words, read out of the
    same resolve() the map renders. If chat and map ever disagreed, they would
    disagree here first - and they cannot, because this is that data."""
    try:
        from cells.engineer.cards import sessions
        from spine.ops import projects
        from spine.storage import events as _ev
        view = projects.resolve(repo)
        # The owner's lane RENAMES, same read routes_info does for the map. This
        # passed None and so answered in default labels: chat said "Backlog ->
        # ... -> Review" about a board whose columns are called "Inbox" and
        # "Abnahme". A name he cannot find on his board is not an answer.
        ll = (_ev.settings().get("policy") or {}).get("lane_labels") or {}
        f = sessions.flow(ll, repo_view=view)
        by_key = {n["key"]: n for n in f["nodes"]}
        by_key["gate"] = f["gate"]
        by_key["deploy"] = f["deploy"]

        def _name(k):
            n = by_key.get(k) or {}
            return "%s%s" % (n.get("label") or k, "" if n.get("active") else " (aus)")

        # The SAME picture the pipeline draws: lanes are the stations of the
        # route, gate and deploy are named ON the arrow they run in. Listing all
        # five flat read as five lanes and silently dropped "Fertig" - the chat
        # and the map must not describe the machine differently.
        draw = f.get("row") or {}
        lanes = draw.get("lanes") or [n["key"] for n in f["nodes"]]
        on_edge = {}
        for s in draw.get("steps") or []:
            on_edge.setdefault(s.get("after"), []).append(_name(s["key"]))
        row = []
        for i, k in enumerate(lanes):
            row.append(_name(k))
            if i < len(lanes) - 1:
                here = on_edge.get(k) or []
                row.append("-(%s)->" % ", ".join(here) if here else "->")
        tail = ""
        if view.get("deviations"):
            tail = ("\nVom Vorlagen-Standard abgewichen: %s."
                    % ", ".join(d["key"] for d in view["deviations"]))
        # `row` already carries its own arrows (a step names the edge it runs
        # in), so this joins with a SPACE - " -> " here would double them.
        return "%s\nStrecke: %s.%s" % (headline, " ".join(row), tail)
    except Exception as e:                                   # noqa: BLE001
        # A confirmation that dies is worse than a plain one: the change ALREADY
        # happened, so say so rather than letting an exception read as failure.
        return "%s (Strecke konnte ich gerade nicht zeichnen: %s)" % (headline, str(e)[:120])


def _note_overrides(repo, patch, actor):
    """Record which of this repo's template values the owner just moved.

    Only ever records keys the template ACTUALLY set (`applied`) - a settings
    change that the template never had an opinion on is not a deviation from it,
    and marking it as one would make the map cry wolf. Total: a failure to note
    a deviation must never undo a change that already succeeded."""
    if not repo:
        return
    try:
        from spine.ops import projects
        view = projects.resolve(repo)
        if not view.get("template"):
            return
        applied = view.get("applied") or {}
        for top, sub in list(patch.items()):
            pairs = sub.items() if isinstance(sub, dict) else [(None, sub)]
            for k, v in pairs:
                dotted = "%s.%s" % (top, k) if k is not None else top
                if dotted in applied and applied[dotted] != v:
                    projects.set_override(view["repo"], dotted, v, actor=actor)
    except Exception as e:                                   # noqa: BLE001
        print("copilot: noting overrides for %s failed: %s" % (repo, e), flush=True)


def _tag(a, t):
    """Remember on the ACTION which card it produced/touched. The result is a
    sentence (Henry reads it next turn); the chat needs the id to draw a tile
    that opens the card's thread (threads.py) - parsing the sentence back
    would be a heuristic, this is the record."""
    try:
        from cells.copilot.chat import card_mirror
        a["_card"] = t["id"]
        a["_card_name"] = card_mirror.short_name(t)
    except Exception:                                    # noqa: BLE001
        pass
    return t


def _run_action(a, actor, role="operator"):
    from cells.engineer.cards import sessions
    from cells.engineer.chains import processes
    from spine.storage import events
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
        from spine.storage import events as _ev
        _ev.save_settings(patch, actor=actor, reason="via chat")
        _ev.emit("config", "-", actor=actor, patch=patch)
        # If this repo runs on a template and the owner just moved one of the
        # values that template set, RECORD the deviation now - at the moment it
        # happens, at the one owner of that field. The pipeline map then RENDERS
        # "vom Standard abgewichen" instead of a later pass deducing it (PRD §5,
        # and CLAUDE.md's no-monkey-patches rule).
        _note_overrides(a.get("repo") or "", patch, actor)
        return "policy updated: " + json.dumps(patch)[:300]
    if kind == "apply_template":
        # "Repo Y soll wie ein Doku-Repo laufen." Calls the SAME mutator the
        # settings screen POSTs to, so a sentence and a tap cannot produce two
        # different answers.
        allowed_roles = (events.settings().get("policy") or {}).get("chat_configure_roles", ["owner"])
        if role not in allowed_roles:
            return _denied("apply_template", role, allowed_roles, "policy.chat_configure_roles")
        from spine.ops import projects
        from spine.registry import templates
        repo = (a.get("repo") or events.settings().get("default_repo") or "").strip()
        if not repo:
            return ("apply_template: welches Repo? Sag mir den Pfad, oder setz ein "
                    "default_repo - ich will nicht das falsche Repo umstellen.")
        tid = (a.get("template") or "").strip()
        if not templates.get(tid):
            return ("apply_template: '%s' kenne ich nicht. Es gibt: %s."
                    % (tid, ", ".join("%s (%s)" % (t["id"], t["label"])
                                      for t in templates.catalog())))
        try:
            projects.apply_template(repo, tid, actor=actor)
        except (ValueError, RuntimeError) as e:
            return "apply_template: %s" % e
        return _pipeline_answer(repo, "Vorlage '%s' gilt jetzt fuer %s." % (tid, repo))
    if kind == "set_station":
        # DELIBERATELY NOT a generic key setter. It takes a STATION NAME, maps it
        # to the one real key behind it, and refuses every fixed station BY NAME.
        # So a model that reaches for "switch off the gate" cannot arrive at
        # save_settings with it - the refusal is structural, not a line in a
        # prompt that the model may or may not honour.
        allowed_roles = (events.settings().get("policy") or {}).get("chat_configure_roles", ["owner"])
        if role not in allowed_roles:
            return _denied("set_station", role, allowed_roles, "policy.chat_configure_roles")
        from spine.ops import projects
        repo = (a.get("repo") or events.settings().get("default_repo") or "").strip()
        if not repo:
            return "set_station: welches Repo? Sag mir den Pfad, oder setz ein default_repo."
        raw = a.get("station") or ""
        st = sessions.station_id(raw)
        if not st:
            return ("set_station: '%s' ist keine Station. Die Strecke ist: %s."
                    % (raw, " -> ".join(sessions.STATIONS)))
        if st not in sessions.SWITCHABLE_STATIONS:
            return _station_is_law(st)
        on = a.get("on")
        cmd = (a.get("command") or "").strip()
        if on is False:
            cmd = ""
        elif not cmd:
            cur = projects.resolve(repo).get("deploy_hook") or ""
            if not cur:
                return ("Deploy anschalten heisst: sag mir den Befehl, der laufen soll "
                        "(z.B. 'bash ops/deploy/push_update.sh'). Ohne Befehl gaebe es "
                        "nichts zu tun - die Station bliebe aus.")
            cmd = cur
        try:
            projects.sight_repo(repo, actor=actor)
            # The hook key must be spelled the way the CARD spells its repo, or
            # the lookup in lanemachine._repo_hook (an exact string match) never
            # hits and the deploy step silently does not run.
            path = projects.norm_repo(repo)
            hooks = dict(events.settings().get("repo_hooks") or {})
            entry = dict(hooks.get(path) or {})
            entry["deploy"] = cmd
            hooks[path] = entry
            events.save_settings({"repo_hooks": hooks}, actor=actor,
                                 reason="Station %s via chat" % st)
            events.emit("config", "-", actor=actor,
                        patch={"repo_hooks.%s.deploy" % path: cmd})
            projects.set_override(path, "repo_hooks.deploy", cmd, actor=actor)
        except (ValueError, RuntimeError) as e:
            return "set_station: %s" % e
        return _pipeline_answer(repo, "Station Deploy ist jetzt %s."
                                % ("AUS" if not cmd else "AN (%s)" % cmd))
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
        _tag(a, t)
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
                dispatch=a.get("dispatch", True) is not False,
                fast_track=a.get("fast_track") is True)
        except RuntimeError as e:
            return "direct_task: %s" % e
        _tag(a, t)
        return ("Direkt-Build gestartet (%s%s) - der Agent arbeitet OHNE Worktree direkt "
                "im Baum %s. Kein Gate, kein Merge: was er ändert, ist sofort da."
                % (t["id"], ", fast-track" if t.get("fast_track") else "",
                   t.get("worktree")))
    if kind == "file_card":
        repo = events.settings().get("default_repo")
        if not repo:
            return ("file_card: es ist kein default_repo gesetzt. Entweder settings "
                    "default_repo auf das Projekt setzen (configure), oder ich mache es "
                    "als machine_task auf dem Rechner - sag mir welches.")
        # Hand new_track the human STEM only - it owns the real branch name
        # (slug + card id, verified free). This used to slug the task here and
        # ship it verbatim, so two cards opening with the same sentence shared a
        # branch AND a worktree; accepting one deleted the other's live tree.
        t = sessions.new_track(repo, "chat-" + a["task"], a["task"],
                               lane="working" if a.get("dispatch") else "backlog",
                               value=a.get("value"), driver=a.get("driver", "claude"),
                               actor=actor, priority=a.get("priority", "medium"),
                               due=a.get("due", ""))
        _tag(a, t)
        return "filed card %s (%s)" % (t["id"], t["lane"])
    if kind in ("move", "steer", "delete", "archive"):
        t = _find_card(a.get("card", ""))
        if t is None or isinstance(t, list):
            return _card_hint(kind, a.get("card", ""), t if isinstance(t, list) else [])
        # admin gate: MOVING / DELETING / ARCHIVING a card is a structural change -
        # only authorized roles may (policy.chat_admin_roles, default owner+operator).
        # steer stays open (clients steer their own cards).
        if kind in ("move", "delete", "archive"):
            from spine.auth import auth
            admin_roles = auth.chat_admin_roles()
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
            # on:false is the way BACK. _snapshot marks archived cards
            # " ARCHIVED" precisely so the owner can ask for one back - but
            # this hardcoded on=True meant chat had no verb for that, and the
            # app only ever archived either, so "hol die Karte zurück" had no
            # route at all. Accept the model's stringy booleans too ("false"),
            # rather than silently archiving again on a restore request.
            on = a.get("on", True)
            if isinstance(on, str):
                on = on.strip().lower() not in ("false", "0", "no", "nein", "off")
            on = bool(on)
            sessions.archive_track(t["id"], on=on, actor=actor)
            return ("archived card %s" if on else "unarchived card %s (back on the board)") % t["branch"]
        from spine.ops import bgthread
        bgthread.spawn("track:steer:" + t["id"], lambda: sessions.steer(
            t["id"], a["text"], actor=actor, source="board copilot"))
        _tag(a, t)
        return "steer sent to %s (agent working in background)" % t["branch"]
    if kind == "hands":
        # Henry's hands: a one-shot sub-agent with the machine tools, no card
        # (cells/copilot/chat/hands.py). The result comes back into Henry's
        # NEXT turn and into the owner's transcript as an act row.
        task = (a.get("task") or "").strip()
        if not task:
            return "hands: keine Aufgabe angegeben."
        from cells.copilot.chat import hands, copilot
        hid = hands.spawn(actor, task, copilot._skey(actor, a.get("card")),
                          card=a.get("card") or None, why=(a.get("why") or "")[:200])
        a["_hands"] = hid
        return ("Hände gestartet (%s): %s - das Ergebnis kommt in deinen naechsten Turn "
                "und in den Chat, sobald es da ist." % (hid, task.splitlines()[0][:90]))
    if kind == "follow_up":
        # The honest replacement for "schau ich mir gleich an" (board-copilot.md
        # forbids that prose now - it promised a check nothing ever performs,
        # since a chat turn ends and nothing wakes Henry up again except the
        # owner's next message). This files a real escalation the BROKER loop
        # picks up within _INTERVAL_S seconds with full tool access (Read/Bash/
        # Grep) and judges like any other - so "ich schau's mir an" becomes a
        # promise the harness itself tracks, not one only the model remembers.
        from spine.registry import escalations
        text = (a.get("text") or "").strip()
        if not text:
            return "follow_up: sag mir in einem Satz, was ich pruefen soll"
        card = a.get("card")
        ct = _find_card(card) if card else None
        card_id = ct["id"] if ct and not isinstance(ct, list) else None
        escalations.emit("henry-followup", card=card_id, detail=text)
        # NOT a fixed-time promise (owner report 2026-09-10: a follow-up sat
        # queued behind a ~5min ship-decision judgement, so "within 90s" was
        # already false the moment something slow was ahead of it in the
        # broker's queue - henry_broker._dispatch_pass now dispatches
        # follow-ups on their own thread precisely so this stays close to
        # true in the common case, but the chat confirmation must not assert
        # a number the broker never actually guaranteed).
        return "notiert - laeuft im Hintergrund (Status: die Zeile ueber dem Eingabefeld)"
    if kind == "resolve_blocker":
        # Unblock a card whose merge is blocked by an uncommitted (dirty) tree in
        # the shared repo checkout - a cross-cutting fix the sandboxed worker
        # can't do. Park the dirty work on a wip-* branch (nothing lost) + retry.
        # Structural + touches the shared checkout -> admin gate, like move.
        from spine.auth import auth
        admin_roles = auth.chat_admin_roles()
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
        from spine.auth import auth
        admin_roles = auth.chat_admin_roles()
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
        from spine.auth import auth
        admin_roles = auth.chat_admin_roles()
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
        from spine.auth import auth
        admin_roles = auth.chat_admin_roles()
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
        from cells.engineer.connectors import connectors
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
        from cells.engineer.connectors import connectors
        made = connectors.run_connector(a.get("name", ""), actor=actor)
        return "connector ran: %d new backlog cards" % len(made)
    if kind == "rollback_connector":
        from cells.engineer.connectors import connectors
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
        from spine.ops import importers
        p2 = importers.url_import(a.get("url", ""), client=a.get("client", ""),
                                  due=a.get("due", ""), actor=actor)
        return "imported %s - agent is deriving the process steps" % a.get("url")
    if kind == "import_jira":
        from spine.ops import importers
        made = importers.jira_import(a.get("jql", ""), actor=actor)
        return "imported %d Jira issues into the backlog" % len(made)
    if kind == "clarify_goal":
        # The owner answered a PM open_question / corrected a plan fact IN CHAT.
        # brief() previously never read chat, only the goal text + board - so the
        # answer was heard but the next plan repeated the same question. This
        # folds it into the planner's ground truth (pm.add_clarification) and
        # re-plans NOW, one turn, so the chat is a real answer channel, not a
        # dead end that still requires editing the Ziel field by hand.
        from cells.copilot.planning import pm
        text = (a.get("text") or "").strip()
        if not text:
            return "clarify_goal: kein Text übergeben"
        if not pm.get_goal():
            return "clarify_goal: kein Ziel gesetzt - nichts zum Klarstellen"
        pm.add_clarification(text, actor=actor)
        # Re-Plan im HINTERGRUND (owner decree 2026-09-05): pm.brief() ist ein
        # eigener Modell-Call (~2,5min gemessen 07:32->07:34:52) und lief hier
        # SYNCHRON - Henrys Actions laufen sequenziell, also blockierte er
        # jede spaetere Action im selben Block. Der Owner sah "Gebongt, startet
        # gleich" und dann minutenlang nichts, weil sein new_process hinter
        # einem Re-Plan wartete, der mit ihm nichts zu tun hat. bgthread (nicht
        # ein nackter Thread) traegt das Crash-Reporting: ein gestorbener
        # Re-Plan wird eskaliert statt zu verschwinden. Der frueher hier
        # angehaengte automatische Ziel-Abgleich (goal_check, nur Titel) ist
        # seit 2026-09-13 gestrichen (Owner: "Henry fragt dumme Fragen").
        from spine.ops import bgthread

        def _replan():
            try:
                pm.brief()
            except Exception as e:                           # noqa: BLE001
                print("clarify_goal re-plan failed:", str(e)[:200])
        bgthread.spawn("pm:replan", _replan)
        return "Notiert: „%s“ - Plan wird im Hintergrund neu gerechnet." % text[:150]
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
    if kind in ("edit_process", "cancel_process", "delete_process", "process_status"):
        # Added 2026-09-03 (owner report: the Prozesse screen let you add
        # steps and nothing else - no rename/re-schedule, no way to stop a
        # process, no visibility into what's happening). Same process-ref-
        # by-fragment resolution accept_steps already uses, so "der
        # Vertragsprozess" works the same way in every one of these.
        frag = (a.get("process") or "").lower()
        ps = [p for p in processes.list_processes()
              if frag in p["id"].lower() or frag in p["request"].lower()]
        if len(ps) != 1:
            return "%s failed: process ref ambiguous or not found" % kind
        pid = ps[0]["id"]
        if kind == "process_status":
            # read-only - anyone who can see /processes can ask about one.
            _, lines = processes.progress_summary(pid)
            return ("%s:\n" % pid) + "\n".join(lines) if lines else "%s hat keine Schritte." % pid
        from spine.auth import auth
        admin_roles = auth.chat_admin_roles()
        if role not in admin_roles:
            return _denied(kind, role, admin_roles, "policy.chat_admin_roles")
        if kind == "edit_process":
            patch = {k: a[k] for k in ("client", "due", "request") if k in a}
            if not patch:
                return "edit_process: nothing to change (give client/due/request)"
            try:
                processes.update_process(pid, patch, actor=actor)
            except ValueError as e:
                return "edit_process refused: %s" % e
            return "%s updated: %s" % (pid, json.dumps(patch)[:200])
        if kind == "cancel_process":
            try:
                processes.cancel_process(pid, actor=actor)
            except RuntimeError as e:
                return "cancel_process refused: %s" % e
            return "%s cancelled - remaining steps will not auto-advance; already-dispatched cards keep running" % pid
        # delete_process - removes the row entirely (owner: "cancel bleibt
        # nur stehen, ich will es weg"); cards a step already spawned are
        # untouched, same rule as cancel.
        try:
            processes.delete_process(pid, actor=actor)
        except RuntimeError as e:
            return "delete_process refused: %s" % e
        return "%s deleted - it will no longer appear in the Prozesse list; any card already created keeps running" % pid
    if kind in ("add_step", "update_step", "remove_step", "move_step"):
        # Owner decree 2026-09-03 ("Henry soll den Prozess aendern koennen"):
        # chat is a FULL alternative to the (still limited) Prozesse UI, not
        # just a process-level one - individual steps too. Same admin gate
        # as edit_process/cancel_process (these mutate structure, same tier
        # as accepting/removing a step in the UI's own StepEditor, which is
        # open - but the UI action requires a TAP the owner is looking at;
        # chat has no such implicit "I can see what I'm changing" context,
        # so it gets the stricter gate).
        frag = (a.get("process") or "").lower()
        ps = [p for p in processes.list_processes()
              if frag in p["id"].lower() or frag in p["request"].lower()]
        if len(ps) != 1:
            return "%s failed: process ref ambiguous or not found" % kind
        p = ps[0]
        from spine.auth import auth
        admin_roles = auth.chat_admin_roles()
        if role not in admin_roles:
            return _denied(kind, role, admin_roles, "policy.chat_admin_roles")
        if kind == "add_step":
            title = (a.get("title") or "").strip()
            if not title:
                return "add_step: title required"
            processes.add_step(p["id"], title, a.get("mode", "do"))
            return "step '%s' added to %s" % (title[:60], p["id"])
        step_frag = (a.get("step") or "").lower()
        idx = next((i for i, s in enumerate(p["steps"])
                   if step_frag in (s.get("title") or "").lower()), None)
        if idx is None:
            return "%s failed: step '%s' not found in %s" % (kind, a.get("step"), p["id"])
        if kind == "remove_step":
            try:
                processes.remove_step(p["id"], idx)
            except RuntimeError as e:
                return "remove_step refused: %s" % e
            return "step removed from %s" % p["id"]
        if kind == "move_step":
            direction = (a.get("direction") or "").strip().lower()
            if direction not in ("up", "down"):
                return "move_step: direction must be 'up' or 'down'"
            try:
                processes.move_step(p["id"], idx, direction, actor=actor)
            except RuntimeError as e:
                return "move_step refused: %s" % e
            return "step moved %s in %s" % (direction, p["id"])
        # update_step
        patch = {k: a[k] for k in ("title", "desc", "mode", "due", "days") if k in a}
        if not patch:
            return "update_step: nothing to change (give title/desc/mode/due/days)"
        processes.update_step(p["id"], idx, patch)
        return "step updated in %s: %s" % (p["id"], json.dumps(patch)[:200])
    if kind == "audit_query":
        # Card 5 (ops/docs/backlog/rbac-gxp): Henry can answer questions about
        # the append-only audit trail - "wer hat GxP aktiviert", "letzte
        # Ablehnungen diese Woche". Read-only, gated on the REAL chatting
        # user's role (never a standing capability Henry itself holds - see
        # spine/auth/permissions.py's own warning against exactly that).
        from spine.auth import permissions
        if not permissions.can({"role": role}, "audit.read"):
            allowed = sorted(r for r, caps in permissions.matrix().items() if "audit.read" in caps)
            return _denied("audit_query", role, allowed, "spine/auth/permissions.py's permission matrix")
        rows = events.query_audit(kind=a.get("kind"), track=a.get("track"), actor=a.get("actor"),
                                  since=a.get("since"), until=a.get("until"), q=a.get("q"))
        limit = max(1, min(int(a.get("limit") or 20), 200))
        tail = rows[-limit:]
        if not tail:
            return "audit: keine Eintraege fuer diese Filter."
        lines = ["%s  %-10s actor=%s%s" % (
            e.get("at_utc", "?"), e.get("kind", "?"), e.get("actor", "-"),
            ("  " + e.get("reason", "")) if e.get("reason") else "")
            for e in tail]
        more = "" if len(rows) <= limit else " (+%d weitere, aeltere)" % (len(rows) - limit)
        return "audit (%d Treffer%s):\n%s" % (len(rows), more, "\n".join(lines))
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
