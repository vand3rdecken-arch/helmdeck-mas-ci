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
    from cells.copilot.chat import copilot
    from spine.agent import drivers
    argv = [copilot.CLAUDE, "-p", "--output-format", "json",
            "--permission-mode", perm or copilot.henry_pmode()]
    # HENRY'S OWN SETTINGS LAYER, not whatever cwd implies (2026-09-12). Until
    # now this spawn loaded the operator's personal ~/.claude (rtk hook, model
    # pin, memory hooks) PLUS the repo's project layer (the build-loop Stop
    # hook that once redirected two judgement turns into filling in
    # .loop/workorder.md - debt henry-broker-loop). With bypassPermissions the
    # copilot layer is also where the guard hook and the secret deny-list
    # live - without it, "more rights, fenced by a hook" would be all rights.
    from spine.registry import harness
    argv += harness.cli_args("board-copilot")
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
    raw = json.loads(stdout)
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
            # example: the onboarding demo card (accounts-boards-prd phase 3) -
            # inert, never dispatched, and Henry must never plan/reason about it.
            if t.get("archived") or t.get("lane") == "done" or t.get("example"):
                continue
            lines.append("card %s | %s/%s | ft=%s direct=%s turn_active=%s | %s" % (
                t["id"], t.get("lane"), t.get("status"), bool(t.get("fast_track")),
                bool(t.get("direct")), drivers.turn_active(t["id"]),
                (t.get("task") or "")[:60]))
    except Exception as e:
        lines.append("(board unreadable: %s)" % e)
    lines.append(_ship_lock_line())
    lines.append(_android_lock_line())
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
        from spine.ops.actionlog import read_timeline
        recs = read_timeline(t.get("run_dir") or "")[-n:]
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


def _decide(esc):
    """One judgement round. Returns True if the escalation was closed."""
    escalations.record_attempt(esc["id"])
    card_log = _card_log_tail(esc.get("card"))
    t = _find_track(esc.get("card"))
    policy = _judgement_policy(t)
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
          '{"action": "did|move|ship|rerun_deploy|steer|notify_owner|ignore",\n'
          ' "card": "karten-id oder leer",\n'
          ' "lane": "bei move: review|done",\n'
          ' "kind": "bei ship: none|ota|native",\n'
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
    if action == "did" and not privileged:
        # Defense in depth: even if the model tried anyway, this card's
        # escalation does not get closed via "did" - stays open for a
        # privileged human/owner to see, same shape as the GxP refusal
        # below (_execute's did/move gate).
        escalations.record_note(esc["id"],
            "Henry versuchte 'did' auf einer client-Karte ohne Haende - "
            "abgelehnt, bleibt offen")
        return False
    if not _execute(action, card, lane, text, esc, kind=kind, why=why):
        return False   # malformed verb - stays open for the next attempt
    escalations.record_decision(esc["id"], action, card=card, why=why)
    # Full text here too: _audit lands as a `note` in the card's ActionLog, and
    # the card chat RENDERS notes (card_transcript.tsx kind === "note") - so a
    # cut here is a mid-word chat message on the card surface as well.
    _audit(card, "HENRY entschieden (%s): %s - %s" % (
        esc["kind"], action,
        (text + (" | " + why if why else "")) if action == "did" else (why or text)))
    # REPORT BACK on every closing action (owner decree 2026-08-21: "if the work
    # is done he doesn't report back") - notify_owner/give-up already push; the
    # quiet successes (did/move/rerun/steer) were invisible until now.
    # NOT for `move` (owner report 2026-09-12, "Karte sendet push und Henry
    # auch"): a lane move is narrated by the lane pipeline itself (_say_card:
    # "auf Review geprueft" / "abgenommen und gemergt") and pushed by
    # card_event - the SAME event, already on the owner's screen. Henry's
    # `why` rides INSIDE that line (move_lane's `note`, see _execute) instead
    # of a second bubble + second push one second later. ONE event, ONE line.
    if action in ("did", "ship", "rerun_deploy", "steer"):
        # FULL text - the 180-char cut that used to live here was a PUSH budget
        # (owner report 2026-08-28: Henry's chat messages "end mid-word"). Since
        # 52033b6 this same string is also the board/card CHAT message, and a
        # chat has no length budget: _notify_owner truncates for FCM alone.
        _label = action + ((" " + kind) if action == "ship" and kind else "")
        _notify_owner("Henry (%s): %s%s - %s" % (
            esc["kind"], _label, (" -> " + lane) if action == "move" else "",
            text or why), None if action == "did" else _find_track(card))
    return True


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


def _execute(action, card, lane, text, esc, kind="", why=""):
    from spine.auth import gxp
    from spine.storage.trackstore import _load, _find
    t = _find(_load(), card) if card else None
    if action == "ignore":
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


def _notify_owner(text, t):
    """`text` arrives WHOLE. Exactly one consumer has a length budget - the FCM
    push - and it truncates here, at its own edge. The chat and the card audit
    get the full message: callers must never pre-truncate for the push, or the
    notification's limit silently becomes the chat's (owner report 2026-08-28,
    "Nachrichten enden mitten im Wort")."""
    # PRESENCE-GATED, like every other harness push (owner report 2026-09-12,
    # "viele Meldungen doppelt"): this was a raw push_fcm - the ONE sender in
    # the daemon that skipped notify's 3-tier presence policy, so a Henry
    # decision buzzed the phone while the owner was looking at that very chat,
    # right after the card's own (correctly suppressed) push. notify.escalate
    # is the PM's path for exactly this shape - "alert whose chat line has
    # already landed" - and its dedup is the caller's job: the chat line below
    # is written once per decision, so the push is too.
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
    followups = [e for e in open_escs if e["kind"] == _FOLLOWUP_KIND]
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
    check_stale_ship_lock()
    threading.Thread(target=_loop, daemon=True).start()
