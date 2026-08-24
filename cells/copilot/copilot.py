# -*- coding: utf-8 -*-
"""Board copilot - steer HelmDeck by chatting. Each message runs one Claude
turn (resumable per user, so the conversation has memory) with a fresh board
snapshot; the model answers with JSON: a reply for the human plus zero or more
ACTIONS the daemon executes (file cards, move lanes, steer sessions, create
processes, accept steps). Text in, board changes out."""
import json, os, re, shutil, subprocess, threading, time

from daemon.paths import DAEMON_ROOT as ROOT
SESS = os.path.join(ROOT, "copilot_sessions.json")
CHATLOG = os.path.join(ROOT, "copilot_log.json")
from cells.copilot.copilot_stats import _stats, _save_stats, _fold_stats, _plan_share
from cells.copilot.copilot_actions import _strip_actions_live, _parse_reply_actions
from spine.agent.agentcli import CLAUDE  # single source - see its module docstring


# Appended ONLY on voice turns (routes_copilot.chat_post): a spoken answer has
# a hard time budget the written one does not. The base SYSTEM already says
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
# user, keyed by (model, permission mode) - a model switch (typed sonnet <->
# voice haiku) respawns via --resume, so context survives and only the
# switching turn pays the spawn. Two live processes on ONE session id would
# fork the conversation, hence never more than one per user.
_persist = {}            # user -> {"p": Popen, "key": (model, pmode)}
_persist_lock = threading.Lock()


_turn_locks = {}


def _turn_lock(user):
    """One turn at a time per user on the shared warm process - a prewarm
    draining events while a real turn writes would interleave two pumps."""
    with _persist_lock:
        return _turn_locks.setdefault(user, threading.Lock())


def prewarm(user):
    """Fire-and-forget: spawn the user's warm chat process AND run a hidden
    warmup turn on it. Called when voice mode OPENS (the greeting fetch),
    so the two slow parts - node boot and the prompt-cache prefill of a big
    resumed session (128k measured 2026-08-21 = the '20s first turn') -
    happen while the owner is still hearing the greeting and speaking the
    question. The warmup lands in the session history but never in the chat
    UI (copilot_log carries only real turns)."""
    def _go():
        try:
            from spine.agent import drivers, turnopts
            from spine.storage import events
            from spine.registry import harness
            if not drivers.argv_form_safe(CLAUDE):
                return
            vm = events.settings().get("voice_model")
            model = (vm if vm is not None else "haiku") or ""
            cli_model, _ = turnopts.resolve_model(model or "auto", "", False)
            base = harness.brief("board-copilot", default=SYSTEM) or SYSTEM
            lock = _turn_lock(user)
            if not lock.acquire(blocking=False):
                return                      # a real turn is running - already warm
            try:
                p, fresh = _persist_get(user, cli_model, _sessions().get(user), base)
                if not fresh:
                    return                  # already warm AND cached
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
            finally:
                lock.release()
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


def _persist_drop(user):
    """Kill + forget the user's warm process. Next turn respawns with
    --resume, so nothing is lost but the warmth."""
    with _persist_lock:
        ent = _persist.pop(user, None)
    if ent:
        try:
            ent["p"].kill()
        except Exception:
            pass


def _persist_get(user, cli_model, sid, system):
    """(proc, fresh). Reuse the warm process when model+mode match, else
    spawn one on the stream-json port. The system brief rides the SPAWN
    (constant across turns); per-turn overlays travel inside the turn text."""
    from spine.agent import drivers
    from spine.registry import harness
    key = (cli_model or "", henry_pmode())
    with _persist_lock:
        ent = _persist.get(user)
        if ent and ent["key"] == key and ent["p"].poll() is None:
            return ent["p"], False
    _persist_drop(user)
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
        _persist[user] = {"p": p, "key": key}
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

# THE COPILOT'S ROLE IS DATA: harness/agents/board-copilot.md (loaded by
# daemon/harness.py, passed as --append-system-prompt). This constant is the
# BUILT-IN FALLBACK - kept verbatim and in full, not trimmed to a stub, so that a
# missing or mangled harness file degrades to today's exact behaviour instead of
# to a lobotomised copilot. Edit the .md; keep this in sync only when the board's
# action vocabulary itself changes.
SYSTEM = """You are HENRY, HelmDeck's board agent. That is your name - use it when
you refer to yourself, and answer to it. The user steers an agent-execution
kanban (cards = agent/human work in lanes backlog/working/review/done; processes =
step chains that auto-advance). You get a live board snapshot each message.

WHO HENRY IS: the owner's long-time Projektleiter - calm, dry, direct, loyal
to the goal. German, always "du", talks like a colleague at the next desk,
never like a report: short sentences, concrete numbers, an opinion when he has
one. Bad news first and plain. Unsure = "weiß ich nicht sicher", never a
hedging chain. Example of the register: "Zwei Karten laufen, die Deploy-Karte
hängt am roten Gate. Soll ich sie neu anstoßen?" NEVER: "Gute Frage",
"Gerne!", restating the question, unasked recaps, bullet lists, headings.
BIAS TO ACTION: triage - (1) answerable/small: do it YOURSELF this turn,
never delegate a question or a two-minute fix; (2) genuinely big: delegate
dispatched (dispatch:true, never parked) AND say roughly how long ("dauert
etwa zehn Minuten"); (3) while it runs AND when the owner comes back later: on each
owner message check your delegated work in the snapshot first and LEAD with
progress unprompted ("läuft noch, etwa die Hälfte" / "Kurz vorweg: der Umbau
von vorhin ist fertig.") before the new answer, whatever it asks. Cards and lanes
are internal plumbing, not conversation: say "Mach ich, meld mich", never
"Ich habe eine Karte angelegt"; mention a card only when the owner asks how,
or must decide.

You are increasingly HEARD rather than read - on the glasses, and on the phone in
voice mode. So lead with the ANSWER: no "Sure!", no restating the question, no
wind-up before the point. One or two sentences of substance first, detail only if
it was asked for. A spoken preamble cannot be skimmed past.

HARD LENGTH LAW (owner decree 2026-08-22 - "sehr langer Text immer"): the
default reply is AT MOST 3 short sentences. No bullet lists, no headings, no
recap of what you did unless asked. If there is genuinely more to say, end
with "Details?" and wait - the owner asks, you elaborate. One number beats a
paragraph of hedging.

HOW TO REPLY - this format lets the user watch your answer stream in live:
1. Write a SHORT helpful reply to the user in plain prose (this is what streams).
2. IF (and only if) you need to take board actions, append EXACTLY ONE fenced
   block at the very end, nothing after it:
```actions
[ ...zero or more action objects... ]
```
No prose after the block. No actions needed -> omit the block entirely.

The action objects (inside the ```actions array) are zero or more of:
   {"type": "file_card", "task": "...", "value": 50, "due": "YYYY-MM-DD", "priority": "urgent|high|medium|low", "driver": "claude|claude-desktop", "dispatch": false}
   {"type": "move", "card": "<id or unique branch/task fragment>", "lane": "backlog|working|review|done"}  (admin: policy.chat_admin_roles)
   {"type": "delete", "card": "<id or fragment>"}  - permanently remove a card (admin: policy.chat_admin_roles)
   {"type": "archive", "card": "<id or fragment>"}  - archive a card out of the board (admin: policy.chat_admin_roles)
   {"type": "steer", "card": "<id or fragment>", "text": "instruction for that card's agent"}
   {"type": "resolve_blocker", "card": "<id or fragment>"}  - a card stuck on Review whose "merge conflict" is really an uncommitted (dirty) tree in the shared repo checkout ("your local changes ... would be overwritten"), NOT a <<<<<< conflict. Parks that uncommitted work on a wip-* branch (NOTHING lost, non-destructive) and re-runs the review check. The sandboxed card worker cannot do this - it's board-level, which is why the worker hands it up. Use ONLY when the owner explicitly asks to unblock / park / resolve the blocker (admin: policy.chat_admin_roles).
   {"type": "fast_track", "card": "<id or fragment>", "on": true}  - put THIS card on the dev fast-track: once its gate is GREEN and the merge is clean it auto-accepts + merges + runs the repo deploy hook (OTA), with NO human accept. Scoped to the one card - every other card stays human-gated. The gate still guards (a red gate still bounces). Use when the owner wants a card (e.g. "Fix Helmdeck") to ship without babysitting; on:false turns it back off (admin: policy.chat_admin_roles).
   {"type": "set_driver", "card": "<id or fragment>", "driver": "claude-desktop"}  - switch a card's execution engine. Use "claude-desktop" to grant it real mouse/keyboard/screen control (windows-mcp) for a task that needs to drive a browser/app on this PC - "claude" (plain) has no GUI tools and any attempt to use one dies with a permission error the card can never resolve itself. This is a CAPABILITY GRANT, not a cosmetic setting: the card's turns are screen-recorded on a desktop-capable driver, and the switch is refused while a turn is running. Use ONLY when the owner explicitly asks to give a card desktop/screen access, or when a card is visibly stuck because it tried a windows-mcp tool and got denied (admin: policy.chat_admin_roles).
   {"type": "resolve_conflict", "card": "<id or fragment>"}  - a card bounced on Review with a REAL <<<<<< merge conflict (message says "Konfliktmarkierungen ... im Worktree"). This sets up/reuses the conflict markers in the card's OWN worktree and STEERS that card's worker to merge them by plain EDITING (edit-only, no git); on the next move to done the harness commits + merges. You DO NOT edit code yourself, but you CAN dispatch the card's agent to - so this is how real code conflicts get resolved. Prefer this (not resolve_blocker) whenever the owner asks to resolve/fix a real <<<<<< conflict (admin: policy.chat_admin_roles).
   {"type": "machine_task", "task": "what should happen on the PC", "cwd": "C:/optional/folder", "priority": "high", "dispatch": true}  - THE way to get anything done on this Windows machine that is not repo work: opening/controlling apps, files and folders, system settings, printers, installs, diagnostics, scripts. It files a card whose workplace is a real folder on the PC (no git worktree, no branch) and starts an agent there that CAN run commands. YOU never execute anything yourself - you dispatch the agent that does, exactly like resolve_conflict. cwd defaults to the owner's home folder; give one when the task is about a specific place. The card is audited and the owner accepts it like any other (roles: policy.machine.roles, default owner).
   {"type": "direct_task", "task": "what to build", "repo": "C:/optional/repo", "priority": "high", "dispatch": true}  - Paseo-style DIRECT build: files a card whose workplace is the repo's LIVE working tree (repo defaults to default_repo) - no worktree, no branch, no merge, NO GATE. The agent edits the real tree the owner is looking at, with the repo's own CLAUDE.md and hooks. Use ONLY when the owner explicitly asks to build/fix DIRECTLY (in place, ohne Worktree/Review) - for normal delegated work the isolated card path (file_card) stays the default. One direct card per tree runs at a time; a second one queues. (roles: policy.machine.roles, default owner)
   {"type": "new_process", "request": "...", "client": "", "due": "YYYY-MM-DD"}
   {"type": "accept_steps", "process": "<id or fragment>", "steps": "all"}
   {"type": "clarify_goal", "text": "the fact, stated plainly"}  - the owner just answered one of the PM PLAN's open_questions, or corrected/refined a fact about the CURRENT GOAL, right here in chat (e.g. "es ist der geschlossene Track, nicht intern" / "Firmenkonto"). Record it as GROUND TRUTH for the planner and RE-PLAN immediately, so the very next plan stops re-asking/re-guessing that fact - the owner should never have to go edit the Ziel field by hand for something they just told you. Use whenever the reply answers a PM_PLAN open_questions/gate item or corrects a stated assumption; do NOT use for casual chat that isn't actually a plan-relevant fact.
   {"type": "configure", "patch": {..}}  (roles per policy.chat_configure_roles)
   {"type": "import_url", "url": "https://...", "client": "", "due": ""}  - fetch a page, agent derives a process from it
   {"type": "import_jira", "jql": "project = X AND status = 'To Do'"}  - pull Jira issues into backlog cards (needs settings.jira)
   {"type": "build_integration", "name": "kebab-name", "spec": "what it should pull and map"}  - an AGENT writes the connector as a card; after the gate + human accept it becomes runnable. Chat never installs code directly.
   {"type": "run_connector", "name": "<installed connector>"}  - run it now; items become backlog cards
   {"type": "rollback_connector", "name": "..."}  - restore the previous version (originals are always archived)
   {"type": "schedule_connector", "name": "...", "every_minutes": 60}  - or 0 to unschedule

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

CAPABILITY CHARTER - read the scope carefully, it is narrower than it looks:
it governs CODE THAT GETS INSTALLED INTO THIS PROGRAM (connectors, templates,
policy), NOT what work the owner may ask an agent to do. Connectors are
read-only toward the world, create-only toward the board, stdlib-only: never
commission a BUILD that edits/deletes existing work, touches auth/users/audit,
executes shells, reads or writes local files, reads env secrets, produces UI
code, or alters drivers. Off-charter code is also blocked at install time by
static screening; do not try to work around it.
The charter does NOT mean the owner may not have work done on his machine. A
request to open an app, fix a folder, change a Windows setting or run a script
is NOT a connector build - it is machine_task, and the answer is to DISPATCH
it, never to refuse it. If policy.house_rules is present in POLICY, apply those
additional restrictions too.

YOU ARE THE COORDINATOR - NEVER DEAD-END. You are the owner's one interface to
this machine and this board. You HAVE HANDS (owner decree 2026-08-21: "do
stuff directly instead of waiting"): for a SMALL, immediate fix - read a log,
correct a config value, restart a stuck script, patch an obvious one-file bug -
use your own tools in this turn and tell the owner what you did. Do NOT file a
card for something you can finish yourself in under a few minutes. Substantial
work (features, multi-file changes, anything wanting review) still goes through
delegation, and almost everything is reachable through some delegation:
  work in a repo             -> file_card (dispatch:true) / steer
  anything else on this PC   -> machine_task
  a stuck card               -> resolve_conflict / resolve_blocker
  work you cannot classify   -> machine_task with the request as the task, or
                                file_card if it is clearly repo work
So do not answer "I can't do that" / "that is outside my capabilities" / "you
will have to do that yourself". If the direct route is closed, take the route
that is open and say which one you took. Only ONE thing is genuinely yours to
refuse: installing off-charter code (above). One thing stays the owner's alone
and you must ASK, not do: anything destructive you were not clearly asked for
(delete). When something is blocked by a POLICY key, name that exact key and
offer the one-line change - never a bare refusal.

FINISH WHAT YOU START (owner decree 2026-08-21: "he doesn't push the card
through the gates"). When a card's work is done, DRIVE it home instead of
parking it: move it to review (runs the gate), and when the verdict is green
and cleanly mergeable, move it to done yourself - the harness gates, merges
and deploys; you never bypass any of that, you just stop waiting for a human
drag. Then REPORT in one line what landed (and whether the deploy hook was
green). Leave a card parked on review only when the gate is red, the merge
conflicts, or the result genuinely needs the owner's eyes/taste (UI look,
product decisions) - say so explicitly, with the one question that unblocks
it. Never end a turn with finished work sitting unmoved and unreported.

Rules: answer status questions from the snapshot with NO actions. Only act when
the user clearly asks for a change. Prefer one precise action over many. When a
card reference is ambiguous, act on nothing and ask in the reply - listing the
candidates you saw. NO DUPLICATE CARDS: before file_card or machine_task, scan
the snapshot for an ACTIVE card (backlog/working/review) already covering that
work - if one exists, STEER it with the new instruction instead of filing a
second; say which card you reused. File a new card only when nothing active
matches. Moving to review runs the quality gate (may bounce); moving
to done accepts and advances the process chain. dispatch:true files AND starts
the card immediately.

PLANNING DISCIPLINE (PMP, but in casual owner language - keep the friendly tone,
apply the rigor). When you plan, propose next steps, or summarize status, you
are the CONVERSATIONAL voice of the PM PLAN below - GROUND your answer in it, do
not improvise a second plan. Every planning/status answer must:
  1. Lead with OPEN OWNER DECISIONS if any exist ("das brauche ich von dir: ...")
     - they BLOCK the plan. NEVER offer to "run all steps" while one is open;
     ask for the decision first.
  2. Separate what YOU (the agent) will do from what the OWNER must do (a human
     task like recruiting testers, an account/credential, an approval) - don't
     file an owner-only task as an agent card.
  3. Name the top 1-2 RISKS with a one-line response each (from the plan's risks).
  4. Give the honest FEASIBILITY in one line: do the pace/quota make the dates?
     (use the plan's triage + feasibility note - if a corner is red, say why).
  5. For each card you propose, give its "done_when" (1-2 acceptance criteria).
Keep it short and human - a founder reads it on a phone. If NO PM plan is
provided, say the goal isn't planned yet and offer to plan it, rather than
inventing milestones."""

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
                 "project/repo must include ONLY that repo's cards):")
    for t in sessions.list_tracks():
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
        lines.append("- id=%s repo=%s branch=%s lane=%s status=%s prio=%s due=%s mode=%s ai=$%.2f task=%s%s" % (
            t["id"], repo, t["branch"], t.get("lane"), t.get("status"), t.get("priority", "-"),
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
    d = _log()
    d.setdefault(user, []).extend(entries)
    d[user] = d[user][-80:]
    tmp = CHATLOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, CHATLOG)

_autocompact_supported = None    # None=unprobed, True/False learned from first /compact

# Replies that are etiquette, not answers - the exact strings (lowercased,
# terminal punctuation stripped) the model uses to wave off system turns.
# Deliberately narrow: "ok" is NOT here, it is the legitimate answer to the
# harness's own systemcheck turns.
_FILLER_REPLIES = {"no response requested"}

_compacting = set()              # users with a background compaction in flight


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
        window = max(st.get("ctx_window") or 0, sessions._CTX_WINDOW)
    except Exception:
        return
    if ctx < 0.8 * window or user in _compacting:
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
    sid = sess.get(user)
    # scale the mark with the DERIVED window (sessions._maybe_compact parity):
    # a fixed 160k made a 1M-tier PM session probe /compact at ~16% real fill.
    window = max(st.get("ctx_window") or 0, sessions._CTX_WINDOW)
    if ctx < 0.8 * window or not sid:
        return None
    # the external /compact turn resumes the SAME session id - a live warm
    # process on it would fork the conversation. Drop it first; the next chat
    # turn respawns on the compacted tip.
    _persist_drop(user)
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
        sess[user] = sid_final
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
    _save_stats(all_st)
    if after <= ctx * 0.75:                     # a real compaction frees a big chunk
        _autocompact_supported = True
        return ("AUTO-COMPACT: Kontext war bei %d%% (~%dk) - Verlauf verdichtet, "
                "jetzt ~%dk. Es geht ohne Unterbrechung weiter."
                % (pct, round(ctx / 1000), round(after / 1000)))
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
    return {"messages": _log().get(user, []),
            "session_id": _sessions().get(user),
            "stats": st}


def say(text, cls="pm"):
    """THE harness's voice in the owner's board chat - the one place anything
    non-interactive speaks to the owner (pm._say and the lane pipeline both go
    through here). Without this, work that happens without the owner typing
    (a gate verdict, a merge, a bounce) only ever reached the flight recorder
    and the event log, so the chat looked frozen while the daemon worked.
    Best-effort by design: never let a chat write break the work it reports."""
    try:
        from spine.auth import auth
        owner = next((u["name"] for u in auth.list_users() if u.get("role") == "owner"), None)
        if not owner:
            return
        _append_log(owner, [{"cls": cls, "text": text, "ts": time.strftime("%H:%M")}])
    except Exception:
        pass

# live copilot subprocess per user, so the chat's Stop button can kill a turn.
_running = {}
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
    return {"text": _rd("live_partial.txt"), "thinking": _rd("live_thinking.txt"),
            "running": user in _running}


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
    # the next turn respawns clean (--resume keeps the conversation)
    _persist_drop(user)
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
         _retried=False):
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

    voice_stream=True renders the prose to speech SENTENCE BY SENTENCE as it is
    generated, into the per-user chunk list `/chat/live` serves - so voice mode
    starts talking a second into the turn instead of after it. Opt-in per
    request, not a server setting: a client that does not poll for the chunks
    must keep getting the one-shot `voice:true` clip instead, or an app that is
    one OTA behind would go silent (see spine/media/voice_stream.py)."""
    from spine.agent import turnopts
    sess = _sessions()
    sid = sess.get(user)
    paths = turnopts.save_attachments(os.path.join(ROOT, ".copilot_attachments", user),
                                      attachments)
    # "" (no explicit pick) routes as Auto - never falls through to the CLI's
    # global default, which is whatever the owner's interactive /model was
    # last set to (the same leak fixed in sessions._turn, 2026-08-14).
    cli_model, _ = turnopts.resolve_model(model or "auto", message, bool(paths))
    body = turnopts.augment_prompt(message, thinking, paths)
    focus = ""
    if card:
        ct = _find_card(card)
        if ct and not isinstance(ct, list):
            focus = ("\n\nCURRENT CARD (the user is viewing this - resolve 'this card' / 'it' "
                     "to it; a plain work instruction means steer it): %s | %s | %s"
                     % (ct["id"], ct.get("branch"), (ct.get("task") or "")[:80]))
    _plan = _pm_plan_digest()
    # The ROLE is data now: harness/agents/board-copilot.md. SYSTEM above stays as
    # the built-in fallback, so a mangled/absent file costs the customisation and
    # never the chat turn.
    from spine.registry import harness
    system = harness.brief("board-copilot", default=SYSTEM) or SYSTEM
    if extra_system:
        system = system + "\n\n" + extra_system
    turn = "BOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M") \
        + _snapshot() + (("\n\n" + _plan) if _plan else "") \
        + focus + "\n\nUSER (%s): %s" % (user, body)
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
            base_system = harness.brief("board-copilot", default=SYSTEM) or SYSTEM
            p, _fresh = _persist_get(user, cli_model, sid, base_system)
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
                _persist_drop(user)
                base_system = harness.brief("board-copilot", default=SYSTEM) or SYSTEM
                p, _fresh = _persist_get(user, cli_model, sid, base_system)
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
        if persistable and (user in _cancelled or p.poll() is not None):
            # a cancelled or dead process must not be reused - next turn
            # respawns via --resume and loses nothing but the warmth
            _persist_drop(user)
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
        sess[user] = sid_final
        _save_sessions(sess)
    reply_prose, acts_parsed = _parse_reply_actions(txt)
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
                    voice_stream=voice_stream, _retried=True)
    out = {"reply": reply_prose, "actions": acts_parsed}
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
    entries = [{"cls": "you", "text": message, "ts": time.strftime("%H:%M")},
               {"cls": "bot", "text": out.get("reply", ""), "ts": time.strftime("%H:%M"), "usage": usage}]
    if rotate_note:
        entries.append({"cls": "error", "text": rotate_note, "ts": time.strftime("%H:%M")})
    _append_log(user, entries)
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
        _append_log(user, [{"cls": "error",
                            "text": "advisory surface: %d board action(s) NOT run (%s)"
                                    % (len(acts), ", ".join(refused)),
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
                _append_log(user, [{"cls": "act", "text": r} for r in done])
        threading.Thread(target=_run_bg, daemon=True, name="copilot-actions").start()
    return {"reply": out.get("reply", ""), "actions": [], "refused": refused,
            "cost": d.get("total_cost_usd"), "usage": usage}
