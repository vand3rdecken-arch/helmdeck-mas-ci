# -*- coding: utf-8 -*-
"""Board copilot - steer HelmDeck by chatting. Each message runs one Claude
turn (resumable per user, so the conversation has memory) with a fresh board
snapshot; the model answers with JSON: a reply for the human plus zero or more
ACTIONS the daemon executes (file cards, move lanes, steer sessions, create
processes, accept steps). Text in, board changes out."""
import json, os, re, shutil, subprocess, threading, time, uuid

from daemon.paths import DAEMON_ROOT as ROOT, REPO_ROOT as _REPO_ROOT
SESS = os.path.join(ROOT, "copilot_sessions.json")
MODELS_F = os.path.join(ROOT, "copilot_models.json")
CHATLOG = os.path.join(ROOT, "copilot_log.json")
from cells.copilot.copilot_stats import _stats, _save_stats, _fold_stats, _plan_share
from cells.copilot.copilot_actions import _strip_actions_live, _parse_reply_actions
from spine.agent.agentcli import CLAUDE  # single source - see its module docstring
from spine.ops import ask  # the <helmdeck-ask> grammar's ONE owner (parse/strip)


# Appended ONLY on voice turns (routes_copilot.chat_post): a spoken answer has
# a hard time budget the written one does not. The base role already says
# "lead with the answer", but measured 2026-08-21: a voice question still got a
# minute-long reply full of options and counter-questions - unlistenable. This
# is a per-turn overlay, not a SYSTEM edit, so typed chat keeps its depth.
VOICE_STYLE = (
    "VOICE TURN - the owner is LISTENING, not reading, probably walking or "
    "driving. This is a CONVERSATION, not a report. HARD RULES for this reply:\n"
    "- Write EXACTLY what a person would SAY out loud: plain spoken sentences. "
    "ZERO markdown - no **bold**, no *stars*, no bullets, no headings, no "
    "backticks, no emoji. Every glyph you write will be read aloud literally.\n"
    "- At most TWO short sentences (~8 seconds spoken). Answer first, one "
    "detail if essential, stop. The owner interrupts long answers by hand - "
    "every sentence you add is one he may have to cut off.\n"
    "- NEVER speak lists, options, menus, card ids, branch names, file paths "
    "or numbers with more than two digits. Summarize instead ('three cards "
    "are waiting' - not which).\n"
    "- Do not end with a question unless you are genuinely BLOCKED. No "
    "'should I A or B' - pick the sensible default, act, say what you did.\n"
    "- Talk like a colleague across the room, in the owner's language: "
    "contractions, natural rhythm, no 'Status im Ueberblick', no preamble.\n"
    "- SIMPLE words only - everyday vocabulary a tired listener catches on "
    "the first pass. No jargon, no anglicisms in German ('bereitgestellt', "
    "nicht 'deployed'), no nested sentences. One thought per sentence.\n"
    "- ANSWER FROM WHAT YOU ALREADY HAVE (the board snapshot, the "
    "conversation). Do NOT read files or run commands for a spoken question - "
    "every tool call is silent seconds in the owner's ear. Use tools only "
    "when the owner explicitly asked you to DO something this turn.\n"
    "- Depth on request only: offer it in five words or less ('Details am "
    "Bildschirm.'), never inline.")


# -- persistent chat process (voice-speed, owner decree 2026-08-21) ----------
# MEASURED: a fresh `claude -p` spawn costs 8-12s BEFORE the model writes a
# token (node cold start + init) - the dominant share of a 12s voice turn.
# The cards already solved this (drivers._ClaudeSession, Paseo's model): keep
# the process alive on the stream-json port and a turn costs model time only.
# This is that port for the board chat, deliberately small: ONE process per
# user, carrying its live (model, permission mode) as its key. A turn that
# routes to a DIFFERENT model no longer respawns - it switches the running
# process on the control plane (_persist_switch, drivers.apply_opts parity),
# because with the composer's "auto" default the tier is re-picked from every
# message's text and respawn-on-change meant the process was warm in name only
# (see _persist_switch for the measured numbers). Two live processes on ONE
# session id would fork the conversation, hence never more than one per user.
_persist = {}            # user -> {"p": Popen, "key": (model, pmode)}
_persist_lock = threading.Lock()


_turn_locks = {}

# prewarm throttle - see prewarm(). Guards the FAILING case only (a spawn that
# dies immediately would otherwise re-warm on every /chat/history poll).
_prewarm_at = {}         # user -> last prewarm start (monotonic-ish wall clock)
_PREWARM_COOLDOWN = 120.0

# CACHE KEEPALIVE (owner incident 2026-09-02 14:44): a warm PROCESS is not a
# warm CACHE. The API-side prompt cache lives ~5 minutes; a 10-minute pause
# between turns expired it and the next turn re-read the whole session at
# full price/latency (~30s at 99k) despite the process sitting there warm.
# While the chat surface is open (prewarm rides every /chat/history poll), a
# hidden systemcheck ping refreshes the cache before it lapses - same hidden
# turn the spawn warmup already runs, same precedent. Bounded: only within
# _KEEPALIVE_MAX of the last REAL turn, so an abandoned open tab stops paying
# for warmth nobody is using.
_last_turn_at = {}       # skey -> wall clock of the last REAL turn
_last_touch_at = {}      # skey -> last real turn OR keepalive ping
_KEEPALIVE_AGE = 240.0   # refresh when the cache is older than this (TTL ~300s)
_KEEPALIVE_MAX = 2700.0  # stop 45min after the last real turn

# ACTION RESULTS pending for the NEXT turn (owner incident 2026-09-02 14:44):
# Henry's ```actions run daemon-side AFTER his reply, in a background thread,
# and their results went ONLY to the owner's display log - Henry never saw
# them. A failed dispatch ("direct_task: not a git repo") was on the owner's
# screen while Henry's own transcript still ended with his "Fix laeuft an"
# claim, so the next turn he reported the fix as running and, asked how he
# checked, admitted he hadn't. Same blind spot the WORKER path already fixed
# in sessions._pending_context ("runs OUTSIDE the agent session - prepend the
# actual report so the worker isn't blind") - this is that wheel, not a new
# one. In-memory: a daemon restart loses at most one turn's pending results.
_pending_actions = {}    # skey -> [result strings], folded into the next turn
_pending_lock = threading.Lock()


def _turn_lock(user):
    """One turn at a time per user on the shared warm process - a prewarm
    draining events while a real turn writes would interleave two pumps."""
    with _persist_lock:
        return _turn_locks.setdefault(user, threading.Lock())


def prewarm(user, spoken=True):
    """Fire-and-forget: spawn the user's warm chat process AND run a hidden
    warmup turn on it. Called when voice mode OPENS (the greeting fetch) and
    when the board chat is OPENED (the /chat/history fetch), so the two slow
    parts - node boot and the prompt-cache prefill of a big resumed session
    (128k measured 2026-08-21 = the '20s first turn') - happen while the owner
    is still hearing the greeting / reading the transcript and typing, instead
    of on the clock of their first question. The warmup lands in the session
    history but never in the chat UI (copilot_log carries only real turns).

    Cheap to call: a process that is already warm costs one poll() and returns.
    The cooldown below only bounds the case where warming genuinely FAILS - a
    process that dies on every spawn would otherwise be re-spawned (and pay a
    real warmup turn) on every single /chat/history poll, which the app falls
    back to every 8s when the event stream is down (data/stream.ts).

    `spoken` picks WHICH tier to warm. It matters because the prompt cache the
    warmup turn fills is per-model: warming haiku buys a typed sonnet turn only
    the node boot, not the prefill. Voice pins the fast voice_model, so it says
    spoken=True; the board chat routes "auto" over an empty message - i.e. the
    everyday typed tier - so it says spoken=False. Guessing wrong is no longer
    expensive either way (_persist_switch adopts the real turn's model on the
    control plane instead of respawning), it just warms less."""
    now = time.time()
    with _persist_lock:
        if now - _prewarm_at.get(user, 0.0) < _PREWARM_COOLDOWN:
            return
        _prewarm_at[user] = now

    def _go():
        try:
            from spine.agent import drivers, turnopts
            from spine.storage import events
            from spine.registry import harness
            if not drivers.argv_form_safe(CLAUDE):
                return
            model = ""
            if spoken:
                vm = events.settings().get("voice_model")
                model = (vm if vm is not None else "haiku") or ""
            # SAME ctx signal chat() uses: ctx_tokens is a routing INPUT (a
            # model whose window cannot hold the session gets lifted), so a
            # prewarm that read it differently from the real turn would warm a
            # tier the turn then has to switch away from. Same STICKY tier as
            # chat() too: a typed turn resolves explicit > sticky > auto, so a
            # prewarm that ignored the sticky pick would warm a tier the very
            # next real turn switches away from.
            cli_model, _ = turnopts.resolve_model(
                model or _model_prefs().get(_skey(user)) or "auto", "", False,
                signals={"ctx_tokens": (_stats().get(user) or {}).get("ctx_tokens")})
            base = harness.brief("board-copilot")
            lock = _turn_lock(user)
            if not lock.acquire(blocking=False):
                return                      # a real turn is running - already warm
            try:
                # A live process is already the whole point - leave it exactly
                # as the last real turn left it. Going through _persist_get
                # here would switch its model to this GUESS, only for the next
                # real turn to switch it straight back: two control ops to end
                # up where we started. But a live process is NOT a live cache
                # (5-min API TTL) - when the cache is about to lapse and the
                # owner was recently active, refresh it with the same hidden
                # systemcheck the spawn warmup runs. See _KEEPALIVE_AGE above.
                bkey = _skey(user)
                p = None
                with _persist_lock:
                    ent = _persist.get(bkey)
                    if ent and ent["p"].poll() is None:
                        _now = time.time()
                        if (_now - _last_touch_at.get(bkey, 0.0) > _KEEPALIVE_AGE
                                and _now - _last_turn_at.get(bkey, 0.0) < _KEEPALIVE_MAX):
                            p = ent["p"]     # warm but cooling - ping below
                        else:
                            return           # warm AND cached (or idle too long)
                if p is None:
                    # BOARD key only: the owner's decree is that just the Henry
                    # board chat is kept warm. A card conversation pays one spawn
                    # when it is opened and stays warm for the rest of it.
                    p, fresh = _persist_get(bkey, cli_model,
                                            _sessions().get(bkey), base)
                    if not fresh:
                        return              # already warm AND cached
                p.stdin.write(json.dumps({"type": "user", "message": {"role": "user",
                              "content": "(Systemcheck, nicht vorlesen - antworte nur: ok)"}}) + "\n")
                p.stdin.flush()
                t0 = time.time()
                for line in p.stdout:
                    if time.time() - t0 > 120:
                        break
                    try:
                        if json.loads(line.strip() or "{}").get("type") == "result":
                            break
                    except ValueError:
                        continue
                _last_touch_at[bkey] = time.time()
            finally:
                lock.release()
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


def _persist_drop(skey):
    """Kill + forget ONE conversation's warm process (`skey` = _skey(user, card)).
    Next turn respawns with --resume, so nothing is lost but the warmth."""
    with _persist_lock:
        ent = _persist.pop(skey, None)
    if ent:
        try:
            ent["p"].kill()
        except Exception:
            pass


def _control(p, subtype, timeout=3.0, **fields):
    """Fire ONE control_request at the warm chat process and WAIT for its
    control_response. True only on a proven `success`
    (drivers._ClaudeSession._control parity, same 3s bound as Paseo's
    awaitWithTimeout - and the same wire shape: the id echoes in
    ev["response"]["request_id"]).

    Reading stdout here is safe because EVERY caller holds the user's turn lock
    (chat() and prewarm() both acquire it before _persist_get), so between
    turns nobody else pumps this pipe. And a timeout is not left dangling: the
    caller kills the process on False, so this reader hits EOF and can never
    steal the next turn's events.
    """
    req_id = "cp-" + uuid.uuid4().hex[:12]
    try:
        p.stdin.write(json.dumps({"type": "control_request", "request_id": req_id,
                                  "request": dict({"subtype": subtype}, **fields)}) + "\n")
        p.stdin.flush()
    except Exception:
        return False
    done, box = threading.Event(), {}

    def _read():
        try:
            for line in p.stdout:
                try:
                    ev = json.loads(line.strip() or "{}")
                except ValueError:
                    continue
                resp = ev.get("response") or {}
                if ev.get("type") == "control_response" and resp.get("request_id") == req_id:
                    box["resp"] = resp
                    break
        except Exception:
            pass
        done.set()
    threading.Thread(target=_read, daemon=True).start()
    if not done.wait(timeout):
        return False
    return (box.get("resp") or {}).get("subtype") == "success"


def _persist_switch(ent, key):
    """Adopt a model / permission-mode change on the LIVE process via the
    control plane instead of respawning it (drivers.apply_opts parity - the
    last open item on the persistent-session card).

    THIS is what makes the board chat actually stay warm. The composer defaults
    to "auto" (surfaces/app/src/ui/card_composer.tsx), so turnopts.pick_model
    re-picks the tier from EVERY message's text: "danke" routes haiku, a plain
    question sonnet, anything matching _HARD ("debug", "analysiere",
    "refactor", "root cause") opus - and a voice turn pins haiku on top of
    that. Keyed respawn-on-change therefore threw the warm process away on an
    ordinary typed conversation, and the next turn paid node boot (8-12s) PLUS
    a full --resume prefill of a months-long board session (~20s measured at
    128k) - the "warm process" was only ever warm for a run of messages that
    happened to route to the same tier.

    The key advances ONLY on the runtime's own confirmation (no monkey patches:
    a control op we did not see succeed is not evidence of anything). Any
    failure returns False and the caller falls back to today's drop+respawn, so
    the worst case is exactly the behaviour we had before.
    """
    old_model, old_mode = ent["key"]
    new_model, new_mode = key
    p = ent["p"]
    if new_model != old_model and not _control(p, "set_model", model=(new_model or "default")):
        return False
    if new_mode != old_mode and not _control(p, "set_permission_mode", mode=new_mode):
        return False
    ent["key"] = key
    return True


def _persist_get(skey, cli_model, sid, system):
    """(proc, fresh) for ONE conversation (`skey` = _skey(user, card)). Reuse
    the warm process - switching its model/mode on the control plane when the
    turn routed differently (_persist_switch) - and only spawn when there is
    nothing live to reuse. The system brief rides the SPAWN (constant across
    turns); per-turn overlays travel inside the turn text.

    Keyed per conversation since 2026-09-02: a card chat must not resume the
    board session (and vice versa), so each key owns its own process AND its
    own --resume id. Only the BOARD key is prewarmed (owner's call) - a card
    conversation pays one spawn on open and stays warm for the rest of it."""
    from spine.agent import drivers
    from spine.registry import harness
    key = (cli_model or "", henry_pmode())
    live = None
    with _persist_lock:
        ent = _persist.get(skey)
        if ent and ent["p"].poll() is None:
            if ent["key"] == key:
                return ent["p"], False
            live = ent
    if live is not None and _persist_switch(live, key):
        # cancel() can drop the process while the switch was in flight - only
        # hand back a handle the registry still owns, never a killed one.
        with _persist_lock:
            if _persist.get(skey) is live and live["p"].poll() is None:
                return live["p"], False
    _persist_drop(skey)
    argv = [CLAUDE, "-p", "--output-format", "stream-json", "--input-format", "stream-json",
            "--include-partial-messages", "--verbose", "--permission-mode", henry_pmode()]
    if cli_model:
        argv += ["--model", cli_model]
    if sid:
        argv += ["--resume", sid]
    argv += ["--append-system-prompt", system]
    argv += harness.cli_args("board-copilot")
    from spine.agent.drivers import _cmd_line
    p = subprocess.Popen(_cmd_line(argv), cwd=ROOT, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, encoding="utf-8", errors="replace", bufsize=1)
    with _persist_lock:
        _persist[skey] = {"p": p, "key": key}
    return p, True


def henry_pmode():
    """Permission mode for every Henry surface - board chat AND the escalation
    broker (ONE knob, settings `henry_permission_mode`). Owner decree
    2026-08-21: Henry runs in a WORKING mode, not plan - "should be able to do
    stuff directly instead of waiting". Plan mode had him proposing cards for
    fixes he could apply in the same breath, and left the broker judging a
    merge conflict it wasn't allowed to touch. NOTE the cwd stays DAEMON_ROOT
    for chat turns (sessions resume per project dir - moving cwd orphans every
    existing PM conversation), so Henry's hands use absolute paths."""
    from spine.storage import events
    return (events.settings().get("henry_permission_mode") or "").strip() or "acceptEdits"

# HENRY'S ROLE IS DATA, IN EXACTLY ONE PLACE: ops/harness/agents/board-copilot.md
# (owner-editable, versioned via /harness, shipped with every install - the
# desktop bundle carries ops/harness as an extraResource). The 17 KB copy that
# used to live here rotted ~1.9k chars behind the file exactly as harness.py's
# _DEFAULTS comment predicted a copy would; resolution is harness.brief(
# "board-copilot") whose floor is a SHORT degraded-mode stub in harness._DEFAULTS
# (never-break-a-spawn), loud in harness.errors() instead of silently stale.

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


def _model_prefs():
    try:
        with open(MODELS_F, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_model_pref(skey, mid):
    """Remember which model THIS conversation runs on (skey -> concrete id).

    Why (owner report 2026-09-02): the composer chip said sonnet-5, yet the
    board session had been served by FOUR models. The chip only rides requests
    from the one app surface that persists it - watch and glasses turns carry
    no model at all and re-rolled Auto from each message's wording, and voice
    turns pin the fast voice_model by decree. Prompt caches are PER MODEL, so
    every tier flip re-read the whole session at full price (measured: one
    $16.65 turn at 405k in). The conversation's model is CONVERSATION state,
    so it lives server-side, keyed like the session id itself."""
    d = _model_prefs()
    if d.get(skey) == mid:
        return
    d[skey] = mid
    tmp = MODELS_F + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, MODELS_F)
    except OSError:
        pass                       # a lost pref re-learns next turn; never break the turn


def _skey(user, card=None):
    """The identity of ONE Henry conversation - what a session id and a warm
    process are keyed by.

    Board chat keeps the BARE user key, so the owner's existing board session
    (and its entry in daemon/copilot_sessions.json) survives this change
    untouched - no migration, no lost history.

    A card-scoped Henry chat gets its OWN key, hence its own session. Before
    this, every card conversation was appended to the one eternal board session
    (measured 2026-09-02: 431,257 tokens over 200 turns, re-processed on every
    single turn). Paseo's agents are per-task for exactly this reason -
    packages/server/.../agent-manager.ts mints a fresh agent per task and calls
    deleteAgentState on the id first. A card session is bounded by the card.

    NOT the worker's session: that one has exactly one owner
    (drivers._ClaudeSession) appending to its transcript, and a second writer
    would corrupt the card's own record. Henry READS the card's timeline
    instead (_card_context) - the shared one-inbox record that already carries
    every steer."""
    return user if not card else "%s\x00card:%s" % (user, card)


def _card_context(card_id, limit=40):
    """What a card-scoped Henry needs to know about ITS card, read from the
    card's own timeline - the one-inbox record that already interleaves the
    worker's steps, the owner's steers and Henry's notes (see say(card=...) and
    routes_copilot's reply_to_card). This is the "how and what was steered"
    history, not a re-derivation of it.

    Empty string when the card has no readable run_dir - a card-scoped chat
    must never fail because its timeline is missing."""
    ct = _find_card(card_id)
    if not ct or isinstance(ct, list):
        return ""
    head = ("THIS CARD: id=%s | repo=%s | branch=%s | lane=%s | status=%s | mode=%s\n"
            "TASK: %s" % (
                ct.get("id"), os.path.basename((ct.get("repo") or "").replace("\\", "/").rstrip("/")) or "?",
                ct.get("branch"), ct.get("lane"), ct.get("status"), ct.get("mode") or "-",
                (ct.get("task") or "").strip()))
    run_dir = ct.get("run_dir")
    if not run_dir:
        return head
    try:
        from spine.agent import timeline_store
        steps = timeline_store.read(run_dir, limit=limit)
    except Exception:
        return head
    lines = []
    for s in steps:
        who = s.get("byKind") or s.get("role") or "?"
        txt = (s.get("text") or s.get("title") or "").replace("\n", " ").strip()
        if not txt:
            continue
        # A steer is the interesting event - it is what the owner told the
        # worker to do, and the reason this history is worth carrying at all.
        lines.append("- [%s] %s: %s" % (s.get("ts") or "", who, txt[:220]))
    if not lines:
        return head
    return head + "\n\nCARD TIMELINE (most recent last - worker steps, your own " \
                  "notes and every steer the owner sent):\n" + "\n".join(lines[-limit:])


def _snapshot(full=False):
    """The board as text. `full=False` (the default, what a chat turn injects)
    carries only the LIVE board; `full=True` adds finished/archived cards and
    the full debt text.

    Why the split, measured 2026-09-02: this block used to ride COMPLETE inside
    every user turn - 83,488 chars (~23k tokens) of uncached input the model
    re-read before answering anything, which is the bulk of the ~21s warm-turn
    latency (Paseo, by contrast, sends ONLY the user's text and keeps context in
    the cached system prompt + tools - packages/server/.../claude/agent.ts:3386).
    Of that payload 53,871 chars were FINISHED cards and 14,427 were debt prose:
    history, not live state. History is now fetched on demand (Henry runs
    ops/tools/board_state.py, which calls this with full=True) instead of being
    pushed into every turn."""
    from cells.engineer import sessions
    from cells.process import processes
    from spine.storage import events
    m = events.metrics(sessions.list_tracks())
    pol = events.settings().get("policy") or {}
    lines = ["POLICY: " + json.dumps(pol)]
    lines += ["CAPACITY: WIP %d/%d, headroom %d cards" % (
        m["capacity"]["wip"], m["capacity"]["wip_limit"], m["capacity"]["headroom"])]
    # Cards span MULTIPLE repos (projects). The repo is shown so a question about
    # one project (e.g. "what's left for HelmDeck") is scoped to THAT repo only -
    # without it the model mixed Seekingalpha/immo-deal-scanner cards into HelmDeck.
    lines.append("CARDS (each belongs to ONE repo; a question about a specific "
                 "project/repo must include ONLY that repo's cards)%s:"
                 % ("" if full else " - LIVE ONLY, see the note at the end for finished work"))
    hidden_done = hidden_arch = 0
    for t in sessions.list_tracks():
        # example: the onboarding demo card (accounts-boards-prd phase 3) is
        # never real work - excluded so the PM/board-copilot never plans
        # around it or reports it as an open card.
        if t.get("example"):
            continue
        # Finished + archived cards are HISTORY: 53,871 of the 57,993 chars this
        # section used to cost, re-read on every single turn to answer questions
        # that were almost never about them. Counted (never silently dropped -
        # the count is what tells Henry there IS history to go fetch) and served
        # in full by ops/tools/board_state.py.
        if not full:
            if t.get("archived"):
                hidden_arch += 1
                continue
            if t.get("lane") == "done":
                hidden_done += 1
                continue
        repo = os.path.basename((t.get("repo") or "").replace("\\", "/").rstrip("/")) or "?"
        # needs_you carries its open question; a FINISHED card carries its RESULT
        # (outcome, persisted at accept). Without the second half, an owner
        # decision answered in a card's final reply resurfaced as "open" in the
        # PM plan triage - the planner reads THIS snapshot. Only the STORED
        # outcome is read: legacy pre-outcome cards were stamped once by
        # sessions.backfill_outcomes (daemon start, agent-reviewed values) -
        # never re-derived per read, so a heuristic change can't silently
        # rewrite what a finished card is remembered for.
        if t.get("status") == "needs_you":
            tail = " last_reply=" + t.get("last_reply", "")[:150].replace("\n", " ")
        elif t.get("lane") == "done":
            o = t.get("outcome") or ""
            tail = (" outcome=" + o[:150].replace("\n", " ")) if o else ""
        else:
            tail = ""
        # ARCHIVED is stated, never silently omitted. The board hides archived
        # cards (surfaces/app/src/ui/board.tsx `shown`), this snapshot lists
        # every track - so an archived card reported here as if it were on the
        # board sent the owner looking for a card no board view could show.
        # Telling him it is archived is what lets him ask for it back.
        arch = " ARCHIVED" if t.get("archived") else ""
        lines.append("- id=%s repo=%s branch=%s lane=%s status=%s%s prio=%s due=%s mode=%s ai=$%.2f task=%s%s" % (
            t["id"], repo, t["branch"], t.get("lane"), t.get("status"), arch, t.get("priority", "-"),
            t.get("due") or "-", t.get("mode") or "-", t.get("ai_cost", 0),
            t["task"][:90].replace("\n", " "), tail))
    try:
        from cells.connectors import connectors as _c
        cs = _c.list_connectors()
        if cs:
            lines.append("INSTALLED CONNECTORS: " + ", ".join(
                "%s (%s)" % (c["name"], c["description"][:40]) for c in cs))
    except Exception:
        pass
    try:
        from spine.registry import debt as _d
        open_items = [d for d in _d.list_debt() if d["status"] != "paid"]
        if open_items:
            if full:
                lines.append("STRUCTURAL DEBT (open, ordered): " + "; ".join(
                    "%s - %s (bites when: %s)" % (d["id"], d["title"], d["trigger"])
                    for d in open_items))
            else:
                # ids + titles only: the full 'bites when' prose was 14,427 chars
                # of every turn. The ids are enough for Henry to know what exists
                # and to look one up when a question is actually about it.
                lines.append("STRUCTURAL DEBT (%d open): " % len(open_items) + "; ".join(
                    "%s - %s" % (d["id"], d["title"]) for d in open_items))
    except Exception:
        pass
    lines.append("PROCESSES:")
    for p in processes.list_processes():
        lines.append("- id=%s status=%s client=%s due=%s request=%s" % (
            p["id"], p["status"], p.get("client") or "-", p.get("due") or "-", p["request"][:80]))
        for i, s in enumerate(p.get("steps", [])):
            lines.append("    step[%d] state=%s mode=%s title=%s" % (
                i, s.get("state", "proposed"), s["mode"], s["title"][:70]))
    if not full and (hidden_done or hidden_arch):
        # NOT a silent cap: Henry is told exactly what is missing and how to get
        # it, so "I don't know" is never the honest answer to a history question.
        lines.append(
            "\nNOT SHOWN ABOVE: %d finished and %d archived card(s), plus the full "
            "'bites when' text of each debt item. They are omitted because they are "
            "history and cost ~19k tokens on every turn. When a question is about "
            "finished/archived work, a past outcome, or a debt item's detail, RUN "
            "THIS FIRST and answer from its output:\n"
            "    py -3.12 %s --full\n"
            "(cwd does not matter - the path is absolute.)"
            % (hidden_done, hidden_arch,
               os.path.join(_REPO_ROOT, "ops", "tools", "board_state.py")))
    return "\n".join(lines)

# -- action layer: extracted to copilot_actions.py (god-file breakup). ----
# Re-imported here so every existing copilot.<name> caller stays unchanged.
from cells.copilot.copilot_actions import (
    _find_card, ALLOWED_CONFIG, _card_hint, _denied, _run_action)

def _branchless_slug_fix():
    pass  # new_track slugs empty branch to 'track'; acceptable

def _log():
    try:
        with open(CHATLOG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def _append_log(user, entries):
    """THE one writer of the chat log - and therefore the one place a DATE is
    stamped.

    Owner, 2026-08-29, with a screenshot of the watch's SMS app: he wants date
    separators between days. `ts` has always been "%H:%M" alone, which cannot
    tell a message sent today from one sent three weeks ago, so a separator was
    impossible to draw honestly.

    Stamped HERE rather than at the six-plus call sites that build entries (the
    chat's you/bot pair, the rotate note, the compaction note, _say, the refusal
    note): a per-site copy is exactly the drift CLAUDE.md's one-owner rule
    exists to prevent, and whichever site got forgotten would emit messages that
    silently fall outside every separator.

    FORWARD-ONLY, deliberately. Entries already on disk carry no date and get
    none - one invented for them would be a guess printed as a fact. A client
    draws separators from here on and simply omits them above, which is the
    honest rendering of "this was never recorded".
    """
    stamped = []
    for e in entries:
        if isinstance(e, dict) and not e.get("date"):
            e = dict(e)          # never mutate the caller's entry
            e["date"] = time.strftime("%Y-%m-%d")
        stamped.append(e)
    entries = stamped
    d = _log()
    d.setdefault(user, []).extend(entries)
    d[user] = d[user][-80:]
    tmp = CHATLOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, CHATLOG)
    # THE EVENT, announced from the one place that can honestly announce it.
    #
    # Every surface reading this transcript used to discover a new line on a
    # TIMER (phone 8s, watch 15s) because nothing here ever said "it moved" -
    # /stream/wait only ever watched db._version, and the chat log is a file, not
    # a table. This is the missing half: the single writer of the log is also the
    # single publisher of its cursor, so a waiting client is woken by the write
    # itself rather than by re-reading the file on a clock.
    #
    # AFTER os.replace, never before: the rename is what makes the new line
    # visible to a reader, so a cursor bumped earlier could wake a client that
    # then reads the OLD file and concludes nothing changed - a lost event that
    # would look exactly like the delay this replaces.
    #
    # Best-effort and non-fatal, the same contract as every other notify/emit
    # call site here: the durable state (the file) is already written, and a
    # storage hiccup must never turn a persisted turn into a failed one. The
    # clients' reconnect path is the backstop.
    try:
        from spine.storage import db
        db.bump_chat()
    except Exception as _be:                                    # noqa: BLE001
        print("copilot: chat cursor bump failed -", str(_be)[:200])

_autocompact_supported = None    # None=unprobed, True/False learned from first /compact

# Replies that are etiquette, not answers - the exact strings (lowercased,
# terminal punctuation stripped) the model uses to wave off system turns.
# Deliberately narrow: "ok" is NOT here, it is the legitimate answer to the
# harness's own systemcheck turns.
_FILLER_REPLIES = {"no response requested"}

_compacting = set()              # users with a background compaction in flight

# Henry's durable memory. NOT the CLI's shared auto-memory directory: that one
# is derived by the CLI from a project identity which measurably is NOT "this
# cwd" (harness._memory_isolation says so, and every card worktree we measured
# shared ONE directory keyed off something else). Guessing that derivation is
# the unverified reconstruction CLAUDE.md forbids - and cards are DENIED writes
# there on purpose (debt: card-shares-the-operators-auto-memory).
#
# So Henry gets the shape Anthropic documents for exactly this and nothing more
# clever: a plain directory of .md files plus an index that rides in the brief
# (progressive disclosure - the index is always in context, a file is read only
# when it's relevant). Machine-local runtime data, so it lives under daemon/
# like every other runtime store.
MEMORY_DIR = os.path.join(ROOT, "henry_memory")
MEMORY_INDEX = os.path.join(MEMORY_DIR, "MEMORY.md")


def _memory_digest():
    """The memory INDEX for the turn - never the notes themselves.

    That split is the whole mechanism: the index is small and always present, a
    note is opened only when it turns out to matter. Putting the notes inline
    would re-grow exactly the context the compaction just freed."""
    try:
        with open(MEMORY_INDEX, encoding="utf-8") as f:
            body = f.read().strip()
    except OSError:
        return ""
    if not body:
        return ""
    return ("\n\nDEIN GEDAECHTNIS (Index; die Dateien liegen in %s - lies eine, "
            "wenn sie zur Frage passt, und schreib dazu, wenn du etwas "
            "Dauerhaftes lernst):\n%s" % (MEMORY_DIR, body[:4000]))


def _compact_mark(st):
    """The context level at which Henry must compact - the LOWER of two
    INDEPENDENT reasons, because they protect different things:

      overflow  0.8 * window - the session must not hit the wall.
      stay-fast the biggest context the FAST model can still carry, so a
                trivial ack or a spoken turn can still be answered by it.

    Only the first existed, and it is the wrong guard for the symptom the owner
    actually feels. Measured 2026-08-30: Henry sat at 615,889 of a 1M window =
    61.6%, comfortably under the 800k overflow mark and therefore never
    compacted - while having been too big for Haiku's 200k window since roughly
    168k, i.e. since 17% fill. The overflow guard fires at 80%; the line that
    costs speed and plan-share is crossed at 17%. Nothing watched it, so every
    board turn - typed or spoken - silently ran on the big model with a 615k
    prefill re-read each time (83M input tokens over 98 turns).

    Returns (mark, why). `why` is carried into the chat note so a compaction
    never looks arbitrary to the owner."""
    from spine.agent import turnopts
    from spine.storage import events
    from cells.engineer import sessions
    window = max(int(st.get("ctx_window") or 0), sessions._CTX_WINDOW)
    overflow = int(0.8 * window)
    try:
        vm = events.settings().get("voice_model")
        fast_id, _ = turnopts.resolve_model((vm if vm is not None else "haiku") or "haiku", "")
        fw = turnopts.model_window(fast_id)
    except Exception:                                            # noqa: BLE001
        fw = None
    if fw and fw - turnopts.CTX_HEADROOM < overflow:
        return fw - turnopts.CTX_HEADROOM, "stay-fast"
    return overflow, "overflow"


def _schedule_compact(user):
    """Compact in the BACKGROUND, off the request thread. The
    huggingface/speech-to-speech lesson (chat.py's single-flight compaction
    worker, read 2026-08-23): history compaction is maintenance and must never
    be a pause in the conversation. Before this, _maybe_compact ran inside the
    POST /chat handler - at the context brim it held the reply hostage exactly
    when the owner was mid-conversation (measured: two voice questions
    swallowed around the 05:47 auto-compact). Single-flight per user; the
    per-user turn lock serializes with real turns so the external /compact
    cannot fork a session a concurrent question is advancing."""
    try:
        from cells.engineer import sessions
        st = _stats().get(user) or {}
        ctx = st.get("ctx_tokens") or 0
        mark, _why = _compact_mark(st)
    except Exception:
        return
    # at most ONE compaction per conversation turn. Without this the stay-fast
    # mark can sit just above what a compaction actually achieves, and the
    # background worker would re-fire on every reply forever. _maybe_compact's
    # own "did it really shrink" check catches a CLI that ignores /compact; this
    # catches a compaction that works but doesn't reach the mark.
    if ctx < mark or user in _compacting:
        return
    if int(st.get("turns") or 0) <= int(st.get("compacted_at_turn") or -1):
        return
    _compacting.add(user)

    def _go():
        try:
            lk = _turn_lock(user)
            lk.acquire()
            try:
                note = _maybe_compact(user)
            finally:
                lk.release()
            if note:
                _append_log(user, [{"cls": "error", "text": note,
                                    "ts": time.strftime("%H:%M")}])
        except Exception:
            pass                 # best-effort, same contract as _maybe_compact
        finally:
            _compacting.discard(user)

    threading.Thread(target=_go, daemon=True).start()


_MEMORY_SEED = """# Henrys Gedaechtnis

Index. Eine Zeile pro Notiz - `- [Titel](datei.md) - Aufhaenger`.
Der Index faehrt bei jedem Turn im Brief mit; die Datei selbst liest Henry nur,
wenn sie zur Frage passt.
"""

_SAVE_PROMPT = (
    "SYSTEM-WARTUNG, keine Owner-Nachricht - antworte NICHT im Chat-Ton und "
    "stelle keine Rueckfrage.\n\n"
    "Dein Verlauf wird gleich verdichtet. Was jetzt nicht auf der Platte steht, "
    "steht dir danach nur noch als Zusammenfassung zur Verfuegung.\n\n"
    "Schreib die dauerhaften Fakten aus diesem Gespraech nach %s:\n"
    "- eine Datei pro Sache, `<kurz-kebab-titel>.md`, Einzeiler-Zusammenfassung "
    "ganz oben, dann der Fakt und WARUM er zaehlt.\n"
    "- danach eine Zeile pro Datei in MEMORY.md nachtragen.\n"
    "- dauerhaft = Owner-Entscheidungen, Vorlieben, laufende Vorhaben, "
    "Zusagen, offene Fragen, harte Fakten ueber Repos und Geraete.\n"
    "- NICHT speichern, was Code, Karten oder Git-Historie ohnehin festhalten, "
    "und nichts, was nur fuer den letzten Turn galt.\n"
    "- gibt es die Notiz schon, aktualisiere sie statt eine zweite anzulegen.\n"
    "- Geheimnisse (Token, Passwoerter) gehoeren NICHT hinein.\n\n"
    "Antworte am Ende mit genau einer Zeile: was du gespeichert hast."
)


def _save_memory(user, sid):
    """Give Henry ONE turn to persist what matters BEFORE the verdichtung.

    This is the owner's decree of 2026-08-30 ("kompaktieren und ins Speicher"),
    and it is the documented shape rather than an invention: a plain directory
    of .md files plus an index, exactly what Anthropic's own guidance prescribes
    when an agent needs to carry knowledge across a context boundary. Henry
    writes it himself with the hands he already has (henry_pmode is acceptEdits)
    - nothing here parses his conversation or decides for him what mattered.

    Runs on the SAME session id, so what he writes is informed by the full,
    not-yet-compacted history. Best-effort by the same contract as the
    compaction it precedes: a failed save must never block the compaction, and a
    failed compaction must never break the chat."""
    from spine.agent import drivers
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        if not os.path.exists(MEMORY_INDEX):
            with open(MEMORY_INDEX, "w", encoding="utf-8") as f:
                f.write(_MEMORY_SEED)
    except OSError:
        return False
    # acceptEdits, NOT the plan mode the /compact spawn uses: a turn told to
    # write files must be allowed to write files.
    argv = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
            "--permission-mode", henry_pmode(), "--resume", sid]
    try:
        p = subprocess.Popen(drivers._cmd_line(argv), cwd=ROOT, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, encoding="utf-8", errors="replace")
        p.stdin.write(_SAVE_PROMPT % MEMORY_DIR); p.stdin.close()
        for _line in p.stdout:                    # drain: an undrained pipe deadlocks
            pass
        p.wait(timeout=20)
    except Exception:                                            # noqa: BLE001
        return False
    return True


def _maybe_compact(user):
    """Copilot counterpart of sessions._maybe_compact (card parity, re-enabled
    2026-08-14): compact the board-chat session in place once it crosses the
    high-water mark, so a long-running PM conversation never dead-ends or
    silently overflows into a fresh session. Self-verifying (probes /compact
    once, learns True/False from whether the context actually shrank) and
    best-effort - never breaks/blocks the turn that already returned to the
    user. Returns a note to surface in the chat log, or None."""
    global _autocompact_supported
    if _autocompact_supported is False:
        return None
    from cells.engineer import sessions
    from spine.agent import drivers
    st = _stats().get(user) or {}
    ctx = st.get("ctx_tokens") or 0
    sess = _sessions()
    sid = sess.get(_skey(user))          # BOARD session - the long-lived one
    # scale the mark with the DERIVED window (sessions._maybe_compact parity):
    # a fixed 160k made a 1M-tier PM session probe /compact at ~16% real fill.
    window = max(st.get("ctx_window") or 0, sessions._CTX_WINDOW)
    mark, why = _compact_mark(st)
    if ctx < mark or not sid:
        return None
    # the external /compact turn resumes the SAME session id - a live warm
    # process on it would fork the conversation. Drop it first; the next chat
    # turn respawns on the compacted tip. BOARD key: proactive compaction
    # guards the long-lived board session; card sessions are bounded by their
    # card and are not compacted (see debt henry-card-session-uncompacted).
    _persist_drop(_skey(user))
    # ...and BEFORE the history is verdichtet, let Henry put what matters on
    # disk. Order is the whole point: after /compact he only has the summary.
    saved = _save_memory(user, sid)
    pct = min(100, round(ctx / window * 100))
    argv = [CLAUDE, "-p", "--output-format", "stream-json", "--include-partial-messages",
            "--verbose", "--permission-mode", "plan", "--resume", sid]
    cmd = drivers._cmd_line(argv)
    result, new_sid, after_usage = {}, sid, {}
    try:
        p = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
        p.stdin.write("/compact"); p.stdin.close()
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            typ = ev.get("type")
            if typ == "system" and ev.get("session_id"):
                new_sid = ev["session_id"]
            elif typ == "assistant":
                mu = (ev.get("message") or {}).get("usage")
                if isinstance(mu, dict) and mu:
                    after_usage = mu
            elif typ == "result":
                result = ev
        try:
            p.wait(timeout=8)
        except Exception:
            pass
    except Exception:
        return None   # best-effort - never let compaction break the chat
    sid_final = result.get("session_id") or new_sid
    all_st = _stats()
    m = all_st.setdefault(user, {})
    if sid_final and sid_final != sid:
        chain = [s for s in (m.get("session_chain") or []) if s != sid]
        chain.append(sid)
        m["session_chain"] = chain[-6:]         # bounded - last 6 prior sessions
        sess[_skey(user)] = sid_final
        _save_sessions(sess)
    # measured economics: the compact turn is billed too, but NOT counted as a
    # conversation turn (card parity: sessions._record_econ, not _record_turn).
    from spine.storage import events
    u = result.get("usage") or {}
    models = list((result.get("modelUsage") or {}).keys())
    m["cost"] = round(float(m.get("cost") or 0.0)
                      + events.price_turn(models, u, result.get("total_cost_usd")), 6)
    m["tokens_in"] = int(m.get("tokens_in") or 0) + u.get("input_tokens", 0) \
        + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    m["tokens_out"] = int(m.get("tokens_out") or 0) + u.get("output_tokens", 0)
    after = (after_usage.get("input_tokens", 0) + after_usage.get("cache_creation_input_tokens", 0)
             + after_usage.get("cache_read_input_tokens", 0)) or ctx
    m["ctx_tokens"] = after
    # one compaction per turn (see _schedule_compact): a stay-fast mark can sit
    # below what /compact actually reaches, and that must not become a loop.
    m["compacted_at_turn"] = int(st.get("turns") or 0)
    _save_stats(all_st)
    if after <= ctx * 0.75:                     # a real compaction frees a big chunk
        _autocompact_supported = True
        return ("AUTO-COMPACT (%s): Kontext war bei %d%% (~%dk) - %s, Verlauf "
                "verdichtet, jetzt ~%dk. Es geht ohne Unterbrechung weiter."
                % (why, pct, round(ctx / 1000),
                   "Dauerhaftes zuvor ins Gedaechtnis geschrieben" if saved
                   else "Gedaechtnis-Schreibung fehlgeschlagen",
                   round(after / 1000)))
    _autocompact_supported = False
    return None    # this CLI doesn't honor /compact - stay silent, no per-turn pollution


def history(user):
    """The user's persisted copilot transcript (the same Claude session the
    backend resumes - session id in copilot_sessions.json, resumable even from
    a terminal via `claude --resume <id>`) plus the PM-session stats the board
    chat renders as context meter + usage line (card-chat parity)."""
    st = _stats().get(user)
    if st:
        st = dict(st)
        st["plan_pct"] = _plan_share(st)
    return {"messages": [_readable(m) for m in _log().get(user, [])],
            "session_id": _sessions().get(user),
            "stats": st}


def owner_name():
    """WHO the board chat belongs to, or None. Derived from the user registry
    every time, never cached - the same read say() always did inline, lifted
    out so it has one owner: pm_comm._ask_owner has to ask "is one of MY
    questions still unanswered?" before posting another, and that means
    resolving the same principal say() writes to. Two copies of this lookup
    would be two answers to "whose chat is this"."""
    try:
        from spine.auth import auth
        return next((u["name"] for u in auth.list_users()
                     if u.get("role") == "owner"), None)
    except Exception:
        return None


def chat_question_open():
    """The owner's currently-open chat question, or None - open_question()
    with the principal resolved, for callers outside this cell.

    Exists because the chat offers exactly ONE answerable question at a time
    (see open_question), and a writer that ignores that stacks DEAD PANELS:
    measured 2026-08-30 12:47, the first live tick after the notice rework
    posted three asks in one PM pass, and the two earlier ones - both more
    urgent than the third - were unanswerable the instant the third landed.
    Anyone about to ask must check here first."""
    u = owner_name()
    return open_question(u) if u else None


def open_question(user):
    """The CHAT's own open question (as opposed to a card's), or None.

    "The chat's", not "Henry's", since 2026-08-30: the PM asks through this
    same channel now - pm_comm._ask_owner writes a cls:"bot" entry carrying a
    question - because the owner decreed that an automatic notice holding a
    real decision has to give him a BUTTON instead of a paragraph. Both ends
    of the channel key on cls "bot" (this function, which routes_copilot.
    _answer_text checks the tapped request_id against, and the app's
    openChatQuestion), so a PM question written in any other class would
    render as prose with buttons nobody can tap. The tapped answer then walks
    the ordinary chat path into Henry - the right split, since the PM detects
    and asks while Henry is the one with hands to execute the answer.

    DERIVED from the log every time it is asked - there is no `pending_question`
    field anywhere, and there must not be one. The chat log is the single record
    of what was said; a second stored flag beside it is a copy that can disagree
    with it (the class of bug the no-monkey-patches decree names), and it would
    need clearing on every path that ends a question: an answer, a fresh message,
    a cancel, a session rotation. Reading it back costs nothing and cannot drift.

    "Open" = the newest `cls:"bot"` entry carrying a question, with NOTHING said
    since. Anyone speaking after it settles it: the owner moved on, or Henry did.
    This mirrors openCardQuestion() in the app - same rule, and the app's panel
    disappearing is then the truth rather than a guess, because answering a
    superseded question is a 409 here anyway.

    Note this covers only questions asked IN the chat (Henry's or the PM's). A
    mirrored CARD question belongs to that card and is answered through
    sessions.answer_question (see _route_to_card)."""
    log = _log().get(user, [])
    for i in range(len(log) - 1, -1, -1):
        m = log[i]
        if m.get("cls") != "bot" or not m.get("question"):
            continue
        if any(x.get("cls") in ("you", "user", "bot") for x in log[i + 1:]):
            return None
        return m["question"]
    return None


def _readable(m):
    """BACKSTOP for entries written before chat() learned to clean the reply.

    Every turn from here on stores prose + a typed `question` (see chat()), so
    this is a no-op on new entries - `strip` returns the text untouched when the
    sentinel is absent. But the owner's log already HOLDS raw blocks from every
    wear/glasses turn taken until now, and those are exactly the lines his
    screenshot shows. They are cleaned on READ rather than rewritten in place:
    the chat log is an append-only record of what was said, and a display defect
    is not a reason to edit history.

    The block is dropped, not resurrected as a panel. A question from a past
    turn has already been answered or has gone stale, and offering dead buttons
    for it would be a worse lie than the JSON was."""
    # NOT every entry is a dict, and the writer says so out loud: _append_log
    # deliberately passes a non-dict through instead of crashing the log write
    # (ops/tests/test_chat_date_stamp.py step 6 asserts exactly that). The reader
    # never honoured the other half of that contract - one stray string in the
    # log and this raised AttributeError, taking down /chat/history and with it
    # the transcript on EVERY surface at once, not just the malformed line.
    #
    # Returned untouched rather than dropped: this function's whole discipline is
    # that the log is an append-only record and a display defect is no reason to
    # edit history. The surfaces already skip what they cannot render.
    if not isinstance(m, dict):
        return m
    if m.get("cls") != "bot":
        return m
    text = m.get("text") or ""
    # strip_stream, not strip: strip() needs a COMPLETE block and returns a
    # TRUNCATED one untouched - which put the raw JSON straight back on screen
    # for exactly the malformed case this function exists to hide (caught by
    # ops/tests/test_chat_question_channel.py). strip_stream also cuts from an
    # unclosed opening tag, so a reply that was cut off mid-block is covered.
    cleaned = ask.strip_stream(text)
    if cleaned == text:
        return m
    m = dict(m)
    # A legacy reply that was ONLY a block still has to say something:
    # summary() reads the question back as its first line. If even that fails
    # (a MALFORMED block - truncated JSON, a bad label type), the entry is left
    # with EMPTY text and the app skips the bubble entirely. Falling back to the
    # raw text here would put the JSON back on screen, which is the whole defect
    # - an unreadable block is hidden, never shown "just in case".
    q, _ = ask.parse(text)
    m["text"] = cleaned.strip() or (ask.summary(q) if q else "")
    return m


def say(text, cls="pm", card=None, extra=None):
    """THE harness's voice in the owner's board chat - the one place anything
    non-interactive speaks to the owner (pm._say and the lane pipeline both go
    through here). Without this, work that happens without the owner typing
    (a gate verdict, a merge, a bounce) only ever reached the flight recorder
    and the event log, so the chat looked frozen while the daemon worked.
    Best-effort by design: never let a chat write break the work it reports.

    `card` = a card id this notice is ABOUT (e.g. a lane outcome). When it
    resolves to a live run_dir, the notice ALSO folds into that card's own
    timeline (byKind:henry) - so a proactive nudge about a specific card
    shows up in its team-chat too, not only the global board chat.

    `card` is now also PERSISTED on the chat entry itself (2026-08-29, the
    one-inbox decree). It was previously used only to pick the timeline to fold
    into and then thrown away, which left every harness-authored line in the
    board chat unattributed: the owner could read "Gate ist rot" without the
    transcript knowing WHICH card said it. Carrying the id is what lets a reply
    be routed back to that card by IDENTITY instead of by guessing from the
    text - see routes_copilot.chat_post's `reply_to_card`.

    `extra` merges additional fields into the entry (the card mirror's `kind` /
    `cardName` / `question`). Kept as one opaque dict rather than a growing
    parameter list so a new mirror field never needs a signature change here,
    in _append_log, and in every stub that stands in for this function."""
    try:
        owner = owner_name()
        if not owner:
            return
        entry = {"cls": cls, "text": text, "ts": time.strftime("%H:%M")}
        if card:
            entry["card"] = card
        if extra:
            # never let a caller's dict overwrite the three fields above -
            # a mirror line that lied about its own cls would be unrenderable
            entry.update({k: v for k, v in extra.items()
                          if k not in ("cls", "text", "ts")})
        _append_log(owner, [entry])
        if card:
            ct = _find_card(card)
            run_dir = ct.get("run_dir") if ct and not isinstance(ct, list) else None
            if run_dir:
                from spine.agent import timeline_store
                timeline_store.append(run_dir, "s:" + uuid.uuid4().hex,
                    {"kind": "note", "text": text, "byKind": "henry",
                     "ts": time.strftime("%H:%M:%S"), "ta": time.time()})
    except Exception:
        pass

# live copilot subprocess per user, so the chat's Stop button can kill a turn.
_running = {}
# WHICH card the in-flight turn is scoped to (chat(card=...)), or None for a
# board-chat turn. A satellite of _running with exactly the same lifetime -
# set and cleared at the same two places, never derived from anything else.
# The live feed is per USER but a turn belongs to ONE surface, and turns are
# serialised (_turn_lock), so without this the card chat would render the
# board chat's prose into the card's timeline while it waited for the lock.
_running_card = {}
_cancelled = set()

# -- streaming: ONE chat surface with the card (shared Transcript), only the
# backend differs. The copilot streams its PROSE reply into a per-user live feed
# the board chat polls (like a card's live_partial), so the board agent "types"
# live instead of a blocking "denkt". Actions still come as a trailing block.


def _pm_plan_digest():
    """The PM's LIVE PMP plan, compact - so the copilot GROUNDS its planning in
    it (owner decisions, DoD, risks, feasibility, the measured triangle) instead
    of improvising a second, shallower plan. Empty when no goal is planned."""
    try:
        from cells.pm import pm
        p = pm.live_plan() or {}
    except Exception:
        return ""
    if not (p.get("goal") or p.get("milestones")):
        return ""
    L = ["PM PLAN (the PMP-graded plan - GROUND planning/status answers in THIS, "
         "per the PLANNING DISCIPLINE above):"]
    if p.get("goal"):
        L.append("GOAL: " + str(p["goal"])[:220])
    tri = p.get("triage") or {}
    rs = p.get("triage_reasons") or {}
    L.append("TRIAGE budget=%s timeline=%s scope=%s%s" % (
        tri.get("budget"), tri.get("timeline"), tri.get("scope"),
        (" | " + " ; ".join("%s red: %s" % (k, str(v)[:110]) for k, v in rs.items())) if rs else ""))
    feas = p.get("feasibility") or {}
    if feas.get("note"):
        L.append("FEASIBILITY: " + str(feas["note"])[:300])
    for q in (p.get("open_questions") or [])[:4]:
        L.append("OPEN OWNER DECISION (blocks the plan): " + str(q)[:220])
    for r in (p.get("risks") or [])[:4]:
        L.append("RISK: " + str(r)[:180])
    ms = p.get("milestones") or []
    if ms:
        L.append("MILESTONES:")
        for m in ms[:6]:
            dw = m.get("done_when") or []
            L.append("  - %s (due %s, %s%s)%s" % (
                str(m.get("name"))[:80], m.get("target_date") or "?", m.get("priority") or "?",
                (", blocked_by: " + str(m.get("blocked_by"))[:70]) if m.get("blocked_by") else "",
                (" done_when: " + "; ".join(str(x)[:55] for x in dw[:2])) if dw else ""))
    return "\n".join(L)


def _copilot_run_dir(user):
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", user or "u") or "u"
    d = os.path.join(ROOT, "copilot_runs", safe)
    os.makedirs(d, exist_ok=True)
    return d


def _cwrite(path, text):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def _crm(path):
    try:
        os.remove(path)
    except OSError:
        pass




def live(user):
    """The board agent's live streaming reply + reasoning for /chat/live - the
    board chat polls this while a turn runs so it streams like a card AND shows a
    live 'thinking' preview during the pre-output reasoning (no dead 40s wait)."""
    d = _copilot_run_dir(user)

    def _rd(name):
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""
    # strip_stream, not strip: while the block is still being typed its CLOSING
    # tag has not arrived, so strip() (which needs a complete block) would let
    # the JSON appear character by character in the live bubble and only tidy
    # itself once the turn settled. Cutting from the opening tag - and from a
    # half-typed one - is the same thing the card's readers do
    # (spine/agent/claude_sessions.py: read_transcript_live/_store); the board
    # chat was simply the one live feed that never got it.
    # `card` scopes the feed to the surface the running turn belongs to, so a
    # card chat can stream Henry's card-scoped reply (debt
    # card-henry-reply-not-streamed) without ever painting a BOARD turn's prose
    # into a card's timeline - see _running_card.
    return {"text": ask.strip_stream(_rd("live_partial.txt")),
            "thinking": _rd("live_thinking.txt"),
            "running": user in _running,
            "card": _running_card.get(user)}


def cancel(user):
    """Stop this user's in-flight copilot turn (the chat Stop button)."""
    _cancelled.add(user)
    # Drop queued speech in the same breath. Audio that outlives the turn it
    # belongs to would talk over the next question - the interrupt has to reach
    # the ear, not just the model.
    from spine.media import voice_stream as _vstream
    _vstream.drop(user)
    p = _running.get(user)
    if p:
        try:
            p.terminate()
        except Exception:
            pass
    # a terminated process is no longer reusable - forget the warm handle so
    # the next turn respawns clean (--resume keeps the conversation). Drop the
    # handle of the conversation the KILLED turn belonged to: _running_card is
    # the existing satellite of _running that already records exactly that, so
    # cancelling a card turn no longer throws the board's warm process away.
    _persist_drop(_skey(user, _running_card.get(user)))
    return bool(p)


def build_argv(cli_model, sid, system):
    """THE assembly point for the board copilot's `claude` argv. ONE owner.

    Returns (argv, role_in_turn). `role_in_turn` is True when the role could NOT
    be passed as --append-system-prompt and must be prefixed to the user turn
    instead - see the argv_form_safe note below.

    Extracted so /harness's spawn preview shows this surface's REAL command
    rather than a second hand-written copy of it (CLAUDE.md: one owner, no
    reconstructed state). The copilot's flag order genuinely differs from a card's
    - --model/--resume come before the system prompt here, and the settings layer
    goes last - which is precisely the kind of detail a re-listed preview gets
    wrong and then reports with total confidence.

    ROLE SEPARATION: the copilot's standing role belongs in the SYSTEM prompt,
    not stapled to the front of every user turn. As a user-turn prefix it was
    re-sent verbatim on each message, it sat inside the resumed conversation
    where the model could treat it as something the *user* said (and later turns
    could argue with it), and it blurred the line between the fixed role and the
    live board snapshot. --append-system-prompt puts it where the card workers'
    brief already lives.

    ...but ONLY when arguments really travel as an argv list. On the last-resort
    cmd.exe spawn form a 10 KB argument full of quotes and ``` fences is exactly
    the payload that broke --resume, so there we keep the old prefix-the-turn
    shape: degraded role separation beats a mangled command line.
    """
    from spine.agent import drivers
    from spine.registry import harness
    argv = [CLAUDE, "-p", "--output-format", "stream-json",
            "--include-partial-messages", "--verbose", "--permission-mode", henry_pmode()]
    if cli_model:              # whitelist only - no arbitrary model ids from the client
        argv += ["--model", cli_model]
    if sid:
        argv += ["--resume", sid]
    role_in_turn = not drivers.argv_form_safe(CLAUDE)
    if not role_in_turn:
        argv += ["--append-system-prompt", system]
    argv += harness.cli_args("board-copilot")
    return argv, role_in_turn


def chat(user, message, role="operator", model="", thinking="", attachments=None,
         card=None, allow_actions=True, extra_system="", voice_stream=False,
         client_msg_id="", announce=True, _retried=False, model_source="user"):
    """One copilot turn for this user. Returns {reply, actions, refused, cost, usage}.
    model/thinking/attachments come from the shared composer and resolve through
    turnopts (same whitelist + Auto routing the card chat uses). `card` = the id of
    a card the user is currently viewing, so 'this card' / 'it' resolves to it -
    the same free agent, reachable from within a card.

    allow_actions=False makes the turn ADVISORY: the model may still emit an
    actions block, but nothing is executed and the dropped types come back in
    `refused`. That is the seam glass mode uses - see the refusal site below for
    why this is enforced in code rather than asked for in the prompt.

    extra_system is appended to the resolved system brief, for a surface with a
    hard shape requirement (the lens: short prose, always end in tappable
    options) that the shared board brief should not have to carry.

    announce=False silences the finished answer's NOTIFICATION (notify.chat_reply
    below). For a door whose own response IS the delivery - the watch and the
    glasses both render the reply and speak it aloud inside this same request -
    a push would buzz the wrist about a sentence it is reading out. The phone's
    /chat needs no such flag: its app reports presence, so an answer the owner
    can see suppresses itself.

    voice_stream=True renders the prose to speech SENTENCE BY SENTENCE as it is
    generated, into the per-user chunk list `/chat/live` serves - so voice mode
    starts talking a second into the turn instead of after it. Opt-in per
    request, not a server setting: a client that does not poll for the chunks
    must keep getting the one-shot `voice:true` clip instead, or an app that is
    one OTA behind would go silent (see spine/media/voice_stream.py)."""
    from spine.agent import turnopts
    # ONE conversation per (user, card): a card-scoped Henry chat resumes its
    # OWN session, not the eternal board one. Board chat keeps the bare user
    # key, so the existing session survives untouched. See _skey.
    skey = _skey(user, card)
    sess = _sessions()
    sid = sess.get(skey)
    paths = turnopts.save_attachments(os.path.join(ROOT, ".copilot_attachments", user),
                                      attachments)
    # "" (no explicit pick) routes as Auto - never falls through to the CLI's
    # global default, which is whatever the owner's interactive /model was
    # last set to (the same leak fixed in sessions._turn, 2026-08-14).
    # ctx_tokens is a ROUTING INPUT, not just a meter. Henry's session is
    # long-lived (one per user, months of board chat) while the picker reads a
    # two-character message: without this the trivial-message path picked the
    # 200k Haiku tier for a 615k session and the resume died on "Prompt is too
    # long" (2026-08-30, card 20260830-065545). Read from copilot_stats, the
    # ONE owner of that number - folded at event time, never re-derived.
    _st = _stats().get(user) or {}
    # STICKY TIER (owner decree 2026-09-02, "Fix the routing"): a conversation
    # keeps its model. Resolution order: explicit pick > this conversation's
    # recorded model > Auto - so Auto routes at most ONCE per conversation
    # instead of re-rolling the tier from every message's wording. A tier flip
    # invalidates the per-model prompt cache and re-reads the whole session at
    # full price/latency; on a long session that costs far more than any
    # per-message "right tier" buys (the warm PROCESS never made the CACHE
    # warm). resolve_model still applies the window law to whatever wins - a
    # sticky pick that no longer fits the session is lifted, never obeyed
    # blindly. A voice turn USES its pinned fast model (explicit wins) but
    # must not RECORD it - the voice pin is a per-turn speed decree, not the
    # conversation's choice (model_source="voice" from routes_copilot).
    _pick = (model or "").strip()
    if not _pick or _pick == "auto":
        _pick = _model_prefs().get(skey) or "auto"
    cli_model, _ = turnopts.resolve_model(_pick, message, bool(paths),
                                          signals={"ctx_tokens": _st.get("ctx_tokens")})
    if cli_model and model_source != "voice":
        _save_model_pref(skey, cli_model)
    body = turnopts.augment_prompt(message, thinking, paths)
    focus = ""
    card_run_dir = None
    if card:
        ct = _find_card(card)
        if ct and not isinstance(ct, list):
            focus = ("\n\nCURRENT CARD (the user is viewing this - resolve 'this card' / 'it' "
                     "to it; a plain work instruction means steer it): %s | %s | %s"
                     % (ct["id"], ct.get("branch"), (ct.get("task") or "")[:80]))
            card_run_dir = ct.get("run_dir") or None
    if card_run_dir and not _retried:
        # Card-scoped chat is a real participant in THAT card's own team-chat
        # transcript, not a client-side illusion - fold the human's message in
        # right now, at submission (same discipline as drivers.py's own
        # timeline fold), so a second device watching the card sees it live.
        # Guarded by `not _retried`: the filler-guard retry below calls chat()
        # again with the SAME message - it must not fold the human's words in
        # twice.
        from spine.agent import timeline_store
        _tsv, _tav = time.strftime("%H:%M:%S"), time.time()
        timeline_store.append(card_run_dir, "s:" + uuid.uuid4().hex,
            {"role": "user", "kind": "text", "text": message,
             "by": user, "byKind": "human", "to": "henry", "ts": _tsv, "ta": _tav})
    # A turn carries the context of the surface it belongs to, and only that.
    # A CARD chat gets that card's own timeline (worker steps, Henry's notes,
    # every steer - the one-inbox record); it does NOT need 22 other cards, and
    # sending them was most of what made the board session grow. A BOARD chat
    # gets the live board; its history stays on demand (see _snapshot's
    # docstring and ops/tools/board_state.py).
    if card:
        _cc = _card_context(card)
        snapshot_block = (("CARD CONTEXT (%s):\n" % time.strftime("%Y-%m-%d %H:%M"))
                          + _cc + "\n\n") if _cc else ""
    else:
        _plan = _pm_plan_digest()
        snapshot_block = "BOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M") \
            + _snapshot() + (("\n\n" + _plan) if _plan else "") \
            + _memory_digest()
    # The ROLE is data: ops/harness/agents/board-copilot.md (the only copy).
    # brief() is total - a mangled/absent file degrades to the short stub in
    # harness._DEFAULTS and reports via harness.errors(), never breaks the turn.
    from spine.registry import harness
    system = harness.brief("board-copilot")
    if extra_system:
        system = system + "\n\n" + extra_system
    # Results of the PREVIOUS turn's actions, told exactly once (worker parity:
    # sessions._pending_context). Without this Henry reported a FAILED dispatch
    # as running - the error was on the owner's screen, never in his session.
    with _pending_lock:
        _pending = _pending_actions.pop(skey, [])
    action_report = ""
    if _pending:
        action_report = ("ERGEBNIS deiner Aktionen aus dem LETZTEN Turn (daemon-"
                         "seitig NACH deiner Antwort ausgefuehrt - du siehst sie "
                         "hier zum ersten Mal; ein Fehler heisst: die Aktion ist "
                         "NICHT gelaufen, behaupte nichts anderes):\n- "
                         + "\n- ".join(str(r)[:400] for r in _pending) + "\n\n")
    turn = action_report + snapshot_block + focus + "\n\nUSER (%s): %s" % (user, body)
    # STREAM (shared with the card surface): stream-json so the prose reply types
    # into the per-user live feed the board chat polls, instead of a blocking
    # black box. The turn goes in on stdin (it is huge - never a cmd arg).
    run_dir = _copilot_run_dir(user)
    live_path = os.path.join(run_dir, "live_partial.txt")
    think_path = os.path.join(run_dir, "live_thinking.txt")
    sid_path = os.path.join(run_dir, "live_session.txt")
    _crm(live_path); _crm(think_path); _crm(sid_path)
    # Speech rides the SAME prose stream as the live text - one source, folded in
    # at event time below, never re-derived from the finished reply.
    from spine.media import voice_stream as _vstream
    if voice_stream:
        _vstream.begin(user)
    else:
        _vstream.drop(user)     # a non-voice turn must not leave last turn's audio collectable
    # drivers._cmd_line, NOT ["cmd","/c",...]: routing claude.cmd through cmd.exe
    # silently mangles quoted arguments (it ate the card workers' --resume - see
    # drivers._real_claude_exe).
    from spine.agent import drivers
    _cancelled.discard(user)
    # serialize with prewarm (and any concurrent send) on the shared process
    _lk = _turn_lock(user)
    _lk.acquire()
    # PERSISTENT PORT when argv travels safely (the normal case since ea09780):
    # reuse the warm stream-json process - the 8-12s spawn is paid once, not
    # per turn (voice-speed decree). The cmd.exe-degraded box keeps the old
    # one-shot spawn; its problem is quoting, not latency.
    persistable = drivers.argv_form_safe(CLAUDE)
    try:
        if persistable:
            # base brief only at spawn (constant); per-turn overlays (VOICE_STYLE
            # et al) ride inside the turn text so voice<->typed does not respawn.
            base_system = harness.brief("board-copilot")
            p, _fresh = _persist_get(skey, cli_model, sid, base_system)
            prompt = (extra_system + "\n\n" + turn) if extra_system else turn
        else:
            argv, _role = build_argv(cli_model, sid, system)
            prompt = system + "\n\n" + turn
            # encoding="utf-8" is REQUIRED: without it Windows decodes claude's UTF-8
            # output as cp1252 and mangles em dashes / arrows into mojibake in the chat.
            # stderr -> DEVNULL: we read stdout line-by-line (the pump), so an undrained
            # stderr pipe could fill and DEADLOCK the process mid-turn.
            p = subprocess.Popen(drivers._cmd_line(argv), cwd=ROOT, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, encoding="utf-8", errors="replace")
    except Exception:
        _lk.release()      # a failed spawn must not deadlock every later turn
        raise
    _running[user] = p
    _running_card[user] = card or None
    parts, think, result, session_id, ctx_usage = [], [], {}, sid, {}
    resume_echo, ctx_first = False, {}
    # SILENCE watchdog (persist only): a one-shot process ends the read loop by
    # exiting; a persistent one that stops answering would hang the pump forever.
    # 600s of NO events -> kill (the read then sees EOF); same silence-not-wall
    # clock rule as everywhere else in the harness.
    _beat = {"t": time.time(), "done": False}
    if persistable:
        def _watchdog():
            while not _beat["done"]:
                if time.time() - _beat["t"] > 600:
                    try:
                        p.kill()
                    except Exception:
                        pass
                    return
                time.sleep(5)
        threading.Thread(target=_watchdog, daemon=True).start()
    try:
        if persistable:
            try:
                p.stdin.write(json.dumps({"type": "user",
                                          "message": {"role": "user", "content": prompt}}) + "\n")
                p.stdin.flush()
            except Exception:
                # warm process died since the health check - respawn ONCE fresh
                _persist_drop(skey)
                base_system = harness.brief("board-copilot")
                p, _fresh = _persist_get(skey, cli_model, sid, base_system)
                _running[user] = p
                p.stdin.write(json.dumps({"type": "user",
                                          "message": {"role": "user", "content": prompt}}) + "\n")
                p.stdin.flush()
        else:
            p.stdin.write(prompt); p.stdin.close()
        for line in p.stdout:                       # the pump (like drivers._pump)
            if user in _cancelled:
                break
            line = line.strip()
            _beat["t"] = time.time()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            typ = ev.get("type")
            if typ == "system" and ev.get("session_id"):
                got = ev["session_id"]
                # resume-attachment evidence (drivers.py parity): a successful
                # --resume ECHOES the asked-for id in the init event.
                if ev.get("subtype") == "init" and sid and got == sid:
                    resume_echo = True
                session_id = got; _cwrite(sid_path, session_id)
            elif typ == "assistant":
                # each full assistant message carries the usage of ITS OWN API
                # call - keep the last one as the context-meter source, exactly
                # like drivers._on_event (see _fold_stats for why the result
                # event's summed usage must not feed the meter).
                mu = (ev.get("message") or {}).get("usage")
                if isinstance(mu, dict) and mu:
                    ctx_usage = mu
                    # the FIRST call's usage is the resume-continuity witness
                    # (sessions.resume_detached): a real continuation carries
                    # >= the prior context; a silent fresh start carries only
                    # the brief.
                    if not ctx_first:
                        ctx_first = mu
            elif typ == "stream_event":
                e = ev.get("event") or {}
                if e.get("type") == "content_block_delta":
                    dl = e.get("delta") or {}
                    if dl.get("type") == "text_delta":
                        parts.append(dl.get("text", ""))
                        _live_prose = _strip_actions_live("".join(parts))
                        _cwrite(live_path, _live_prose)
                        if voice_stream:
                            _vstream.feed(user, _live_prose)
                    elif dl.get("type") == "thinking_delta":
                        # stream the REASONING too - it starts ~9s before the
                        # prose, so the chat shows live progress instead of a
                        # dead "denkt 40s" wait. Rolling tail (last ~600 chars).
                        think.append(dl.get("thinking", ""))
                        _cwrite(think_path, "".join(think)[-600:])
            elif typ == "result":
                result = ev
                if persistable:
                    break        # the process LIVES ON - this turn is complete
        if not persistable:
            try:
                p.wait(timeout=8)
            except Exception:
                pass
    finally:
        _beat["done"] = True
        _running.pop(user, None)
        _running_card.pop(user, None)
        if persistable and (user in _cancelled or p.poll() is not None):
            # a cancelled or dead process must not be reused - next turn
            # respawns via --resume and loses nothing but the warmth
            _persist_drop(skey)
        _lk.release()
        if voice_stream:
            # Flush BEFORE the live file is cleared: the last sentence of a reply
            # usually has no trailing whitespace, so the turn ending is the only
            # proof that it closed.
            if user in _cancelled:
                _vstream.drop(user)
            else:
                _vstream.finish(user, _strip_actions_live("".join(parts)))
        _crm(live_path); _crm(think_path)           # done streaming - clear the live preview
    if user in _cancelled:                 # Stop was pressed
        _cancelled.discard(user)
        return {"reply": "(stopped)", "actions": [], "cost": None, "usage": None}
    txt = result.get("result") or "".join(parts)
    if not (txt or "").strip():
        raise RuntimeError("copilot produced no output (turn ended without a result)")
    sid_final = result.get("session_id") or session_id
    rotate_note = None
    if sid_final:
        # session-rotation safety net (Paseo accept-and-rebind, card parity:
        # sessions._finish_turn). Without this, a resume that silently starts
        # FRESH (an overflowed/compacted tip --resume can't continue) just
        # overwrote the pointer with no chain and no notice - the whole board
        # chat "disappears" exactly like the pre-fix card bug. The pointer
        # only ever advances to a session that demonstrably holds THIS turn
        # (proven by the result read off it); the old head is kept, never lost.
        if sid and sid_final != sid:
            from cells.engineer import sessions
            st = _stats().get(user) or {}
            meta = {"resumed_from": sid, "resume_echo": resume_echo, "ctx_first": ctx_first}
            if sessions.resume_detached(st.get("ctx_tokens"), meta):
                rotate_note = ("⚠ Kontext verloren: die Session liess sich nicht "
                                "fortsetzen (%s…), neu begonnen (%s…). Der bisherige "
                                "Verlauf bleibt oben sichtbar." % (sid[:8], sid_final[:8]))
            chain = [s for s in (st.get("session_chain") or []) if s != sid]
            chain.append(sid)
            st["session_chain"] = chain[-6:]           # bounded - last 6 prior sessions
            all_st = _stats(); all_st[user] = st; _save_stats(all_st)
        sess[skey] = sid_final
        _save_sessions(sess)
    reply_prose, acts_parsed = _parse_reply_actions(txt)
    # THE ASK BLOCK, folded in HERE - at event time, at the protocol's one owner.
    #
    # _parse_reply_actions strips the ```actions fence and nothing else, so a
    # <helmdeck-ask> block used to survive into `out["reply"]` AND into the
    # persisted `cls:"bot"` log entry verbatim. The watch papered over that on
    # READ (routes_wear._wear_text / wear_chat_get); the phone's /chat/history
    # did not, so the board chat rendered a screenful of '{"label": ...' JSON -
    # the owner's screenshot, 2026-08-29 17:56.
    #
    # The block reaches THIS log even though board-copilot.md sets
    # ask_protocol:false, because /wear/talk and /glance/talk run WEAR_BRIEF /
    # GLASS_BRIEF through this same copilot.chat on the SAME session - and both
    # of those briefs REQUIRE the block. One session, one log, three surfaces.
    #
    # So it is parsed once, where the reply is produced, and both halves are
    # carried as typed state: `reply_prose` is the prose every surface renders,
    # `question` the tappable half every surface offers. No surface re-derives
    # it from text, and no second parser exists (the phone must never own a
    # copy of this grammar - spine/ops/ask.py is the only one).
    question, reply_prose = ask.parse(reply_prose)
    # A reply that is ONLY a block (the watch/glasses briefs invite exactly
    # that: "end every reply with a <helmdeck-ask> block") would otherwise leave
    # an EMPTY bubble in the chat with the content hidden in the panel. The
    # question's own first line is the honest text for it - never the raw block.
    if question and not reply_prose.strip():
        reply_prose = ask.summary(question)
    # FILLER GUARD (speech-to-speech's provisional-generation lesson, adapted).
    # Measured 2026-08-23 on the owner's PM session: at ~94% context fill the
    # fast voice model answered two real questions with the session's
    # task-notification etiquette - literally "No response requested." A full
    # history rollback is not something --resume sessions offer, so the cheap
    # half: never DELIVER the filler. Re-submit the same question once with a
    # corrective overlay; the retry's answer is what gets logged and spoken.
    if (not _retried and not acts_parsed
            and reply_prose.strip().rstrip(".!").lower() in _FILLER_REPLIES):
        _fold_stats(user, result, ctx_usage)   # the wasted turn is still paid for
        return chat(user, message, role=role, model=model, thinking=thinking,
                    attachments=None, card=card, allow_actions=allow_actions,
                    extra_system=(extra_system + "\n\nDeine letzte Antwort war eine "
                                  "leere Floskel ohne Inhalt. Beantworte jetzt die "
                                  "eigentliche Frage des Owners.").strip(),
                    voice_stream=voice_stream, announce=announce,
                    # carried through the retry: dropping it here would log the
                    # message WITHOUT its client id, and the app would silently
                    # fall back to position matching for exactly the turns that
                    # already went wrong once.
                    client_msg_id=client_msg_id, _retried=True)
    out = {"reply": reply_prose, "actions": acts_parsed}
    # The tappable half rides the response as TYPED state, so /wear/talk and
    # /glance/talk keep getting a question after the prose was cleaned here
    # (they used to re-parse `reply` themselves - see their call sites) and the
    # phone gets one for the first time.
    if question:
        out["question"] = question
    d = result                                       # for cost/usage below
    u = d.get("usage") or {}
    usage = {"in": (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0)),
             "out": u.get("output_tokens", 0), "cost": d.get("total_cost_usd")}
    # measured economics for the PM session itself (card parity): fold this
    # turn's spend + the last call's context fill into copilot_stats.json,
    # which /chat/history serves to the board chat's meter + usage line.
    _fold_stats(user, d, ctx_usage)
    acts = out.get("actions", [])[:6]
    # Persist the exchange NOW and return immediately, so the chat is responsive.
    # Actions (moves, MERGES, steers - potentially minutes) run in the BACKGROUND
    # and append their results to the transcript as they land; the chat polls, so
    # you see them live. This is why 'move 4 cards to done' no longer freezes.
    if card_run_dir:
        # One owner, folded at event time: the reply lands in the CARD's own
        # timeline (not the user's global copilot_log) - it is that card's
        # conversation, visible to every device/user watching it.
        from spine.agent import timeline_store
        _tsv, _tav = time.strftime("%H:%M:%S"), time.time()
        timeline_store.append(card_run_dir, "s:" + uuid.uuid4().hex,
            {"role": "assistant", "kind": "text", "text": out.get("reply", ""),
             "by": "Henry", "byKind": "henry", "ts": _tsv, "ta": _tav, "usage": usage})
        if rotate_note:
            timeline_store.append(card_run_dir, "s:" + uuid.uuid4().hex,
                {"kind": "note", "text": rotate_note, "byKind": "henry", "ts": _tsv, "ta": _tav})
    else:
        # client_msg_id: the id the SENDING CLIENT minted for this message, echoed
        # back on the persisted entry so the app can retire its optimistic copy by
        # IDENTITY instead of by comparing text. Text comparison cannot tell two
        # identical messages apart and silently strands a copy forever when the
        # stored text differs by a character - the defect the owner reported
        # 2026-08-29 ("meine Nachricht steht ganz am Ende"). Same decision Paseo
        # made (packages/app/src/timeline/session-stream-reducers.ts:
        # matchesLocalUserMessageIdentity prefers clientMessageId and keeps text
        # matching only as a COMPAT shim with a removal date).
        #
        # Absent for older clients and for surfaces that never send one (the
        # watch, the glasses): the key is simply omitted, and the app falls back
        # to position. Nothing downstream may require it.
        you = {"cls": "you", "text": message, "ts": time.strftime("%H:%M")}
        if client_msg_id:
            you["client_msg_id"] = client_msg_id
        bot = {"cls": "bot", "text": out.get("reply", ""), "ts": time.strftime("%H:%M"), "usage": usage}
        # PERSISTED beside the prose, exactly as card_mirror.say_card stamps a
        # worker's question onto a `cls:"card"` entry. The panel is therefore
        # still there after a reload, on any device reading this log - a
        # question that only lived in the POST response would vanish on the
        # next poll, which is the one thing an open decision must not do.
        if question:
            bot["question"] = question
        entries = [you, bot]
        if rotate_note:
            entries.append({"cls": "error", "text": rotate_note, "ts": time.strftime("%H:%M")})
        _append_log(user, entries)
        # THE REVERSE MIRROR (owner report 2026-08-29 18:09: "Henrys Antworten
        # loesen keine Notification aus"). card_mirror folds a CARD's news into
        # this chat; this is the other direction - the chat's own news out to the
        # phone and the wrist. It hangs HERE, at the one line that makes an
        # answer exist for the owner, rather than in the /chat route: three doors
        # run a Henry turn (phone, watch, glasses) and all three land on this
        # persist, so a route-level hook would have been one copy per door with
        # nothing keeping them in step - and the door that got forgotten would
        # answer into silence, which is the exact defect being closed.
        #
        # Deliberately NOT in the card_run_dir branch above: that reply lands in
        # a CARD's timeline, not in this transcript, so a notification promising
        # the Henry chat would open a chat that never mentions it. The card's own
        # events already reach the owner through notify.card_event.
        #
        # OFF the request thread. push_fcm does an OAuth token exchange plus one
        # HTTPS call PER DEVICE, each with a 15s timeout, and this line sits
        # INSIDE the owner's /chat request - a slow FCM would be worn as latency
        # on every single answer, which is the opposite of the voice-speed
        # decree. server._bg is the repo's choke point for backgrounded work and
        # carries the crash reporting bare threads kept losing.
        #
        # Best-effort, but never SILENT (card_mirror's rule): a reporting channel
        # that quietly stops working looks exactly like a quiet day.
        if announce:
            _said = out.get("reply", "")

            def _announce():
                try:
                    from spine.comms import notify
                    notify.chat_reply(_said)
                except Exception as _ne:                        # noqa: BLE001
                    print("copilot: reply notification failed -", str(_ne)[:200])

            from spine.http import server as _srv
            _srv._bg("chat:notify:" + str(user), _announce)
    _schedule_compact(user)      # background + single-flight, never blocks this reply
    refused = []
    if acts and not allow_actions:
        # ADVISORY CALLER (glass mode). The lens authenticates with a single
        # SHARED token, not a user session, so it must never reach _run_action -
        # that is the door to machine_task (the whole PC), delete, steer and
        # configure. Refused HERE rather than by asking the model not to emit
        # actions, because a prompt is a request and this is a boundary. The
        # refusal is logged and returned, so no surface can report a change that
        # did not happen.
        refused = sorted({str(a.get("type") or "?") for a in acts})
        _refused_text = ("advisory surface: %d board action(s) NOT run (%s)"
                          % (len(acts), ", ".join(refused)))
        if card_run_dir:
            from spine.agent import timeline_store as _ts
            _ts.append(card_run_dir, "s:" + uuid.uuid4().hex,
                {"kind": "note", "text": _refused_text, "byKind": "henry",
                 "ts": time.strftime("%H:%M:%S"), "ta": time.time()})
        else:
            _append_log(user, [{"cls": "error", "text": _refused_text,
                                "ts": time.strftime("%H:%M")}])
        acts = []
    if acts:
        def _run_bg():
            done = []
            for a in acts:
                try:
                    done.append(_run_action(a, user, role))
                except Exception as e:
                    done.append("action failed: %s" % str(e)[:200])
            if done:
                # Henry sees these NEXT turn (folded into the turn text) - a
                # result that only reached the owner's log left him claiming a
                # failed dispatch was running (2026-09-02 14:44).
                with _pending_lock:
                    _pending_actions.setdefault(skey, []).extend(done)
                if card_run_dir:
                    from spine.agent import timeline_store as _ts
                    for r in done:
                        _ts.append(card_run_dir, "s:" + uuid.uuid4().hex,
                            {"kind": "note", "text": r, "byKind": "henry",
                             "ts": time.strftime("%H:%M:%S"), "ta": time.time()})
                else:
                    _append_log(user, [{"cls": "act", "text": r} for r in done])
        threading.Thread(target=_run_bg, daemon=True, name="copilot-actions").start()
    # feed the keepalive: a real turn IS the freshest cache there is
    _last_turn_at[skey] = _last_touch_at[skey] = time.time()
    return {"reply": out.get("reply", ""), "actions": [], "refused": refused,
            "cost": d.get("total_cost_usd"), "usage": usage}
