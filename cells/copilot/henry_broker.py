# -*- coding: utf-8 -*-
"""Henry's judgement half of the escalation channel (owner decree 2026-08-21,
ops/docs/backlog/henry-exception-broker; cell placement corrected same day on owner
pushback: "respect the cell structure - communication between cells").

The split across the architecture:
  spine/registry/escalations.py - the CHANNEL. Append-only log + fold. Any
      cell may emit; nothing there judges. Same standing as events.jsonl.
  engineer cell                 - EMITS (aborted-by-restart, conflict-
      unresolved, deploy-red). Reports facts, never decides.
  THIS module (copilot cell)    - Henry CONSUMES. Full-context judgement via
      the same headless-claude seam the board chat uses, bounded verbs, the
      2-attempt RESOLVE cap, audit note per decision. Starts with the
      copilot cell, stops with it (copilotEnabled off = no broker).

Policy is DATA: settings.json `henry_policy` overrides DEFAULT_POLICY -
changing Henry's behaviour is editing prose, never shipping Python.
"""
import json
import os
import re
import subprocess
import threading
import time

from daemon.paths import DAEMON_ROOT as ROOT
from spine.registry import escalations
from spine.git.locks import _direct_lock_for

# The fixed cwd every hands-on Henry turn runs in (_ask's cwd - the repo
# root, one level up from DAEMON_ROOT). ONE path, so the lock below is the
# SAME object a direct-build card on this exact repo would also contend for
# (spine.git.locks._direct_lock_for is keyed by normalized path) - Henry and
# a direct card editing the live tree at the same moment now queue against
# each other instead of racing.
_HENRY_REPO_ROOT = os.path.dirname(ROOT)

_MAX_ATTEMPTS = 2
_INTERVAL_S = 90

# A MANDATE, not a rulebook (owner decree 2026-08-24: "Henry should only get
# instructions to plan and intervene"). Henry judges each escalation from the
# live snapshot with model judgement - per-incident prose bullets are the
# judgement-in-code anti-pattern this broker exists to end, so do NOT grow a
# new bullet per escalation kind here. Hard INVARIANTS (bounded verbs, the
# 2-attempt cap, rails via move_lane) live in code, where they belong.
DEFAULT_POLICY = (
    "Du bist Henry, Senior-Projektmanager des HelmDeck-Boards - die einzige "
    "Instanz mit vollem Systemkontext. Dein erster Job ist herauszufinden, "
    "was gerade WICHTIG ist - nicht jede Eskalation verdient dieselbe "
    "Aufmerksamkeit. Dann planst du und greifst ein: du bekommst die "
    "Eskalation plus Live-Schnappschuss und entscheidest selbst, kein "
    "Regelwerk.\n"
    "Du verwaltest drei Dinge:\n"
    "- AI-NUTZUNG: Turns, Quota, Kosten. Verschwende sie nicht - keine "
    "Blindversuche, keine unnoetigen Wiederholungen.\n"
    "- MENSCHEN UND ARBEIT: der Owner und die Karten-Worker. Fertige Arbeit "
    "landet (move review/done - die Rails pruefen selbst), haengende wird "
    "gesteuert. Wecke den Owner nur, wenn keine sichere Selbsthilfe "
    "existiert - dann mit EINER konkreten Frage.\n"
    "- MASCHINEN-RESSOURCEN: die Box (CPU/RAM, Builds, Emulator). Beobachten "
    "und benennen; warten vor toeten. Toete NIE fremde Prozesse und nie "
    "Arbeit, die lebt und Fortschritt macht.\n"
    "Du hast HAENDE: du darfst in diesem Turn selbst lesen/aendern/ausfuehren "
    "und meldest dann action \"did\". Delegiere nur echte Feature-Arbeit. "
    "Technischen Kontext (Logs, Diff, Dateien) holst du dir selbst, bevor du "
    "fragst; bei echter Unklarheit ueber Budget/Timeline/Scope fragst du den "
    "Owner, statt auf Verdacht zu arbeiten."
)


def _dispatcher_privileged(t):
    """May Henry get live-tree HANDS for the card THIS escalation is about?
    Derived fresh, at judgement time, from who actually dispatched the card
    (t['dispatched_by'] - "WHO ASKED", per dispatch.py - not `client`, the
    billing label an owner can set on their own card; same distinction
    spawnenv._card_env's HELMDECK_TOOL_SCOPE derivation already draws)
    against the CURRENT user registry - never assumed, never cached, same
    shape as gxp.is_human().

    A card-less escalation (box load, a deploy hook - nothing a specific
    external card produced) or one dispatched by an agent name (pm, henry,
    chain - auth.get_user finds no account) has no client to be restricted
    FROM; hands stay on, unchanged from today. Only an escalation on a card
    a real `client`-role account filed loses hands.

    Owner decree 2026-08-25 (chat): "das soll ok sein, solange user is owner
    oder hat genuegend rechte" - this is that constraint, enforced rather
    than assumed true."""
    if not t:
        return True
    dispatched_by = t.get("dispatched_by")
    if not dispatched_by:
        return True
    from spine.auth import auth
    u = auth.get_user(dispatched_by)
    if not u:
        return True
    return u.get("role") in auth.chat_admin_roles()


def _ask(prompt, model="", perm=None):
    """Headless one-shot judgement call - same spawn shape as the board
    copilot/PM (drivers._cmd_line, never a bare .cmd with quoted args).

    Runs in a WORKING permission mode, not plan (owner decree 2026-08-21:
    "Henry should start in normal mode... do stuff directly"): Henry may fix
    the exception himself in this turn - hands like a direct/machine card, on
    the live tree, cwd repo root. The bounded-verb JSON stays as the CLOSING
    report, not the only channel. Override via settings `henry_permission_mode`.

    `perm`, when given, overrides that default for THIS call only - used by
    _decide to drop to "plan" (no edits) when _dispatcher_privileged(t) says
    the escalating card's owner does not qualify for Henry's hands."""
    from cells.copilot import copilot
    from spine.agent import drivers
    argv = [copilot.CLAUDE, "-p", "--output-format", "json",
            "--permission-mode", perm or copilot.henry_pmode()]
    if model:
        argv += ["--model", model]
    p = subprocess.Popen(drivers._cmd_line(argv), cwd=_HENRY_REPO_ROOT,
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace")
    try:
        # 300s judged fine; a turn that ACTS (build retry, file fix) needs room.
        stdout, stderr = p.communicate(input=prompt, timeout=900)
    except subprocess.TimeoutExpired:
        p.kill()          # a timed-out judgement must not linger as a zombie
        p.communicate()
        raise
    if not (stdout or "").strip():
        raise RuntimeError("henry: no model output: " + (stderr or "").strip()[:200])
    txt = json.loads(stdout).get("result", "")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("henry: no JSON in reply: " + txt.strip()[:150])
    return json.loads(m.group(0))


def _baseline_commit():
    """Snapshot the repo BEFORE Henry's hands touch it, so a wrong 'did' has
    a clean rollback point (debt henry-direct-hands: "no snapshot to roll
    back to unless the agent commits first" - a direct-build card has the
    same gap, unfixed; this closes it for Henry specifically). No-ops when
    the tree is already clean - never an empty commit, never masks whose
    change something was by committing on the owner's behalf when there is
    nothing new to snapshot."""
    from spine.git.gitutil import _git, _git_try, AGENT_IDENT
    try:
        dirty = _git(_HENRY_REPO_ROOT, "status", "--porcelain")
    except Exception:
        return   # not a git checkout or git unavailable - nothing to baseline
    if not dirty:
        return
    _git_try(_HENRY_REPO_ROOT, *AGENT_IDENT, "add", "-A")
    _git_try(_HENRY_REPO_ROOT, *AGENT_IDENT, "commit", "-m",
            "Henry baseline - snapshot before hands-on judgement turn")


def _hands_on_ask(prompt, timeout=60):
    """_ask(), but for the PRIVILEGED (real hands) path only: serialize
    against any other turn editing this same live tree (the direct-build
    lock, spine.git.locks._direct_lock_for - same primitive, same bounded-
    wait semantics as turnrunner.py's DIRECT card handling, so Henry and a
    direct card on this exact repo now queue instead of racing), and commit
    a baseline first. Bounded wait, not indefinite: a stuck lock must not
    silently swallow every future escalation attempt - it bounces this
    round, same as a direct card that gives up and retries later. `timeout`
    is a param (not hardcoded) purely so a test can prove the busy-lock path
    without a real 60s wait - _decide never overrides it."""
    lock = _direct_lock_for(_HENRY_REPO_ROOT)
    if not lock.acquire(timeout=timeout):
        raise RuntimeError(
            "henry: repo tree busy (a direct/machine card is editing it) - "
            "waited %ss, giving up this round" % timeout)
    try:
        _baseline_commit()
        return _ask(prompt, perm=None)
    finally:
        lock.release()


def _snapshot():
    """One screenful of system truth - derived live at read time, never a
    stored flag (the no-monkey-patch law)."""
    lines = []
    try:
        from spine.storage.trackstore import _load
        from spine.agent import drivers
        for t in _load():
            if t.get("archived") or t.get("lane") == "done":
                continue
            lines.append("card %s | %s/%s | ft=%s direct=%s turn_active=%s | %s" % (
                t["id"], t.get("lane"), t.get("status"), bool(t.get("fast_track")),
                bool(t.get("direct")), drivers.turn_active(t["id"]),
                (t.get("task") or "")[:60]))
    except Exception as e:
        lines.append("(board unreadable: %s)" % e)
    lines.append(_ship_lock_line())
    lines.append(_box_load_line())
    lines.append(_heavy_procs_line())
    return "\n".join(lines[:40])


def _ship_lock_line():
    pid = _ship_lock_pid()
    if pid is None:
        return "ship.lock: frei"
    return "ship.lock: pid %s (%s)" % (pid, "LIVE" if _pid_alive(pid) else "dead/stale")


def _ship_lock_pid():
    lock = os.path.join(os.path.dirname(ROOT), ".loop", "ship.lock", "pid")
    try:
        lines = open(lock).read().splitlines()
    except OSError:
        return None
    # Line 2 is the real Windows PID; line 1 is bash's $$, an MSYS-space pid
    # os.kill() cannot see (measured 2026-08-23: a live 40min gradle build
    # read as "dead" because only the MSYS pid was checked). Fall back to
    # line 1 for a lock written before ship.sh started recording line 2.
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        return None
    return lines[1] if len(lines) > 1 else lines[0]


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _box_load_line():
    """MEASURED box load - the SAME seam the load admission decides by
    (spine.ops.resources, ctypes GetSystemTimes) plus the named
    heavy-op holders its registry tracks. Paseo's collectDaemonDiagnostics
    puts loadavg/freemem in the same snapshot the reader judges from;
    Henry is that reader, so he gets the same numbers the code admits by -
    one truth, not a second reconstruction."""
    try:
        from spine.ops import resources
        from spine.git.locks import list_heavy_holders
        s = resources.sample(0.2)
        cpu = ("%.0f%%" % s["cpu_pct"]) if s.get("cpu_pct") is not None else "?"
        ram = ("%.1f GB frei" % (s["free_ram_mb"] / 1024.0)) if s.get("free_ram_mb") else "?"
        now = time.time()
        holders = ", ".join("%s (%s, seit %ds)" % (h["kind"], h["card"], now - h["since"])
                            for h in list_heavy_holders())
        return "box-last: CPU %s, RAM %s | schwere Ops: %s" % (cpu, ram, holders or "keine")
    except Exception as e:
        return "box-last: (nicht lesbar: %s)" % str(e)[:120]


def _heavy_procs_line():
    """NAMES the load the holder registry cannot see (an external/manual
    build, rustdesk): count the classic build hogs via tasklist. Coarse on
    purpose - _box_load_line has the percentages; this line answers WHO."""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True,
                             text=True, timeout=15).stdout.lower()
        counts = {n: out.count('"%s"' % n) for n in
                  ("java.exe", "node.exe", "qemu-system-x86_64.exe", "clang++.exe")}
        busy = ", ".join("%s x%d" % (k, v) for k, v in counts.items() if v)
        return "build-prozesse: " + (busy or "keine")
    except Exception:
        return "build-prozesse: (nicht lesbar)"


def check_stale_ship_lock():
    """Boot check: a ship.lock whose pid is DEAD means a deploy died with the
    previous daemon (exactly the 04:19 incident - the APK build vanished and
    nobody knew). Report it; whether to re-run is Henry's call."""
    pid = _ship_lock_pid()
    if pid is not None and not _pid_alive(pid):
        escalations.emit("ship-aborted", card=None,
                         detail="ship.lock pid %s ist tot - ein Deploy starb mit dem "
                                "vorigen Daemon; Tree-Stand ggf. ungeshippt." % pid)


def _card_log_tail(card, n=35):
    """The card's own recent history (gate/merge/deploy notes, steers, hook
    output) - read live from its actionlog. Henry's first conflict decision
    (2026-08-21 05:15) had to answer 'kein Kontext (Diff/Historie) verfuegbar'
    because the prompt carried only the board snapshot: full-context judgement
    was judging blind on the one card it was about."""
    if not card:
        return ""
    try:
        from spine.storage.trackstore import _load, _find
        t = _find(_load(), card)
        if not t:
            return ""
        path = os.path.join(t["run_dir"], "actions.jsonl")
        with open(path, encoding="utf-8") as f:
            recs = [json.loads(x) for x in f.read().splitlines()[-n:] if x.strip()]
        return "\n".join("%s %s: %s" % (r.get("ts", "?"), r.get("kind", "?"),
                                        str(r.get("detail", ""))[:220]) for r in recs)
    except Exception as e:
        return "(actionlog unreadable: %s)" % e


def _audit_context(t):
    """Recent audit-trail events for THIS card, folded into Henry's judgement
    prompt (card 5's deferred 'Consumer 2' - the chat's audit_query action,
    cells/copilot/copilot_actions.py, got Henry's interactive half; this is
    the autonomous-escalation half).

    Gated the same question as the chat action (permissions.can(...,
    'audit.read')), but keyed off the card's OWN dispatcher rather than a
    session role - Henry has none of its own. An escalation on a card filed
    by an account without audit.read must not hand Henry (and therefore the
    owner-notify text it can produce) more visibility than that account's
    own would have had."""
    if not t:
        return ""
    try:
        from spine.auth import auth, permissions
        from spine.storage import events
        disp = auth.get_user(t.get("dispatched_by") or "")
        if not disp or not permissions.can(disp, "audit.read"):
            return ""
        rows = events.query_audit(track=t.get("id"))[-8:]
        if not rows:
            return ""
        lines = ["%s  %s  actor=%s%s" % (
            e.get("at_utc", "?"), e.get("kind", "?"), e.get("actor", "-"),
            ("  " + e["reason"]) if e.get("reason") else "")
            for e in rows]
        return "\n== AUDIT (juengste Ereignisse dieser Karte) ==\n" + "\n".join(lines)
    except Exception:
        return ""  # never let a context-enrichment failure block the judgement turn


def _decide(esc):
    """One judgement round. Returns True if the escalation was closed."""
    from spine.storage import events
    policy = (events.settings().get("henry_policy") or "").strip() or DEFAULT_POLICY
    escalations.record_attempt(esc["id"])
    card_log = _card_log_tail(esc.get("card"))
    t = _find_track(esc.get("card"))
    privileged = _dispatcher_privileged(t)
    prompt = (
        policy
        + "\n\n== ESKALATION ==\nkind: %s\ncard: %s\ndetail:\n%s\n" % (
            esc["kind"], esc.get("card") or "-", esc.get("detail") or "")
        + ("\n== KARTE (actionlog, juengste zuerst unten) ==\n" + card_log + "\n" if card_log else "")
        + _audit_context(t)
        + "\n== SYSTEM ==\n" + _snapshot()
        + "\n\nDu darfst vor der Antwort selbst handeln (Dateien, Kommandos). "
          "Fertige Arbeit SCHIEBST du durch: action \"move\" mit lane review "
          "(prueft das Gate) bzw. done (nimmt ab, merged, deployed) - nicht "
          "parken und auf den Owner warten. "
          "Antworte am ENDE NUR mit diesem JSON:\n"
          '{"action": "did|move|rerun_deploy|steer|notify_owner|ignore",\n'
          ' "card": "karten-id oder leer",\n'
          ' "lane": "bei move: review|done",\n'
          ' "text": "bei did: was du getan hast; sonst steer-anweisung bzw. owner-nachricht",\n'
          ' "why": "ein satz begruendung"}')
    if not privileged:
        # This card was filed by a client-role account, not owner/operator -
        # Henry gets NO hands for it (spine.auth.devices' same distinction:
        # dispatched_by, resolved fresh, not the client billing label).
        # perm="plan" makes any edit attempt fail at the tool layer, and the
        # prompt says so up front so the turn doesn't waste itself trying.
        prompt += (
            "\n\nHINWEIS: Diese Karte wurde von einem client-Account "
            "eingereicht - du hast in diesem Turn KEINE Haende (nur lesen). "
            "action \"did\" ist nicht verfuegbar; nutze steer/notify_owner/"
            "ignore.")
    try:
        d = _ask(prompt, perm="plan") if not privileged else _hands_on_ask(prompt)
    except Exception as e:
        escalations.record_note(esc["id"], "ask failed: %s" % str(e)[:200])
        return False
    action = (d.get("action") or "").strip()
    card = (d.get("card") or esc.get("card") or "").strip()
    lane = (d.get("lane") or "").strip()
    text = (d.get("text") or "").strip()
    why = (d.get("why") or "").strip()
    if action == "did" and not privileged:
        # Defense in depth: even if the model tried anyway, this card's
        # escalation does not get closed via "did" - stays open for a
        # privileged human/owner to see, same shape as the GxP refusal
        # below (_execute's did/move gate).
        escalations.record_note(esc["id"],
            "Henry versuchte 'did' auf einer client-Karte ohne Haende - "
            "abgelehnt, bleibt offen")
        return False
    if not _execute(action, card, lane, text, esc):
        return False   # malformed verb - stays open for the next attempt
    escalations.record_decision(esc["id"], action, card=card, why=why)
    _audit(card, "HENRY entschieden (%s): %s - %s" % (
        esc["kind"], action,
        (text[:200] + (" | " + why if why else "")) if action == "did" else (why or text[:120])))
    # REPORT BACK on every closing action (owner decree 2026-08-21: "if the work
    # is done he doesn't report back") - notify_owner/give-up already push; the
    # quiet successes (did/move/rerun/steer) were invisible until now.
    if action in ("did", "move", "rerun_deploy", "steer"):
        _notify_owner("Henry (%s): %s%s - %s" % (
            esc["kind"], action, (" -> " + lane) if action == "move" else "",
            (text or why)[:180]), None if action == "did" else _find_track(card))
    return True


def _find_track(card):
    try:
        from spine.storage.trackstore import _load, _find
        return _find(_load(), card) if card else None
    except Exception:
        return None


def _execute(action, card, lane, text, esc):
    from spine.auth import gxp
    from spine.storage.trackstore import _load, _find
    t = _find(_load(), card) if card else None
    if action == "ignore":
        return True
    # GxP: Henry's two HANDS verbs are off for a card in the regulated scope.
    # `move` would also be stopped by the lane machine's chokepoint (he is not
    # an account), but it is refused here too so the escalation stays open and
    # visibly waiting for a person, instead of being closed against a landing
    # that never happened. `did` has no chokepoint at all - it is Henry editing
    # the live tree - so this is the only place it can be stopped.
    #
    # Out of scope he keeps both hands: the mode narrows what is regulated, it
    # does not turn the exception broker off.
    if action in ("did", "move") and gxp.in_scope(t) and gxp.disabled("henry_" + action):
        from spine.storage import events
        events.emit("gxp", card or "-", outcome="henry_refused", action=action,
                    reason="GxP mode: this needs a person")
        return False
    if action == "did":
        # Henry already acted with his own hands inside the judgement turn
        # (owner decree 2026-08-21) - the work is done, this verb just closes
        # the escalation; `text` (what he did) lands in the audit note.
        return True
    if action == "move" and t and lane in ("review", "done"):
        # Push finished work THROUGH the rails, not around them: move_lane runs
        # the full gate on review and the accept/merge/deploy machinery on done
        # (owner decree 2026-08-21: "he doesn't push the card through the
        # gates"). backlog/working moves stay out of the verb - regressing a
        # card is steering, not landing.
        #
        # SYNCHRONOUS + VERIFIED, on purpose (was fire-and-forget on a bare
        # thread until 2026-08-28): the old code returned True the instant the
        # thread STARTED, so `_decide` closed the escalation and told the owner
        # "done" before move_lane had done anything - a bounce, a conflict, or
        # (measured live) a crashed thread all looked identical to success.
        # move_lane's own terminal write is the ground truth: it sets
        # tt["lane"] = lane ONLY on the pipeline's successful tail (_land) -
        # every bounce/conflict/blocked path returns early with the lane
        # untouched (see cells/engineer/lanemachine.py's _move_lane). Reading
        # that back after the call is therefore a real verification, not an
        # optimistic assumption - same evidence-over-flag discipline as
        # drivers.resume_detached. The broker loop tolerates the wait (moves
        # are rare; this just delays the SAME tick's other escalations by one
        # gate's worth of seconds, same trade sessions.py already made moving
        # gate off the HTTP request thread).
        from cells.engineer import sessions
        try:
            r = sessions.move_lane(t["id"], lane, actor="henry")
        except Exception as e:
            escalations.record_note(esc["id"], "move fehlgeschlagen: %s" % str(e)[:200])
            return False
        if (r or {}).get("lane") != lane:
            reason = (r or {}).get("merge_report") or (r or {}).get("gate_report") or "unbekannt"
            escalations.record_note(esc["id"],
                "move nach %s kam nicht an (blieb auf %s) - Grund: %s"
                % (lane, (r or {}).get("lane"), str(reason)[:300]))
            return False           # stays open - the next attempt sees the real state fresh
        return True
    if action == "steer" and t and text:
        from cells.engineer import sessions
        from spine.ops import bgthread
        bgthread.spawn("track:steer:" + t["id"], lambda: sessions.steer(
            t["id"], text, actor="henry", source="henry-escalation"))
        return True
    if action == "rerun_deploy":
        from cells.engineer.lanemachine import _repo_hook
        from spine.storage import events
        if t is None:
            # card-less ship abort: rebuild the hook target from the default
            # repo - the hook only needs repo/run_dir-shaped fields.
            repo = events.settings().get("default_repo") or ""
            if not repo:
                return False
            t = {"id": "-", "repo": repo, "run_dir": os.path.join(ROOT, "recordings", "_henry"),
                 "worktree": repo}
            os.makedirs(t["run_dir"], exist_ok=True)
        # Fail LOUD, not quiet (found live 2026-08-27): _repo_hook silently
        # returns None when settings.repo_hooks has no EXACT-string-matching
        # "deploy" entry for this repo path - a stale ship.lock then
        # re-escalates on every daemon restart forever, because rerun_deploy
        # still returned True (the escalation closes as "decided") while
        # actually doing nothing at all, and the lock's dead pid never
        # changes. Check the hook exists BEFORE spawning the fire-and-forget
        # thread, so a misconfiguration surfaces as a normal give-up
        # (_give_up already notifies the owner after _MAX_ATTEMPTS) instead
        # of a silent no-op loop.
        cmd = ((events.settings().get("repo_hooks") or {}).get(t["repo"]) or {}).get("deploy", "").strip()
        if not cmd:
            escalations.record_note(esc["id"],
                "rerun_deploy: kein settings.repo_hooks['%s']['deploy'] konfiguriert "
                "(oder der Repo-Pfad passt nicht exakt) - kein Deploy ausgeloest." % t["repo"])
            return False
        from spine.ops import bgthread
        bgthread.spawn("henry:rerun_deploy:" + t["id"], lambda: _repo_hook(dict(t), "deploy"))
        return True
    if action == "notify_owner":
        _notify_owner("Henry (%s): %s" % (esc["kind"], text or (esc.get("detail") or "")[:200]), t)
        return True
    return False


def _give_up(esc):
    escalations.record_decision(esc["id"], "escalated",
                                why="no safe automatic decision after %d attempts" % _MAX_ATTEMPTS)
    _notify_owner("Henry gibt ab (%s): %s" % (esc["kind"], (esc.get("detail") or "")[:200]), None)


def _audit(card, note):
    if not card:
        return
    try:
        from spine.storage.trackstore import _load, _find
        from spine.ops.actionlog import ActionLog
        t = _find(_load(), card)
        if t:
            ActionLog(t["run_dir"]).log("note", note)
    except Exception:
        pass


def _notify_owner(text, t):
    try:
        from spine.comms import notify
        from spine.registry import i18n as _i18n
        notify.push_fcm(_i18n.t("push.henry"), text[:230])
    except Exception:
        pass
    # ALSO into the board chat (owner observation 2026-08-28, "warum nichts im
    # Chat"): the push is suppressed exactly when the owner is LOOKING at the
    # app (notify's owner-presence dedup) and held in quiet hours, and the
    # audit note lives on the card - so the one surface the owner actually
    # reads while watching Henry work, the Henry chat, showed none of the
    # broker's decisions. copilot.say is the same line the lane pipeline's
    # _say_card uses; best-effort like the push.
    try:
        from cells.copilot import copilot
        copilot.say(text, cls="pm", card=(t or {}).get("id") or None)
    except Exception:
        pass
    if t:
        _audit(t["id"], text)


def _loop():
    while True:
        try:
            for esc in escalations.list_open():
                if esc["attempts"] >= _MAX_ATTEMPTS:
                    _give_up(esc)
                    continue
                _decide(esc)
        except Exception as e:
            # never die, but never be SILENT either - an invisible broken broker
            # is exactly the class of failure Henry exists to end.
            print("henry: loop error:", str(e)[:200])
        time.sleep(_INTERVAL_S)


_started = False


def start_broker():
    """Copilot cell lifecycle hook (cells.py start=). Idempotent."""
    global _started
    if _started:
        return
    _started = True
    check_stale_ship_lock()
    threading.Thread(target=_loop, daemon=True).start()
