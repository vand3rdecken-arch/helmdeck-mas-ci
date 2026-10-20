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

Policy is DATA: the mandate below is the DEFAULT, and rule
`report.judgement_policy` overrides it per workspace or per project - changing
Henry's behaviour is editing prose, never shipping Python. It resolves through
spine/registry/behavior.py like every other rule, so it carries a scope, a
validator, a size bound and a row on the harness screen; the pre-rules global
key settings.json `henry_policy` is migrated onto that path once by
spine/storage/legacypolicy.py and stays readable one release as the floor.
"""
import json
import os
import subprocess
import threading
import time
import traceback

from daemon.paths import DAEMON_ROOT as ROOT, DATA_ROOT as _DATA_ROOT
from spine.registry import escalations
from spine.git.locks import _direct_lock_for

# The fixed cwd every hands-on Henry turn runs in (_ask's cwd - the repo
# root, one level up from DAEMON_ROOT). ONE path, so the lock below is the
# SAME object a direct-build card on this exact repo would also contend for
# (spine.git.locks._direct_lock_for is keyed by normalized path) - Henry and
# a direct card editing the live tree at the same moment now queue against
# each other instead of racing.
_HENRY_REPO_ROOT = os.path.dirname(ROOT)

# The FLOORS, not the values (harness-config-ui phase 2). Both are the declared
# defaults of rules report.followup_attempts / report.followup_interval in
# spine/registry/behavior.py, so an installation that cannot read the rule table
# behaves exactly as it does today. The interval is also QUOTED in Henry's own
# brief ("the broker loop picks up within ~90s") - one number in two places that
# could drift, which is why the brief now renders it from this same rule.
_MAX_ATTEMPTS = 2
_INTERVAL_S = 90


def _rule_int(key, floor):
    try:
        from spine.registry import behavior
        v = behavior.value(key, "all")
        return int(v) if v else floor
    except Exception:                                        # noqa: BLE001
        return floor


def _max_attempts():
    return _rule_int("report.followup_attempts", _MAX_ATTEMPTS)


def _interval_s():
    return _rule_int("report.followup_interval", _INTERVAL_S)

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
    "landet (move review/done - die Rails pruefen selbst); dein move traegt "
    "die Antwort des Workers automatisch in den Board-Chat des Owners - kein "
    "zusaetzliches notify_owner dafuer noetig. Haengende wird gesteuert. "
    "Wecke den Owner nur, wenn keine sichere Selbsthilfe existiert - dann mit "
    "EINER konkreten Frage.\n"
    "- MASCHINEN-RESSOURCEN: die Box (CPU/RAM, Builds, Emulator) UND was der "
    "Harness selbst geoeffnet hat - Browser-Tabs im eigenen HelmDeck-Chrome, "
    "gestartete Dev-Server, tote Worktree-Ordner, Scratch-Verzeichnisse, "
    "Locks mit toter PID. Bei einer 'idle-check'-Eskalation (Owner laengere "
    "Zeit weg, Board ruhig) nennt das Lagebild nur drei Fakten: wie lange der "
    "Owner weg ist, welche Prozesse dem Daemon gehoeren, CPU/RAM; alles andere "
    "(Tabs, Ports, Worktrees, Locks) schaust du selbst nach. Es ist eine reine "
    "Beobachtung, keine Empfehlung - DU entscheidest, was weg kann; kein "
    "Regelwerk dafuer, nur dein Urteil. Nie Fenster oder Prozesse des Owners "
    "(der windows-mcp-Pfad faehrt SEIN Chrome, das ist nie im Lagebild und "
    "bleibt unberuehrt), nie etwas, das noch lebt oder zu einer Karte gehoert, "
    "die weiterlaeuft. Beobachten und benennen vor Handeln; warten vor "
    "toeten. Jede Aufraeumaktion nennst du im \"text\"/\"why\" konkret (was, "
    "warum) - das landet als Begruendung im Eskalations- und Audit-Log. "
    "Toete NIE fremde Prozesse.\n"
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


def _extract_json(txt):
    """Henry's prompt demands the closing JSON come LAST ("Antworte am ENDE
    NUR mit diesem JSON"), but the old DOTALL brace-to-brace regex matched
    greedily from the FIRST '{' anywhere in the reply to the LAST '}' - a
    "text" field that happened to quote or describe anything brace-shaped
    earlier in the reply turned that match into "everything between that
    stray brace and the real close", which is not valid JSON (measured
    2026-09-10: a ship-decision judgement failed with 'ask failed: Expecting
    property name enclosed in double quotes'). Try each '{' from the END of
    the reply backwards and let json.JSONDecoder stop at ITS OWN matching
    '}' - the first candidate that parses to a dict is the real, trailing
    answer; earlier braces in prose essentially never parse as valid JSON on
    their own."""
    dec = json.JSONDecoder()
    for i in reversed([i for i, c in enumerate(txt) if c == "{"]):
        try:
            obj, _ = dec.raw_decode(txt, i)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


# STAGED JUDGEMENT (owner 2026-10-07: "nur entscheiden was man macht, und bei
# tatsaechlich nutzen erst lesen"). Round 1 runs with NO tools: the prompt
# already carries the escalation, the card log, the audit lines and the
# system snapshot, and the daemon is the hands - Henry answers `need` with a
# list of what he wants to see, the daemon runs those readers itself and asks
# once more (still no tools). Only `hands` (he must edit/run something) buys a
# round WITH the three tools he actually uses. Measured per step: no tools
# ~12k + prompt, Bash/Read/Edit ~18k, the default block ~30k.
STAGE1_TOOLS = ""
# NOT "plan": plan mode tells the model to finish with ExitPlanMode, a tool a
# tool-less round does not have - it then TYPED the call, invented the result
# ("<system>Tool ran without output</system>") and looped to the 128k output
# cap: 3 of 12 staged judgements 2026-10-07/08, 14 min + $3.5 each, 0 of 347
# before. With no tools there is nothing for plan mode to protect.
STAGE1_PERM = "default"
STAGE1_MAX_OUT = "8000"           # a verdict is one JSON; a runaway stops here
STAGE1_TIMEOUT = 180              # s - was the 900s hands budget
HANDS_TOOLS = "Bash,Read,Edit"
NEED_ROUNDS = 3                   # reloads per judgement (owner: "weitersuchen duerfen")
NEED_MAX = 5                      # readers per reload round
NEED_CAP = 6000                   # chars kept per reader output
_ROUND = {"tools": None}          # the tools of the round _ask is serving (one owner: _decide)

_NEED_ARGV = {
    "card": ("board_state.py", ["--card"]),
    "board": ("board_state.py", []),
    "inbox": ("henry_inbox.py", []),
    "memory": ("henry_memory_get.py", ["find"]),
    "ship_facts": ("ship_facts.py", []),
}


def _run_reader(script, args, timeout=60):
    """One ops/tools reader, run by the daemon's own interpreter from the repo
    root (headless PATH has no `py`; the scripts import spine themselves)."""
    import subprocess
    import sys as _sys
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([_sys.executable, os.path.join(_HENRY_REPO_ROOT, "ops", "tools", script)] + args,
                       cwd=_HENRY_REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    out = (p.stdout or "") + (("\n[stderr] " + p.stderr.strip()[:300]) if p.returncode else "")
    return out.strip()


def _fetch_need(items, card):
    """Resolve Henry's `need` list to text. Unknown names are reported, not
    guessed; everything is capped so one chatty reader cannot swallow the
    prompt. `memory:<begriff>` carries its own argument; `card` defaults to
    the escalating card."""
    blocks = []
    for raw in list(items or [])[:NEED_MAX]:
        raw = str(raw).strip()
        if ":" in raw:                   # card:<id>, memory:<begriff>
            name, _, arg = raw.partition(":")
        else:                            # "card <id>" - measured 2026-10-07, the model's first answer
            name, _, arg = raw.partition(" ")
        name = name.strip().lower()
        spec = _NEED_ARGV.get(name)
        if not spec:
            blocks.append("[%s] unbekannt - verfuegbar: %s" % (raw, ", ".join(_NEED_ARGV)))
            continue
        script, args = spec
        args = list(args)
        if name == "card":
            args.append((arg or card or "").strip())
        elif name == "memory":
            if not arg.strip():
                blocks.append("[memory] braucht einen Begriff: memory:<begriff>")
                continue
            args.append(arg.strip())
        try:
            out = _run_reader(script, args)
        except Exception as e:                               # noqa: BLE001
            out = "[fehlgeschlagen] " + str(e)[:200]
        if len(out) > NEED_CAP:
            out = out[:NEED_CAP] + "\n... (gekuerzt)"
        blocks.append("[%s]\n%s" % (raw, out or "(leer)"))
    return "\n\n".join(blocks)


_STAGE1_TAIL = (
    "\n\nIn dieser Runde hast du KEINE Werkzeuge - alles, was du weisst, steht oben. "
    "Fehlt dir etwas, antworte action \"need\" mit \"data\": eine Liste aus "
    "card, board, inbox, memory:<begriff>, ship_facts (hoechstens %d pro Runde, bis zu %d Runden) - "
    "der Daemon holt es und fragt dich erneut. "
    "Musst du selbst Hand anlegen (Dateien aendern, Kommandos ausfuehren), antworte "
    "action \"hands\" mit \"text\" = was du vorhast; du bekommst dann eine Runde mit "
    "Werkzeugen. Fertige Arbeit SCHIEBST du durch: action \"move\" mit lane review "
    "(prueft das Gate) bzw. done (nimmt ab, merged, deployed) - nicht parken und auf "
    "den Owner warten. action \"restart\" = Daemon-Neustart ueber den Harness. "
    "Antworte am ENDE NUR mit diesem JSON:\n"
    '{"action": "need|hands|move|ship|restart|rerun_deploy|steer|answer|notify_owner|direct_task|machine_task|accept_steps|cancel_process|finish_process|set_next|ignore",\n'
    ' "data": "bei need: die Liste",\n'
    ' "card": "karten-id oder leer",\n'
    ' "lane": "bei move: review|done (done weckt den Prozess der Karte fuer den naechsten Schritt; review ist fuer Ergebnisse, die nur der Owner beurteilen kann)",\n'
    ' "kind": "bei ship: none|ota|native",\n'
    ' "text": "bei hands: dein Vorhaben; bei answer (Worker-Frage, die der Owner bereits sieht): die Antwort, genau ein angebotenes Label oder ein Satz - nur wenn die Frage trivial ist und Code oder fruehere Owner-Entscheidungen sie klaeren, sonst ignore und der Owner entscheidet; bei direct_task/machine_task: der Auftrag der neuen Karte; bei move: DEINE Antwort an den Owner, kurz und alltagssprachlich, auf dem Handy lesbar: was ist erledigt, und bei lane review was er pruefen oder entscheiden soll (review ist seine Abnahme); Pfade, Hashes und Testzahlen helfen ihm dort nicht; den Worker-Bericht nicht kopieren; sonst steer-anweisung bzw. owner-nachricht",\n'
    ' "ask": "bei move nach review, wenn der Owner etwas entscheiden soll: 2-4 kurze Antwort-Buttons als Liste, z.B. [Abnehmen, Nacharbeit, Auf echtem Jira testen]; sonst weglassen",\n'
    ' "at": "bei set_next: YYYY-MM-DD oder YYYY-MM-DD HH:MM",\n'
    ' "goal": "bei direct_task/machine_task: true wenn die Karte dem Ziel dient (GOAL-Zeile)",\n'
    ' "why": "ein satz begruendung"}') % (NEED_MAX, NEED_ROUNDS)

_HANDS_TAIL = (
    "\n\nJETZT hast du Werkzeuge (Bash, Read, Edit) und darfst handeln. "
    "Dein Vorhaben aus der Vorrunde: %s\n"
    "Fuehre es aus und melde action \"did\" (text: was du getan hast). "
    "action \"restart\" = Daemon-Neustart ueber den Harness (verweigert von selbst, solange "
    "eine Karte mitten im Turn ist - NIE taskkill/schtasks selbst tippen). "
    "Antworte am ENDE NUR mit diesem JSON:\n"
    '{"action": "did|move|ship|restart|rerun_deploy|steer|notify_owner|direct_task|machine_task|ignore",\n'
    ' "card": "karten-id oder leer",\n'
    ' "lane": "bei move: review|done (done weckt den Prozess der Karte fuer den naechsten Schritt; review ist fuer Ergebnisse, die nur der Owner beurteilen kann)",\n'
    ' "kind": "bei ship: none|ota|native",\n'
    ' "text": "bei did: was du getan hast; bei move: deine Antwort an den Owner, kurz und alltagssprachlich (erledigt / bei review was er pruefen oder entscheiden soll), den Worker-Bericht nicht kopieren; sonst steer-anweisung bzw. owner-nachricht",\n'
    ' "why": "ein satz begruendung"}')


def _ask(prompt, model="", perm=None):
    """Headless judgement call, ON HENRY'S OWN BOARD SESSION (owner decree
    2026-09-14: "zusammenfuehren" - see copilot.judge's docstring for why the
    old session-less one-shot was two brains that read the same chat but
    never shared context, and how resuming the same session from a
    different process is safe).

    Runs in a WORKING permission mode, not plan (owner decree 2026-08-21:
    "Henry should start in normal mode... do stuff directly"): Henry may fix
    the exception himself in this turn - hands like a direct/machine card, on
    the live tree, cwd repo root. The bounded-verb JSON stays as the CLOSING
    report, not the only channel. Override via settings `henry_permission_mode`.

    `perm`, when given, overrides that default for THIS call only - used by
    _decide to drop to "plan" (no edits) when _dispatcher_privileged(t) says
    the escalating card's owner does not qualify for Henry's hands."""
    from cells.copilot.chat import copilot
    tools = _ROUND.get("tools")
    toolless = tools == STAGE1_TOOLS
    raw = copilot.judge(prompt, cwd=_HENRY_REPO_ROOT, perm=perm, model=model, tools=tools,
                        timeout=STAGE1_TIMEOUT if toolless else 900,
                        max_output=STAGE1_MAX_OUT if toolless else None)
    txt = raw.get("result", "")
    d = _extract_json(txt)
    if d is None:
        raise RuntimeError("henry: no JSON in reply: " + txt.strip()[:150])
    # What the CLI refused this turn, VERBATIM - so a blocked hand is a fact in
    # the escalation record (and the chat's follow-up line), not a story Henry
    # tells about it. Measured 2026-09-11/12: three identical schtasks denials,
    # three different invented reasons.
    d["_denials"] = raw.get("permission_denials") or []
    return d


def _baseline_commit():
    """Snapshot the repo BEFORE Henry's hands touch it, so a wrong 'did' has
    a clean rollback point (debt henry-direct-hands: "no snapshot to roll
    back to unless the agent commits first" - a direct-build card has the
    same gap, unfixed; this closes it for Henry specifically). Returns the
    snapshot sha, or "" when the tree was clean.

    IT IS NOT A COMMIT ANY MORE (owner, 2026-09-23: "Fix commits"). It used
    to be `git add -A` + `git commit`, and on a shared live tree that
    swallows whatever else is in flight: three times that day it took work
    that was not Henry's - an unapproved Wear edit set, then two finished
    changes of the owner's own - and filed all of it under "Henry baseline",
    erasing the real messages and the authorship. A rollback point does not
    have to be reachable from a branch, it only has to EXIST:
    gitutil.snapshot_object writes a dangling commit from a throwaway index
    and mutates neither HEAD nor the index nor the working tree."""
    from spine.git.gitutil import snapshot_object
    return snapshot_object(
        _HENRY_REPO_ROOT, "Henry baseline - rollback point before a hands-on turn")


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
        snap = _baseline_commit()
        if snap:
            # The sha has to reach a human, or the rollback point is a secret:
            # a dangling object is invisible in `git log` by design. One line,
            # in the prompt Henry is already reading, so his own "did" report
            # can quote it.
            prompt += ("\n\nROLLBACK-PUNKT vor diesem Turn: %s "
                       "(haengender Commit, nicht im Log - zurueck mit "
                       "`git checkout %s -- .`). Nenne ihn in deinem \"did\", "
                       "wenn du am Baum etwas geaendert hast."
                       % (snap[:12], snap[:12]))
        return _ask(prompt, perm=None)
    finally:
        lock.release()


def _snapshot():
    """One screenful of system truth - derived live at read time, never a
    stored flag (the no-monkey-patch law)."""
    lines = []
    cap = 40                           # total budget; the CARD list absorbs any cut
    try:                               # the goal first - see goal_drive
        from cells.copilot.planning import goal_drive
        gl = goal_drive.goal_line(goal_drive.goal_state())
        if gl:
            lines += gl.split("\n")
    except Exception as e:                                   # noqa: BLE001
        lines.append("GOAL: (unreadable: %s)" % str(e)[:120])
    cards = []
    try:
        from spine.storage.trackstore import _load
        from spine.agent import drivers
        for t in _load():
            # example: the onboarding demo card (accounts-boards-prd phase 3) -
            # inert, never dispatched, and Henry must never plan/reason about it.
            if t.get("archived") or t.get("lane") == "done" or t.get("example"):
                continue
            cards.append("card %s | %s/%s | ft=%s direct=%s turn_active=%s | %s" % (
                t["id"], t.get("lane"), t.get("status"), bool(t.get("fast_track")),
                bool(t.get("direct")), drivers.turn_active(t["id"]),
                (t.get("task") or "")[:60]))
    except Exception as e:
        lines.append("(board unreadable: %s)" % e)
    # lock / load lines BEFORE the card list: the cap used to cut them first
    # (they were appended last), and a missing "ship.lock: frei" reads as unknown
    lines.append(_ship_lock_line())
    lines.append(_android_lock_line())
    lines.append(_box_load_line())
    lines.append(_heavy_procs_line())
    room = max(cap - len(lines) - 1, 0)
    head = ("Karten (nur live: nicht archiviert, nicht in done, keine Beispiel-Karte; "
            "%d gelistet)" % len(cards))
    shown = cards[:room]
    out = lines + [head] + shown
    if len(cards) > len(shown):
        out.append("(+%d weitere Karten nicht gezeigt)" % (len(cards) - len(shown)))
    return "\n".join(out)


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


def _android_lock_line():
    """The machine-global Android build mutex (ops/deploy/build_lock.sh), read
    the same way ship.lock is: a LIVE-PID observation, never a stored flag.
    Henry needs this because "why is my build not starting" and "why did two
    builds break each other" are the SAME question seen from two sides - a
    queued build is healthy and must not be judged as a stuck card, which is
    exactly the misread the 2026-08-30 incident produced."""
    pid = _android_lock_pid()
    if pid is None:
        return "android-build.lock: frei"
    label = ""
    try:
        with open(os.path.join(_ANDROID_LOCK, "label"), encoding="utf-8") as f:
            label = f.read().strip()[:80]
    except OSError:
        pass
    return "android-build.lock: pid %s (%s)%s" % (
        pid, "LIVE - ein Build laeuft, weitere warten" if _pid_alive(pid) else "dead/stale",
        (" | %s" % label) if label else "")


# Machine-global on purpose - NOT under the repo, because two checkouts share
# one Gradle daemon. Mirrors ops/deploy/build_lock.sh's HELMDECK_LOCK_DIR.
_ANDROID_LOCK = os.path.join(
    os.environ.get("HELMDECK_LOCK_DIR")
    or os.path.join(os.path.expanduser("~"), ".helmdeck", "locks"),
    "android-build")


def _android_lock_pid():
    try:
        lines = [l.strip() for l in
                 open(os.path.join(_ANDROID_LOCK, "pid")).read().splitlines() if l.strip()]
    except OSError:
        return None
    if not lines:
        return None
    return lines[1] if len(lines) > 1 else lines[0]   # line 2 = real Windows pid


def _pid_alive(pid):
    # procwatch.exists, never os.kill(pid, 0): on Windows that TERMINATES the
    # lock holder - every snapshot killed the running ship/build it reported on.
    from spine.ops import procwatch
    return procwatch.exists(pid)


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
                             text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
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
        from spine.ops.actionlog import read_timeline
        allrecs = read_timeline(t.get("run_dir") or "")
        recs = allrecs[-n:]

        def _d(r):
            d = str(r.get("detail", ""))
            return d[:220] + "\u2026" if len(d) > 220 else d
        head = ("(letzte %d von %d Eintraegen; Details auf 220 Zeichen gekuerzt, "
                "\u2026 = gekuerzt)\n" % (len(recs), len(allrecs)))
        return head + "\n".join("%s %s: %s" % (r.get("ts", "?"), r.get("kind", "?"),
                                               _d(r)) for r in recs)
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
            return ("\n== AUDIT (juengste Ereignisse dieser Karte) ==\n" +
                    ("Audit nicht lesbar (Berechtigung des Auftraggebers)" if disp else
                     "Audit nicht lesbar (kein Auftraggeber an der Karte)") + "\n")
        allrows = events.query_audit(track=t.get("id"))
        rows = allrows[-8:]
        if not rows:
            return ""
        lines = ["%s  %s  actor=%s%s" % (
            e.get("at_utc", "?"), e.get("kind", "?"), e.get("actor", "-"),
            ("  " + e["reason"]) if e.get("reason") else "")
            for e in rows]
        return ("\n== AUDIT (juengste Ereignisse dieser Karte; letzte %d von %d "
                "Audit-Eintraegen) ==\n" % (len(rows), len(allrows)) + "\n".join(lines))
    except Exception:
        # never let a context-enrichment failure block the judgement turn - but
        # say the section is missing, an empty string reads as "no events"
        return ("\n== AUDIT (juengste Ereignisse dieser Karte) ==\n"
                "Audit nicht lesbar (Fehler beim Lesen)\n")


def _judgement_policy(t):
    """The mandate this judgement turn opens with, resolved through the declared
    chain (default -> workspace -> project) rather than read off a global key.

    THE PROJECT IS DERIVED FROM THE EVENT, at event time, exactly as
    projectconfig's docstring requires: the escalation's own card carries the
    repo it was dispatched against, so a card-less escalation (box load, a
    deploy hook) honestly resolves the workspace layer instead of being pinned
    to whatever repo happens to be default.

    Degrades to DEFAULT_POLICY on ANY failure. A broken store must never leave
    the broker judging with an empty mandate - that would not be a degraded
    Henry, it would be an unbriefed one."""
    try:
        from spine.registry import behavior
        from spine.storage import projectconfig
        v = behavior.value("report.judgement_policy", "all",
                           projectconfig.for_card(t))
        if isinstance(v, str) and v.strip():
            return v.strip()
    except Exception:                                        # noqa: BLE001
        pass
    return DEFAULT_POLICY


def _staged_ask(prompt, esc, privileged):
    """Round 1 without tools; up to NEED_ROUNDS `need` reloads (still no
    tools, each adds to what he already read); a `hands` round with
    HANDS_TOOLS only when Henry says he must act himself and the escalation
    allows it. A plain `did` from a tool-less round is read as `hands` -
    nothing was done yet, the text is the plan."""
    _ROUND["tools"] = STAGE1_TOOLS
    fetched = []
    try:
        d = _ask(prompt + _STAGE1_TAIL, perm=STAGE1_PERM)
        for n in range(NEED_ROUNDS):
            if (d.get("action") or "").strip() != "need":
                break
            items = d.get("data") or []
            if isinstance(items, str):
                items = [x.strip() for x in items.split(",") if x.strip()]
            escalations.record_note(esc["id"], "Henry liest nach: %s" % ", ".join(map(str, items))[:200])
            fetched.append(_fetch_need(items, esc.get("card")))
            last = n == NEED_ROUNDS - 1
            d = _ask(prompt + "\n\n== NACHGELADEN (auf deine Anfrage) ==\n" + "\n\n".join(fetched)
                     + ("\n\nWeiteres \"need\" gibt es nicht - entscheide jetzt." if last else "")
                     + _STAGE1_TAIL, perm=STAGE1_PERM)
    finally:
        _ROUND["tools"] = None
    action = (d.get("action") or "").strip()
    if action in ("hands", "did", "need") and privileged:
        plan = (d.get("text") or d.get("why") or "").strip() or "(kein Vorhaben genannt)"
        escalations.record_note(esc["id"], "Henry nimmt die Haende: %s" % plan[:200])
        _ROUND["tools"] = HANDS_TOOLS
        try:
            d = _hands_on_ask(prompt + _HANDS_TAIL % plan)
        finally:
            _ROUND["tools"] = None
    elif action == "hands":
        d["action"] = "did"          # the unprivileged refusal below handles it
    return d


def _decide(esc):
    """One judgement round. Returns True if the escalation was closed."""
    card_log = _card_log_tail(esc.get("card"))
    t = _find_track(esc.get("card"))
    policy = _judgement_policy(t)
    privileged = _dispatcher_privileged(t)
    prompt = (
        policy
        + "\n\n== ESKALATION ==\nkind: %s\ncard: %s\ndetail:\n%s\n" % (
            esc["kind"], esc.get("card") or "-", esc.get("detail") or "")
        + (("Vermerk: %s\n" % esc["last_note"]) if "unterdrueckt" in (esc.get("last_note") or "") else "")
        + ("\n== KARTE (actionlog, juengste zuerst unten) ==\n" + card_log + "\n" if card_log else "")
        + _audit_context(t)
        + "\n== SYSTEM ==\n" + _snapshot())
    if not privileged:
        # This card was filed by a client-role account, not owner/operator -
        # Henry gets NO hands for it (spine.auth.devices' same distinction:
        # dispatched_by, resolved fresh, not the client billing label).
        # The staged round has no tools anyway; the note stops him asking
        # for a hands round he will not get.
        prompt += (
            "\n\nHINWEIS: Diese Karte wurde von einem client-Account "
            "eingereicht - du hast fuer sie KEINE Haende (nur lesen). "
            "action \"hands\"/\"did\" ist nicht verfuegbar; nutze steer/notify_owner/"
            "ignore.")
    from cells.copilot.chat import copilot as _cp
    try:
        d = _staged_ask(prompt, esc, privileged)
    except _cp.JudgePreempted:
        # the owner wrote while this ran - his message went first; not an
        # attempt (the 2-attempt cap is for judgements, not interruptions)
        escalations.record_note(esc["id"], "vom Owner-Chat unterbrochen - naechste Runde")
        return False
    except Exception as e:
        escalations.record_attempt(esc["id"])
        escalations.record_note(esc["id"], "ask failed: %s" % str(e)[:200])
        return False
    # counted once a judgement actually came back (or failed on its own) -
    # recorded here, not before the ask, so an owner interruption is free
    escalations.record_attempt(esc["id"])
    den = d.get("_denials") or []
    if den:
        escalations.record_note(esc["id"], "Policy hat %d Aufruf(e) geblockt: %s" % (
            len(den), "; ".join(_denial_line(x) for x in den[:5])))
    action = (d.get("action") or "").strip()
    card = (d.get("card") or esc.get("card") or "").strip()
    lane = (d.get("lane") or "").strip()
    kind = (d.get("kind") or "").strip()
    text = (d.get("text") or "").strip()
    why = (d.get("why") or "").strip()
    at = (d.get("at") or "").strip()
    goal = d.get("goal") is True
    repo = (d.get("repo") or "").strip()      # the project new work belongs to - named, never defaulted
    if action in ("did", "direct_task", "machine_task", "accept_steps", "cancel_process",
                  "finish_process", "set_next", "answer") \
            and not privileged:
        # Defense in depth: even if the model tried anyway, this card's
        # escalation does not get closed via "did" - stays open for a
        # privileged human/owner to see, same shape as the GxP refusal
        # below (_execute's did/move gate).
        escalations.record_note(esc["id"],
            "Henry versuchte '%s' auf einer client-Karte ohne Haende - "
            "abgelehnt, bleibt offen" % action)
        return False
    if not _execute(action, card, lane, text, esc, kind=kind, why=why, at=at, goal=goal, repo=repo):
        return False   # malformed verb - stays open for the next attempt
    escalations.record_decision(esc["id"], action, card=card, why=why,
                                kind=kind if action == "ship" else "")
    # Full text here too: _audit lands as a `note` in the card's ActionLog, and
    # the card chat RENDERS notes (card_transcript.tsx kind === "note") - so a
    # cut here is a mid-word chat message on the card surface as well.
    #
    # ONE card line per decision. A report-back action ends in _notify_owner,
    # which writes the full "Henry (kind): action - text" into the card audit
    # itself (its t is the card) - so this audit line used to land a SECOND
    # time for the same decision, 1s apart (owner screenshot 2026-10-07). It
    # now only stands alone where the report-back does not reach the card:
    # `did` (t=None there), the quiet verbs, and a machine card's DONE.
    _machine_done = action == "move" and lane == "done" and bool(
        (_find_track(card) or {}).get("machine"))
    _reports = action in ("did", "ship", "restart", "rerun_deploy", "steer", "answer", "direct_task",
                          "machine_task") or (action == "move" and not _machine_done)
    if not (_reports and action != "did" and _find_track(card)):
        _audit(card, "HENRY entschieden (%s): %s - %s" % (
            esc["kind"], action,
            (text + (" | " + why if why else "")) if action == "did" else (why or text)))
    # REPORT BACK on every closing action (owner decree 2026-08-21: "if the work
    # is done he doesn't report back") - notify_owner/give-up already push; the
    # quiet successes (did/move/rerun/steer) were invisible until now.
    # `move` used to be excluded whole (owner report 2026-09-12, "Karte sendet
    # push und Henry auch": a lane move already narrates itself - _say_card's
    # "auf Review geprueft"/"abgenommen und gemergt" - and DONE already pushes
    # via notify.card_event, so a second push here would be the same
    # regression again). That carve-out still holds for DONE, but the owner's
    # 2026-09-18 complaint ("warum muss ich nochmal fragen") is that neither
    # of those lines EVER carries what the worker actually said, only that
    # something landed - and REVIEW gets no push AT ALL today (verified:
    # lanemachine's review tail and _accept_machine's review branch are both
    # chat-only). So `move` now reports back too, carrying HENRY's own account
    # (text; the worker's raw reply is NOT pasted in, 2026-10-09) - push only
    # for review (filling a real gap, not doubling one), chat always - EXCEPT
    # a machine/direct card's DONE, which stays dispatch._accept_machine's own
    # job (it gets the same note - see move_lane's `note` param) so the two
    # don't both print the same line for the same event.
    if _reports:
        # FULL text - the 180-char cut that used to live here was a PUSH budget
        # (owner report 2026-08-28: Henry's chat messages "end mid-word"). Since
        # 52033b6 this same string is also the board/card CHAT message, and a
        # chat has no length budget: _notify_owner truncates for FCM alone.
        _label = action + ((" " + kind) if action == "ship" and kind else "")
        # The owner reads HENRY's words (text = what was delivered, what
        # happens next), never the worker's raw reply pasted in - the worker
        # writes for Henry, Henry writes for the owner (2026-10-09).
        _body = text or why
        # A `move` is the ONE message the owner gets for a finished card
        # (dispatch._accept_machine no longer adds a canned line beside it),
        # so it is Henry's words ONLY - the "Henry (kind): move -> review -"
        # prefix is log vocabulary and read as a wall of text (owner
        # 2026-10-10). Other verbs keep the prefix: they are not the card's
        # hand-over.
        _line = _body if action == "move" else "Henry (%s): %s%s - %s" % (
            esc["kind"], _label, "", _body)
        # An open owner decision on a review hand-over is a QUESTION WITH
        # BUTTONS, not more prose (owner 2026-10-10: explain plainly, ask what
        # is open, do not bury the ask in a wall of text). One chat line: the
        # explanation IS the question's text.
        _opts = _ask_options(d) if (action == "move" and lane == "review") else []
        if _opts:
            from cells.copilot.planning import pm_comm
            if _find_track(card):
                _audit(card, _line)
            if pm_comm._ask_owner(_line, _opts, card=card):
                return True
        _notify_owner(_line, None if action == "did" else _find_track(card),
                      push=(action != "move" or lane == "review"))
    return True


def _ask_options(d):
    """The 2-4 tap answers Henry named for the owner's open decision on a
    review hand-over (`ask`: ["Abnehmen", ...]); [] = nothing is open."""
    raw = d.get("ask")
    if isinstance(raw, dict):
        raw = raw.get("options")
    if not isinstance(raw, list):
        return []
    out = [{"label": str(o).strip()[:40]} for o in raw if str(o).strip()]
    return out[:4] if len(out) >= 2 else []


def _denial_line(x):
    ti = x.get("tool_input") or {}
    what = ti.get("command") or ti.get("file_path") or ti.get("path") or ""
    return "%s %s" % (x.get("tool_name") or "?", str(what).replace("\n", " ")[:80])


def _find_track(card):
    try:
        from spine.storage.trackstore import _load, _find
        return _find(_load(), card) if card else None
    except Exception:
        return None


def _esc_process(esc, goal=False):
    """The process an escalation is about: its own `process` record
    (process_drive), or the goal's process for a goal-move - or when Henry's
    judgement says the new card serves the goal ("goal": true). Measured
    2026-09-30: card 20260930-004651 ("ZIEL-KARTE, Nachfrage-Messung") was
    started from an idle-check and never counted as goal work - only a
    goal-move could mark one."""
    if esc.get("process"):
        return esc["process"]
    if esc.get("kind") == "goal-move" or goal:
        from cells.copilot.planning.pm_goal import ensure_goal_process
        return ensure_goal_process()
    return ""


def _execute(action, card, lane, text, esc, kind="", why="", at="", goal=False, repo=""):
    from spine.auth import gxp
    from spine.storage.trackstore import _load, _find
    t = _find(_load(), card) if card else None
    if action == "ignore":
        return True
    if action in ("accept_steps", "cancel_process", "finish_process", "set_next"):
        # PROCESS DECISIONS are Henry's (owner 2026-09-30: the process asked
        # the owner things no human is needed for). Only on an escalation
        # that names its process - never a guessed one.
        from cells.engineer.chains import processes
        from spine.storage import events
        pid = _esc_process(esc)
        if not pid or not processes.get(pid):
            escalations.record_note(esc["id"], "%s: kein Prozess an dieser Eskalation" % action)
            return False
        try:
            if action == "accept_steps":
                repo = repo or (processes.get(pid) or {}).get("repo") or ""
                if not repo:
                    # no silent fallback into the HelmDeck repo (projects.project_question)
                    escalations.record_note(esc["id"], "accept_steps: der Prozess nennt kein Projekt - "
                                                       "Henry fragt den Owner, wo die Arbeit hingehört")
                    return False
                _p, made = processes.accept_all(pid, repo, actor="henry")
                escalations.record_note(esc["id"], "accept_steps: %s -> %s" % (
                    pid, ", ".join(made) or "nichts offen"))
            elif action == "cancel_process":
                processes.cancel_process(pid, actor="henry")
                escalations.record_note(esc["id"], "cancel_process: %s" % pid)
            elif action == "finish_process":
                processes.finish_process(pid, actor="henry")
                escalations.record_note(esc["id"], "finish_process: %s" % pid)
            else:
                if not (text or "").strip():
                    # an empty `what` CLEARS the next move (set_next's own rule):
                    # a decision that merely forgot "text" must not silently
                    # delete the schedule it believes it just set (2026-10-06)
                    escalations.record_note(esc["id"], "set_next ohne text - nichts gesetzt, "
                                            "bleibt offen (text = was, at = wann)")
                    return False
                processes.set_next(pid, text, at, actor="henry")
                escalations.record_note(esc["id"], "set_next: %s - %s" % (at, text[:200]))
        except (RuntimeError, ValueError) as e:
            escalations.record_note(esc["id"], "%s: %s" % (action, str(e)[:250]))
            return False
        return True
    # THE OPEN-QUESTION RAIL (owner report 2026-09-05, screenshot: a card that
    # ASKED him "vc91 ready to upload - how do you want to proceed?" got
    # move->done by a context-bloat judgement, discarding his three-option Play
    # decision). A card carrying an unanswered owner question is NOT finished
    # work - turnrunner.is_delivered says so, and the sync() auto-accept path
    # already refuses it there; Henry's own move/did verbs bypassed that guard.
    # A CLOSE over a pending decision is exactly what must never be automatic,
    # so it is refused in CODE here (a hard invariant, like the GxP guard
    # below), not left to judgement. The escalation stays open and the owner
    # keeps his question; steer/notify_owner/ignore remain available.
    if action in ("did", "move", "ship") and t and t.get("question"):
        escalations.record_note(esc["id"],
            "%s abgelehnt: Karte hat eine offene Frage an den Owner "
            "('%s') - die wird nicht durch Schliessen verworfen. Bleibt offen "
            "fuer seine Entscheidung." % (
                action,
                str((t.get("question") or {}).get("header")
                    or (t.get("question") or {}).get("question") or "")[:80]))
        return False
    if action == "restart":
        # The ONE restart verb (spine/ops/daemonctl, 2026-09-12): the same
        # code path as the Settings button. It refuses while a turn is live -
        # that refusal is a fact for the next attempt, not something Henry
        # works around with a shell.
        from spine.ops import daemonctl
        r = daemonctl.restart(actor="henry")
        if not r.get("ok"):
            escalations.record_note(esc["id"], "restart verweigert: %s %s" % (
                r.get("reason"), (r.get("detail") or "")[:160]))
            return False
        return True
    if action == "ship":
        # The ship DECISION, executed as its own visible board card (owner
        # decree 2026-09-01: shipping is Henry's judgement, not a post-done
        # reflex - the emit half is lanemachine.request_ship_decision, this
        # is the execute half; pays debt ship-decision-not-wired). Owner
        # decree 2026-09-09, 18:04 correction: EXECUTION is no longer an
        # invisible deploy-hook subprocess - `kind` none|ota|native is the
        # advisor contract, and ota/native now spawn a SHIP CARD
        # (dispatch.new_ship_task) instead of calling _repo_hook directly.
        # That card's own agent turn (cells/engineer/harness/agents/
        # ship-worker.md) does DIAGNOSE -> EXECUTE -> VERIFY as its own
        # reasoning and self-closes on a 'SHIP: OK' verdict
        # (sessions._maybe_ship_card_close) - none = a deliberate non-ship
        # (docs-only, daemon-only - the answer the old hash could never give).
        #
        # This escalation closes the MOMENT the card exists, not when the
        # ship finishes: the CARD is now the durable, visible record of "is
        # this ship done, in progress, or stuck" (lane/status/timeline, same
        # as any other card), so there is nothing left for the escalation to
        # wait on. A failed ship card simply parks needs_you like any other
        # stuck card - Henry's own board snapshot already shows it to him on
        # his next pass; no retry ladder needed here (unlike the old
        # rerun_deploy path, which still exists for a bare _repo_hook retry
        # but no longer applies to ship-decision escalations specifically).
        if kind == "none":
            return True                # deliberate non-ship; why lands in the audit note
        if kind not in ("ota", "native"):
            escalations.record_note(esc["id"],
                "ship: kind %r ist nicht none|ota|native - bleibt offen" % kind)
            return False
        from cells.engineer.cards import dispatch
        from spine.storage import events
        repo = (t or {}).get("repo") or events.settings().get("default_repo") or ""
        if not repo:
            escalations.record_note(esc["id"], "ship: kein Repo bekannt - keine Ship-Karte angelegt")
            return False
        origin = t.get("id") if t and t.get("id") != "-" else None
        try:
            card = dispatch.new_ship_task(repo, kind, actor="henry", origin_card=origin)
        except Exception as e:
            escalations.record_note(esc["id"], "ship: Karte konnte nicht angelegt werden: %s" % str(e)[:250])
            return False
        escalations.record_note(esc["id"],
            "ship (%s): Karte %s angelegt - laeuft ab jetzt als eigene Karte auf dem Board."
            % (kind, card.get("id", "?")))
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
        from cells.engineer.cards import sessions
        try:
            r = sessions.move_lane(t["id"], lane, actor="henry", note=(text or why or ""))
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
    if action == "answer":
        # Henry settles a TRIVIAL worker question himself (owner 2026-10-18); the
        # owner saw the same question directly and may have answered first, so
        # the request_id the escalation carries is the guard - a settled or
        # replaced question is a quiet no-op, never a second steer.
        import re
        from cells.engineer.cards import sessions
        if not t or not (text or "").strip():
            escalations.record_note(esc["id"], "answer: Karte oder Antworttext fehlt - bleibt offen")
            return False
        m = re.search(r"request_id:\s*(\S+)", esc.get("detail") or "")
        rid = m.group(1) if m else ""
        q = t.get("question") or {}
        if not q or (rid and rid != (q.get("id") or "")):
            escalations.record_note(esc["id"], "answer: Frage schon beantwortet oder ersetzt - nichts gesendet")
            return True
        routed, answers, qid = sessions.reply_door(t, text.strip())
        if routed != "answer":
            escalations.record_note(esc["id"], "answer: mehrere Fragen oder keine gueltige Antwort - Owner entscheidet")
            return True
        try:
            sessions.answer_question(t["id"], answers, request_id=qid, actor="henry")
        except Exception as e:                               # noqa: BLE001
            escalations.record_note(esc["id"], "answer nicht angekommen: %s" % str(e)[:200])
            return True            # lost the race to the owner (or invalid) - not a retry case
        return True
    if action == "steer" and t and text:
        from cells.engineer.cards import sessions
        from spine.ops import bgthread
        bgthread.spawn("track:steer:" + t["id"], lambda: sessions.steer(
            t["id"], text, actor="henry", source="henry-escalation"))
        return True
    if action == "rerun_deploy":
        # NO LONGER the ship-decision retry path (owner decree 2026-09-09,
        # 18:04 correction: a ship is its own card now - a failed one parks
        # needs_you and is steered/re-run like any other stuck card, not via
        # this verb). Kept for whatever OTHER repo_hooks['deploy'] use a
        # future escalation kind might name directly - a bare _repo_hook
        # retry, unrelated to Henry's `ship` verb above.
        from cells.engineer.cards.lanemachine import _repo_hook
        from spine.storage import events
        if t is None:
            # card-less ship abort: rebuild the hook target from the default
            # repo - the hook only needs repo/run_dir-shaped fields.
            repo = events.settings().get("default_repo") or ""
            if not repo:
                return False
            t = {"id": "-", "repo": repo, "run_dir": os.path.join(_DATA_ROOT, "recordings", "_henry"),
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
        # SYNCHRONOUS + VERIFIED (was fire-and-forget until 2026-08-28, same
        # blind spot the "move" verb had): _repo_hook can run for many minutes
        # (a native APK build) and returns True/False/None on its OWN thread's
        # local dict - closing the escalation the instant the thread STARTED
        # meant a SECOND red build (measured live: card
        # chat-wear-os-integration-phas failed again at 13:20 with an
        # unrelated Gradle-daemon error) had nowhere to go - the escalation
        # was already "decided", so nobody was told. Runs to completion here
        # and checks the hook's own verdict before deciding whether to close.
        try:
            hk = _repo_hook(dict(t), "deploy")
        except Exception as e:
            escalations.record_note(esc["id"], "rerun_deploy crashed: %s" % str(e)[:250])
            return False
        if hk is False:
            escalations.record_note(esc["id"],
                "rerun_deploy: Deploy-Hook wieder rot - bleibt offen fuer den naechsten Versuch.")
            return False           # stays open (2-attempt cap), next attempt gets fresh eyes
        return True
    if action == "notify_owner":
        _notify_owner("Henry (%s): %s" % (esc["kind"], text or esc.get("detail") or ""), t)
        return True
    if action in ("direct_task", "machine_task") and text:
        # START the next piece of work (owner 2026-09-28, goal_drive): the
        # chat's direct_task / machine_task verbs, reachable from a judgement
        # too - without them a wake could only do the work inline ("did") or
        # talk about it. machine_task = the owner's PC as workplace (windows-
        # mcp + browser, owner 2026-09-30: work that needs the desktop starts
        # directly). Same policy switch as the chat verbs (policy.machine.
        # enabled); _decide only lets a privileged judgement get here. A card
        # filed from a goal-move or process-move is a STEP of that process BY
        # RECORD (attach_card below) - never inferred from the task text.
        from cells.engineer.cards import sessions
        from spine.storage import events
        if not sessions.machine_policy().get("enabled", True):
            escalations.record_note(esc["id"], "%s: policy.machine.enabled=false" % action)
            return False
        try:
            if action == "machine_task":
                import os as _os
                nt = sessions.new_machine_task(_os.path.expanduser("~"), text,
                                               actor="henry", priority="high")
            else:
                # the judgement names it, else the card's or the process's own project - never default_repo
                from cells.engineer.chains import processes as _procs
                pid_ = _esc_process(esc)
                card_repo = next((x.get("repo") for x in sessions._load() if card and x.get("id") == card), "")
                repo = (repo or card_repo or ((_procs.get(pid_) or {}).get("repo") if pid_ else "") or "").strip()
                if not repo:
                    escalations.record_note(esc["id"], "direct_task: kein Projekt bekannt - "
                                                       "Henry fragt den Owner, wo die Arbeit hingehört")
                    return False
                nt = sessions.new_direct_task(repo, text, actor="henry", priority="high")
        except Exception as e:
            escalations.record_note(esc["id"], "%s: Start fehlgeschlagen: %s" % (action, str(e)[:250]))
            return False
        # the new card is a STEP of the process the escalation is about - the
        # goal's process for a goal-move or "goal": true - by record, at filing time
        pid = _esc_process(esc, goal=goal)
        if pid:
            try:
                from cells.engineer.chains import processes
                processes.attach_card(pid, nt["id"], actor="henry")
            except Exception as e:                           # noqa: BLE001
                escalations.record_note(esc["id"], "Prozess-Link fehlgeschlagen: %s"
                                        % str(e)[:200])
        escalations.record_note(esc["id"], "%s: Karte %s gestartet" % (action, nt["id"]))
        return True
    return False


def _give_up(esc):
    escalations.record_decision(esc["id"], "escalated",
                                why="no safe automatic decision after %d attempts" % _max_attempts())
    _notify_owner("Henry gibt ab (%s): %s" % (esc["kind"], esc.get("detail") or ""), None)


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


def _notify_owner(text, t, push=True):
    """`text` arrives WHOLE. Exactly one consumer has a length budget - the FCM
    push - and it truncates here, at its own edge. The chat and the card audit
    get the full message: callers must never pre-truncate for the push, or the
    notification's limit silently becomes the chat's (owner report 2026-08-28,
    "Nachrichten enden mitten im Wort").

    `push=False` for a caller whose event already pushes elsewhere (a `move`
    landing on DONE: notify.card_event fires from the lane pipeline itself) -
    the chat write below still happens, only the second buzz is skipped."""
    # PRESENCE-GATED, like every other harness push (owner report 2026-09-12,
    # "viele Meldungen doppelt"): this was a raw push_fcm - the ONE sender in
    # the daemon that skipped notify's 3-tier presence policy, so a Henry
    # decision buzzed the phone while the owner was looking at that very chat,
    # right after the card's own (correctly suppressed) push. notify.escalate
    # is the PM's path for exactly this shape - "alert whose chat line has
    # already landed" - and its dedup is the caller's job: the chat line below
    # is written once per decision, so the push is too.
    if push:
        try:
            from spine.comms import notify
            from spine.registry import i18n as _i18n
            notify.escalate(_i18n.t("push.henry"), text[:230], (t or {}).get("id") or "")
        except Exception:
            pass
    # ALSO into the board chat (owner observation 2026-08-28, "warum nichts im
    # Chat"): the push is suppressed exactly when the owner is LOOKING at the
    # app (notify's owner-presence dedup) and held in quiet hours, and the
    # audit note lives on the card - so the one surface the owner actually
    # reads while watching Henry work, the Henry chat, showed none of the
    # broker's decisions. copilot.say is the same line the lane pipeline's
    # _say_card uses; best-effort like the push.
    #
    # WHOLE, like every other chat message. A notice.short() clip stood here for
    # one day (2026-08-30) and the owner photographed the result the same
    # afternoon: his 14:08 chat card ended "... kein Agent-Turn) …" mid-thought,
    # while the ordinary bot bubbles right above it were intact. The reason it
    # looked like a rogue widget is that it WAS a rogue clip - but on the write
    # side, not the render side (see the module note above _decide's report-back).
    #
    # The two-sentence law is a law about CHANNELS THAT CANNOT SCROLL - the FCM
    # push (its own 230 above) and a question's button header. The chat is a
    # transcript: card_transcript.tsx already folds anything past 1600 chars
    # behind a "mehr anzeigen" toggle, which gives the decree what it actually
    # wanted (no wall) without amputating the sentence that carries Henry's
    # point. Clipping here just moved the push's budget onto the transcript -
    # precisely what this function's own docstring forbids.
    try:
        from cells.copilot.chat import copilot
        copilot.say(text, cls="pm", card=(t or {}).get("id") or None)
    except Exception:
        pass
    if t:
        _audit(t["id"], text)


# kind emitted by copilot_actions.py's follow_up chat verb - the owner's
# "I'll check and report back" promise, which the loop below must keep on a
# bounded clock of its own, not whatever clock the rest of the queue happens
# to run on.
_FOLLOWUP_KIND = "henry-followup"

# Follow-ups already dispatched on a prior tick (still running - _ask can
# outlast one _interval_s() sleep) must not be re-dispatched: two threads
# deciding the SAME escalation concurrently would double-attempt it and
# could double-execute its action (a second "did", a second "move").
_followups_inflight = set()
_followups_lock = threading.Lock()


def _ts_epoch(s):
    try:
        return time.mktime(time.strptime(s or "", "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return 0.0


def followup_tasks(closed_within_s=3600):
    """The Henry chat's BACKGROUND line (owner report 2026-09-12: "Henry sagt
    er macht was, aber ich sehe nichts"): every henry-followup escalation as a
    BgTask-shaped descriptor - the same object a card's bg_tasks are (Paseo
    status running|completed|failed), rendered by the same BackgroundTasks
    line. The follow_up verb answers "notiert" and the broker judges on its
    own thread for minutes; this is the ONLY place the owner can see that
    something is in flight, how long, and how it ended.

    DERIVED from the append-only escalation records at read time (fold):
      open                      -> running,   result = last note if any
      decided (real action)     -> completed, result = why
      given up ("escalated")    -> failed,    result = last note or detail
      closed > closed_within_s  -> dropped (the chat line reported it)"""
    out = {}
    now = time.time()
    try:
        folded = escalations.fold()
    except Exception:
        return out
    for eid, e in folded.items():
        if e.get("kind") != _FOLLOWUP_KIND:
            continue
        opened = _ts_epoch(e.get("ts"))
        detail = (e.get("detail") or "").strip()
        if e.get("closed"):
            decided = _ts_epoch(e.get("decided_ts")) or opened
            if now - decided > closed_within_s:
                continue
            failed = (e.get("action") or "") == "escalated"
            out[eid] = {"title": detail[:90], "status": "failed" if failed else "completed",
                        "since": opened, "updated": decided, "detail": detail,
                        "result": ((e.get("last_note") or detail) if failed
                                   else (e.get("why") or e.get("action") or ""))}
        else:
            out[eid] = {"title": detail[:90], "status": "running",
                        "since": opened, "updated": opened, "detail": detail,
                        "result": e.get("last_note") or ""}
    return out


def _decide_or_give_up(esc):
    if esc["attempts"] >= _max_attempts():
        _give_up(esc)
        return
    _decide(esc)


def _run_followup(esc):
    try:
        _decide_or_give_up(esc)
    except Exception:
        print("henry: followup loop error (%s):\n" % esc["id"] + traceback.format_exc())
    finally:
        with _followups_lock:
            _followups_inflight.discard(esc["id"])


_AFTER_MAX_WAIT_S = 6 * 3600


def _followup_waits(e):
    """True while a follow-up's `after` card still has a turn alive (queued or
    running). 2026-10-11 12:36: Henry filed "when the pages card is done, start
    three apps" - the broker took it up at once, found nothing to do, and gave
    up after two attempts; nothing ever started the next stage until the owner
    typed "Ok" 1.5h later. A conditional promise needs a condition the harness
    can see: derived from the runtime (drivers.turn_inflight), never a stored
    flag, and bounded so a card that never settles cannot park it forever."""
    after = e.get("after")
    if not after:
        return False
    if time.time() - _ts_epoch(e.get("ts")) > _AFTER_MAX_WAIT_S:
        return False
    try:
        from spine.agent import drivers
        return bool(drivers.turn_inflight(after))
    except Exception:                                          # noqa: BLE001
        return False


def _dispatch_pass(open_escs):
    """One while-loop tick's worth of work, split by kind (owner complaint
    2026-09-10: a henry-followup escalation opened at 12:38:47 got its first
    attempt only at 12:43:19 because the strictly serial `for` loop this
    replaced was still blocked inside a single slow ship-decision _decide()
    call - _ask can run up to 900s, plus up to 60s waiting on the direct-
    tree lock, and NOTHING else in that pass could even be looked at until
    it returned).

    HENRY-FOLLOWUP escalations get their own thread each, dispatched FIRST,
    before anything else in this pass has a chance to block the thread this
    function runs on. Every other kind keeps the original serial behaviour -
    one escalation's _decide() at a time, in list order, on this thread -
    unchanged: turning every escalation kind into a worker pool was not what
    was asked for and would need its own concurrency review of the
    invariants _execute enforces (GxP scope, the open-question rail, the
    2-attempt cap) under real parallelism. Follow-ups are the narrow, safe
    case - _hands_on_ask's own _direct_lock_for already serializes any
    tree-touching turn against every other one (Henry or a direct-build
    card), so running several _decide() calls at once does not reintroduce
    the race that lock exists to prevent.

    Returns the list of Threads started (empty if none) - callers that need
    to wait for a pass to finish (tests) can join() them; the live loop does
    not."""
    followups = [e for e in open_escs
                 if e["kind"] == _FOLLOWUP_KIND and not _followup_waits(e)]
    others = [e for e in open_escs if e["kind"] != _FOLLOWUP_KIND]
    started = []
    for esc in followups:
        eid = esc["id"]
        with _followups_lock:
            if eid in _followups_inflight:
                continue
            _followups_inflight.add(eid)
        th = threading.Thread(target=_run_followup, args=(esc,), daemon=True)
        started.append(th)
        th.start()
    for esc in others:
        _decide_or_give_up(esc)
    return started


def _loop():
    while True:
        try:
            _dispatch_pass(escalations.list_open())
        except Exception:
            # never die, but never be SILENT either - an invisible broken broker
            # is exactly the class of failure Henry exists to end. Full
            # traceback, not str(e): SystemErrors from C-level builtins
            # (os.kill, os.fspath, ...) put nothing useful in str(e) - the
            # cause lives in __cause__/__context__, which only the traceback
            # module walks (ops/docs/backlog/henry-loop-error-swallowed-traceback).
            print("henry: loop error:\n" + traceback.format_exc())
        time.sleep(_interval_s())


_started = False


def start_broker():
    """Copilot cell lifecycle hook (cells.py start=). Idempotent."""
    global _started
    if _started:
        return
    _started = True
    # The loop FIRST: a boot check that raises must never cost Henry his ears.
    # 2026-10-20 10:35 check_stale_ship_lock raised (os.kill SystemError) before
    # this line, the thread never started, and every escalation sat unread for
    # 41 minutes behind one line in the boot log.
    threading.Thread(target=_loop, daemon=True).start()
    try:
        check_stale_ship_lock()
    except Exception:
        print("henry: stale ship.lock check failed:\n" + traceback.format_exc())
