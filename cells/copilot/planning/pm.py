# -*- coding: utf-8 -*-
"""PM / CTO planning ROLE, run by the thin harness here.

The PM's brain is DATA (cells/copilot/harness/agents/pm.md + settings.pm), not code. This module only:
  - gathers signals (board + REAL economics + quota/velocity + goal),
  - runs the configured role for ONE plan-mode turn,
  - prices/times the plan in code (LLM judges effort in turns, code converts to
    days at the measured velocity and to shadow-€ at the real cost/turn),
  - writes a reviewable artifact,
  - and hands the actionable items to whoever executes (the night ticker).

On a flat plan (settings.pm.plan == "max") the bottleneck is quota-TIME, not €,
so timelines are in DAYS and the € is leverage/ROI, not cash. Nothing here
executes work; turning items into cards stays an explicit, gated step.
"""
import json, math, os, re, subprocess, threading, time

from spine.registry import i18n as _i18n

from daemon.paths import DAEMON_ROOT as ROOT
# Plan artifacts, activity and loop state are db rows since state-into-db
# phase D (ledger step 7 imported daemon/pm/*) - there is no PLANS dir.

PM_DEFAULTS = {
    "goal": "",
    # "auto" detects the plan from the CLI's real auth (events.plan_effective:
    # subscription login -> "max", API key / Console login -> "api"); the
    # explicit values stay as owner overrides.
    "plan": "auto",             # "auto" | "max" (flat quota) | "api" (per-token €) | "mixed"
    "monthly_eur": 200,
    # the weekly plan allowance in TOKENS, if the owner knows it. 0 = derive it
    # from the live usage window (events.plan_calibration), which is how cost
    # surfaces turn a card's tokens into "% of the subscription".
    "plan_tokens_week": 0,
    "quota_turns_per_day": 0,   # 0 = derive pace from measured velocity
    "role_extra": "",           # house additions appended to the role charter
    # -- the single proactive loop (absorbs the old nightshift ticker) --
    "loop_enabled": False,      # proactive loop off until the owner turns it on
    "repos": [],                # safety allowlist: repos the PM may act in
    "window": "",               # "" / "always" = whenever idle; "HH:MM-HH:MM" restricts
    "idle_minutes": 20,         # you must be away this long before the PM acts
    "replan_minutes": 120,      # re-run the PM plan (LLM) at most this often
    "max_dispatch_per_day": 3,  # cap on autonomous dispatches/day (quota guard)
    # escalation ladder (LangChain ambient-agents / Horvitz mixed-initiative):
    #   "notify" = only refresh the plan, change nothing (advise-only)
    #   "ask"    = also file backlog cards (reversible), but never auto-dispatch
    #   "act"    = also dispatch within the WIP/quota gates (merge/accept stay gated)
    "autonomy": "act",
    # -- per-card budget watchdog (_cost_watch: code thresholds, no LLM) ------
    "watch_base_pct": 5.0,      # BAC of a MEDIUM card: absolute % of the plan budget
    "watch_reserve_pct": 40.0,  # management reserve: share never allocated to cards
    "watch_floor_tokens": 2_000_000,  # fallback ladder in TOKENS - the one honest unit
                                       # left when no €/% calibration is reachable at all
                                       # (owner decree 2026-09-04: never a shadow-$ price)
    "watch_ctx_floor": 150_000, # context tokens considered runaway (window nearly full)
    # -- per-turn spend tripwire (drivers._turn_burn_check: code thresholds,
    # folded live off the stream, no LLM judgement on the arithmetic) --------
    "turn_burn_soft_pct": 2.0,  # %-of-weekly-quota ONE turn may burn -> Henry ("turn-burn", can steer)
    "turn_burn_hard_pct": 5.0,  # %-of-weekly-quota ONE turn may burn -> cooperative cancel, needs_you
}


def _pm():
    from spine.storage import events
    c = dict(PM_DEFAULTS)
    c.update(events.settings().get("pm") or {})
    return c


def get_goal():
    return (_pm().get("goal") or "").strip()


def set_goal(goal):
    from spine.storage import events
    pm = dict(events.settings().get("pm") or {})
    pm["goal"] = (goal or "").strip()
    events.save_settings({"pm": pm})
    return pm["goal"]


# -- CLARIFICATIONS: the owner answers a PM question straight in chat ---------
# brief() only ever read the goal text + the live board - an owner reply to an
# open_question in chat was heard (the copilot replied) but never reached the
# planner, so the NEXT plan repeated the same question. This is the fix: the
# chat action "clarify_goal" (copilot._run_action) calls add_clarification(),
# which is folded into every brief() prompt as ground truth until the goal
# text itself changes (a new goal invalidates old answers - set_goal clears
# them). Small, capped, persisted in the same loop.json the PM already owns.
_CLARIFY_MAX = 12


def add_clarification(text, actor="owner"):
    text = (text or "").strip()
    if not text:
        return []
    with _resolving_lock:
        st = _loopstate()
        cl = st.setdefault("clarifications", [])
        cl.append({"text": text[:500], "at": time.strftime("%Y-%m-%d %H:%M"), "actor": actor,
                   "goal": get_goal()})
        st["clarifications"] = cl[-_CLARIFY_MAX:]
        _save_loopstate(st)
        return st["clarifications"]


def _clarifications_block():
    """Only clarifications recorded against the CURRENT goal text - a goal edit
    (set_goal) makes prior answers stale, so they drop out here rather than
    misleading a re-scoped plan."""
    goal = get_goal()
    cl = [c for c in (_loopstate().get("clarifications") or []) if c.get("goal") == goal]
    if not cl:
        return ""
    lines = ["\n\nOWNER CLARIFICATIONS (answered live in chat - trust these as GROUND TRUTH, "
             "they supersede any guess/assumption in a prior plan or the snapshot):"]
    lines += ["  - %s (%s)" % (c["text"], c.get("at", "")) for c in cl]
    return "\n".join(lines)


def _role():
    # The role is DATA in the harness layer (cells/copilot/harness/agents/pm.md - owner-
    # editable, versioned). brief() is total: a missing/mangled file degrades
    # to the short JSON-shape floor in harness._DEFAULTS, never breaks a plan.
    from spine.registry import harness
    role = harness.brief("pm")
    extra = (_pm().get("role_extra") or "").strip()
    return role + ("\n\n## House additions\n" + extra if extra else "")


def economics():
    """Real spend/token/velocity facts, so estimates are grounded in THIS board."""
    from cells.engineer.cards import sessions
    from spine.storage import events
    from datetime import datetime
    tracks = sessions.list_tracks()
    m = events.metrics(tracks)
    spend = m["totals"]["ai_spend"]
    turns = sum(t.get("turns", 0) for t in tracks)
    toks = sum((t.get("tokens_in", 0) + t.get("tokens_out", 0)) for t in tracks)
    fmt = "%Y-%m-%d %H:%M:%S"
    created = []
    for t in tracks:
        try:
            created.append(datetime.strptime(t["created"], fmt))
        except (KeyError, ValueError, TypeError):
            pass
    span_days = 1.0
    if created:
        span_days = max(1.0, (datetime.strptime(time.strftime(fmt), fmt) - min(created)).total_seconds() / 86400.0)
    pm = _pm()
    # the RESOLVED plan ("max"/"api"), not the raw setting: _budget_assess picks
    # its bottleneck (quota windows vs € cap) off this, and with plan="auto" the
    # raw value names no plan at all. plan_source keeps the evidence visible.
    plan_eff, plan_src = events.plan_effective()
    return {
        "plan": plan_eff,
        "plan_source": plan_src,
        "plan_setting": pm.get("plan", "auto"),
        "monthly_eur": pm.get("monthly_eur", 200),
        "spend_to_date": round(spend, 4),
        "turns_to_date": turns,
        "tokens_to_date": toks,
        "avg_cost_per_turn": round(spend / turns, 4) if turns else 0.0,
        "avg_tokens_per_turn": round(toks / turns) if turns else 0,
        "active_days": round(span_days, 1),
        "velocity_turns_per_day": round(turns / span_days, 1) if turns else 0.0,
        "quota_turns_per_day": pm.get("quota_turns_per_day", 0),
        "value_delivered": m["totals"]["value_delivered"],
        "margin": m["totals"]["margin"],
        "capacity": m["capacity"],
        "spend_by_model": {k: v.get("cost", 0) for k, v in m["ai_by_model"].items()},
        "currency": events.settings().get("currency", "EUR"),
    }


def _system_state():
    """Real WORLD state the board otherwise can't see: what's been PROVISIONED
    OUTSIDE the card lanes (users/accounts, registration). A card agent that set
    up users changes the world, not a card's lane - and _snapshot() only carries
    lanes, so without this the planner re-scopes work that is already done (the
    'board didn't know about the users' gap). FACTS only; the planner and the
    gate derive scope from them, they are never a stamped verdict."""
    lines = []
    try:
        from spine.auth import auth
        users = auth.list_users()
        roles = {}
        for u in users:
            r = u.get("role", "?")
            roles[r] = roles.get(r, 0) + 1
        lines.append("USERS: %d Konto/Konten (%s)" % (
            len(users), ", ".join("%d×%s" % (n, r) for r, n in sorted(roles.items())) or "keine"))
    except Exception:
        pass
    try:
        from spine.storage import events
        reg = events.settings().get("registration")
        if reg:
            lines.append("REGISTRATION: " + json.dumps(reg, ensure_ascii=False)[:200])
    except Exception:
        pass
    return "\n".join(lines) or "(keine gesonderten System-Fakten)"


from cells.copilot.planning.pm_budget import (_pace, _days, _quota_signal, _budget_assess, _fmt_when,
                       _quota_floor, _goal_budget_text, _triage_green)
from cells.copilot.planning.pm_state import touch, _loopstate, _save_loopstate, _today, _in_window, _board_idle


# -- golden-triangle gate: extracted to pm_triangle.py (god-file breakup). --
# Re-imported here so every existing pm.<name> caller (routes_pm.py,
# sessions.py's on_card_done hook) stays unchanged.
from cells.copilot.planning.pm_triangle import (
    live_plan, _gate_triangle, _triage_shape, on_card_done, _on_card_done,
    RECONCILE_PROMPT, reconcile_corner)


def _ask(prompt, model="", system="", hands=False, timeout=300):
    """ONE model turn, JSON out.

    hands=False (consolidation, reconcile): the old shape - plan
    mode, nothing to fetch, the whole prompt on stdin.

    hands=True (brief, 2026-09-12 "planner-with-hands"): the ROLE goes in as
    the system prompt (a stable prefix - the same bytes every run, so the
    API's prompt cache can hit; volatile facts never ride in it), the turn
    text on stdin, and the planner gets the pm.json settings layer: a
    pre-approved evidence wrapper (hd.py -> board_state.py --find/--card,
    henry_memory_get.py find/get, git log) in permission-mode AUTO. Owner
    decree 2026-09-12 ("offen bleiben, nicht ploetzlich eingeschraenkt"):
    the first cut ran `default`, where anything NOT allowlisted dies
    SILENTLY in a headless -p (no prompt exists to answer) - the same
    trap Henry had under acceptEdits, and the planner then guessed instead
    of fetching. Auto lets Claude's classifier approve the unremarkable
    (any read, any git log spelling) and deny the risky, PC-wide; the
    secret deny-rules in pm.json still apply (measured in auto mode by
    spine/ops/probe_henry_guard.py --mode auto). The allowlist stays as a
    pre-approval of the exact wrapper form, nothing more.
    That is the fetch-as-needed half: history and memory are pulled
    by query when a claim needs them, never inlined. Measured 2026-09-12:
    without it the planner asked for a Play account that eight finished
    cards already documented.

    Returns the parsed dict; the CLI's own accounting (num_turns, usage,
    cost) rides along under `_meta` so the artifact can show what the turn
    actually fetched and spent - the rating input, measured not assumed."""
    from cells.copilot.chat import copilot
    from spine.agent import drivers
    from spine.registry import harness
    # drivers._cmd_line, not ["cmd","/c",...] - the cmd.exe route mangles quoted
    # args on a .cmd shim (see drivers._real_claude_exe).
    argv = [copilot.CLAUDE, "-p", "--output-format", "json",
            "--permission-mode", "auto" if hands else "plan"]
    if model:
        argv += ["--model", model]
    if hands:
        if system:
            argv += ["--append-system-prompt-file", copilot._brief_file(system)]
        argv += harness.cli_args("pm")
    cmd = drivers._cmd_line(argv)
    env = None
    if hands:
        # The CLI's Bash/PowerShell tools inherit THIS process's PATH. Measured
        # 2026-09-12 (stream-json): in a stripped environment `py` was
        # "command not found" in Bash and "not recognized" in PowerShell, so
        # every evidence call died and the planner fell back to guessing.
        # Prepend the interpreter that runs the daemon and the Windows py
        # launcher dir, so `py -3.12 ...` resolves wherever the daemon does.
        # ONE owner since 2026-09-12: spawnenv.tool_path (same finding hit the
        # guard hook and Henry's broker the same day).
        from spine.agent.spawnenv import tool_path
        env = tool_path()
    cwd = _scratch_cwd() if hands else ROOT
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
        stdout, stderr = p.communicate(input=prompt, timeout=timeout)
    finally:
        if hands:
            import shutil
            shutil.rmtree(cwd, ignore_errors=True)
    if not (stdout or "").strip():
        raise RuntimeError("pm: no model output: " + (stderr or "").strip()[:200])
    d = json.loads(stdout)
    txt = d.get("result", "")
    meta = {"num_turns": d.get("num_turns"), "usage": d.get("usage"),
            "cost_usd": d.get("total_cost_usd"), "duration_ms": d.get("duration_ms")}
    m = re.search(r"\{.*\}", txt, re.S)
    out = None
    if m:
        try:
            out = json.loads(m.group(0))
        except ValueError:
            out = None
    if not isinstance(out, dict):
        out = {"summary": txt.strip()[:400], "milestones": [], "next": [], "risks": []}
    out["_meta"] = meta
    return out


# -- evidence protocol: the MECHANICS of fetch-as-needed (code), the WHEN is
# policy in pm.md. Relative paths because the planner's cwd is daemon/ - the
# exact strings pm.json allowlists, so a differently-spelled call would die
# silently in headless -p.
EVIDENCE_TOOLS = (
    "\n\nEVIDENCE TOOLS (run them with the PowerShell tool, read-only, pre-approved in exactly this form; "
    "your cwd is a scratch folder that holds only hd.py):\n"
    "    py -3.12 hd.py board --find <term> [term ...]   # finished+live cards carrying ALL terms (outcome + reply)\n"
    "    py -3.12 hd.py board --card <id-fragment>       # ONE card in full\n"
    "    py -3.12 hd.py memory find <term> [term ...]    # Henry's memory notes carrying ALL terms, in full\n"
    "    py -3.12 hd.py memory get <name>                # one note by index name\n"
    "    py -3.12 hd.py log                              # what actually shipped lately (git log, 30 lines)\n"
    "FIRST CALL, always: `py -3.12 hd.py memory find owner` - every note naming a delivery or "
    "decision that WAITS ON THE OWNER (a demo video, an approval, a go) is a launch blocker candidate; the oldest "
    "unresolved one is critical_path step 1 with who=du. Measured 2026-09-12: the plan asked about test automation "
    "while the iOS resubmission had been waiting two days on the owner's iPhone demo video, recorded in memory.\n"
    "Budget: at most 8 tool calls. Search BEFORE you assume or ask - the board below is the LIVE slice only; "
    "%d finished/archived cards and the memory notes are behind these tools, and that is where the answer to "
    "'has X already been done/decided' lives. Never Read a file path directly; never write anything - a tool "
    "answer is already the smallest slice that answers the question, there is nothing worth dumping to a file."
)


# The ONE script the planner's scratch cwd contains. It dispatches to the
# real read-only tools by ABSOLUTE path (spaces in the repo path never touch
# a permission rule: the allowlisted command is always `py -3.12 hd.py ...`)
# and runs git in the repo. Generated per spawn, so the baked-in root is
# always this daemon's.
_WRAPPER = """# -*- coding: utf-8 -*-
# HelmDeck PM evidence wrapper - generated per planning turn, read-only.
import os, subprocess, sys
REPO = %(repo)r
TOOLS = os.path.join(REPO, "ops", "tools")


def run(argv, cwd=None):
    r = subprocess.run(argv, cwd=cwd or REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    sys.stdout.write(r.stdout)
    if r.returncode:
        sys.stdout.write(r.stderr)
    return r.returncode


a = sys.argv[1:]
if a and a[0] == "board" and len(a) > 1 and a[1] in ("--find", "--card", "--live"):
    sys.exit(run([sys.executable, os.path.join(TOOLS, "board_state.py")] + a[1:]))
if a and a[0] == "memory" and len(a) > 1 and a[1] in ("find", "get", "list"):
    sys.exit(run([sys.executable, os.path.join(TOOLS, "henry_memory_get.py")] + a[1:]))
if a and a[0] == "log":
    sys.exit(run(["git", "-C", REPO, "log", "--oneline", "-n", "30"]))
sys.stdout.write("usage: hd.py board --find|--card ... | memory find|get ... | log\\n")
sys.exit(2)
"""


def _scratch_cwd():
    """A fresh, empty working directory OUTSIDE the repo for one planning
    turn, holding only hd.py. The trigger of state-into-db (2026-09-11
    22:01Z): the planner dumped `board_state.py --full` to a file so it could
    grep it, the prefix allowlist cannot see a `>` redirect, and cwd was
    daemon/ - so the dump landed in the repo. Whatever a turn writes now lands
    here and is removed with the directory."""
    import tempfile
    from daemon.paths import REPO_ROOT
    d = tempfile.mkdtemp(prefix="hd-pm-")
    with open(os.path.join(d, "hd.py"), "w", encoding="utf-8") as f:
        f.write(_WRAPPER % {"repo": REPO_ROOT})
    return d


def _memory_index():
    """Henry's memory INDEX (names + one-liners, ~4k chars) - progressive
    disclosure: the note itself is fetched with `find`/`get` only when it
    turns out to matter. The PLANNER's own context; Henry's board turn no
    longer auto-carries this (card chat-henry-kontext-pruning, "voller
    Umbau" - he pulls it himself via henry_memory_get.py get MEMORY)."""
    try:
        from cells.copilot.chat import copilot_memory
        return copilot_memory.digest()
    except Exception:                                            # noqa: BLE001
        return ""


def _hidden_history_count():
    """How many cards the LIVE snapshot hides (finished + archived) - the
    number the planner is told to go fetch behind, so 'history exists' is a
    measured fact in the prompt, not a hope."""
    try:
        from cells.engineer.cards import sessions
        return sum(1 for t in sessions.list_tracks()
                   if not t.get("example") and (t.get("archived") or t.get("lane") == "done"))
    except Exception:                                            # noqa: BLE001
        return 0


def _write_artifact(out):
    """One plan per day (pm_plans row keyed by day - a re-plan the same day
    replaces it, exactly as the plan-YYYYMMDD.json file did)."""
    try:
        from spine.storage import db
        db.pm_plan_put(time.strftime("%Y%m%d"), out)
    except Exception as e:                                       # noqa: BLE001
        print("pm: plan artifact not stored:", e)


def latest_plan():
    try:
        from spine.storage import db
        return db.pm_plan_latest()
    except Exception:                                            # noqa: BLE001
        return None


def _memory(prev, econ):
    """The PM's memory: its previous plan + a hard calibration signal (turns
    actually spent since, and progress) so it self-corrects instead of guessing
    fresh each time. Empty on the first ever plan."""
    if not prev:
        return ""
    lines = ["\n\nYOUR PREVIOUS PLAN (%s) - MEMORY. Compare against it: call out what "
             "SLIPPED or was mis-estimated, and CALIBRATE this plan's est_turns from "
             "what actually happened (don't just re-guess):" % prev.get("generated_at", "?")]
    lines.append("  prev done_pct: %s" % prev.get("done_pct"))
    pe = (prev.get("economics") or {}).get("turns_to_date")
    if pe is not None:
        lines.append("  turns actually spent SINCE that plan: %d" % max(0, (econ.get("turns_to_date", 0) or 0) - pe))
    pb = prev.get("budget") or {}
    if pb.get("est_turns_to_goal") is not None:
        lines.append("  you then estimated %s turns / ~%s days to goal - was that on track?"
                     % (pb.get("est_turns_to_goal"), pb.get("eta_days")))
    for m in (prev.get("milestones") or [])[:6]:
        lines.append("  - %s: was %s turns" % (m.get("name"), m.get("est_turns")))
    return "\n".join(lines)


def _reconcile_block(prev):
    """When the owner ran a corner reconciliation (reconcile_corner), the vetted
    EVIDENCE it gathered is fed back to the planner as FACTS to trust over the raw
    snapshot - so the re-plan actually re-scopes on the real world (e.g. 'users
    already set up' stops being counted as open scope)."""
    rec = (prev or {}).get("reconcile") or {}
    if not rec:
        return ""
    return ("\n\nRECONCILED EVIDENCE (the owner ran a check on a RED triangle corner - "
            "trust these observed FACTS over the snapshot when scoping):\n"
            + json.dumps(rec, ensure_ascii=False)[:1500])


# -- owner questions: one question, ONE identity ------------------------------
# An open question is a HARD dispatch gate now (pm_triangle._gate_triangle:
# non-empty open_questions blocks Scope), so the SAME question surfacing twice
# in different words doesn't just read as noise - two "blocked" reasons for
# one real ask. brief() self-dedupes its own list through this (the old
# verifier used to be the second source merged in here; it is gone, but a
# single planner turn can still repeat itself).
_Q_STOP = {
    # pure function words only, DE + EN. Quantifiers ("viele"), negations and
    # topic nouns deliberately stay: an over-eager stoplist collapses two
    # different questions into one and silently swallows the real one.
    "wie", "was", "wann", "wer", "wo", "warum", "wieso", "welche", "welcher", "welches",
    "welchen", "welchem", "ist", "sind", "war", "waren", "soll", "sollen", "muss",
    "muessen", "müssen", "kann", "koennen", "können", "hat", "hast", "haben", "wird",
    "werden", "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einer",
    "eines", "und", "oder", "fuer", "für", "mit", "von", "vom", "zum", "zur", "auf",
    "aus", "bei", "nach", "ueber", "über", "dir", "dich", "ich", "wir", "sie", "ihr",
    "dass", "dann", "denn", "sich", "auch", "als", "beim", "wenn",
    "what", "when", "who", "whom", "where", "why", "which", "how", "are", "was", "were",
    "does", "did", "the", "and", "for", "with", "from", "into", "that", "this", "there",
    "will", "would", "shall", "should", "can", "could", "has", "have", "had", "been",
    "you", "your", "our", "its", "any", "about",
}


def _q_tokens(q):
    """The CONTENT words of a question: casefolded, punctuation gone, pure
    function words dropped. Two wordings of the same ask land on the same set."""
    return {w for w in re.findall(r"\w+", (q or "").casefold())
            if len(w) >= 3 and w not in _Q_STOP}


# MEASURED, not reasoned (ops/tests/test_pm_clarifications.py pins both sides):
# on real PM question pairs the same ask reworded scores >= 0.571 Jaccard on its
# content words, while two DIFFERENT asks about the same object ("Budget fuer den
# Closed Test?" vs "Deadline fuer den Closed Test?") top out at 0.500. 0.55 is
# that gap - narrow on purpose, since a false merge loses a question the owner
# never gets asked (also reused by duplicate_titles() below, on card TITLES).
_Q_SAME = 0.55


def _same_question(a, b):
    """True when two owner questions ask the SAME thing. Equal after
    normalisation, or a near-duplicate: one's content words fully contained in
    the other's (>= 3 words, i.e. a more specific restatement of the same ask),
    or a _Q_SAME+ Jaccard overlap. Conservative on purpose - a false merge loses
    a question the owner never gets asked, which is worse than a duplicate line."""
    ta, tb = _q_tokens(a), _q_tokens(b)
    if not ta or not tb:                      # nothing but function words: fall back
        return (a or "").strip().casefold() == (b or "").strip().casefold()
    if ta == tb:
        return True
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) >= 3 and small <= big:
        return True
    return len(ta & tb) / float(len(ta | tb)) >= _Q_SAME


def _merge_questions(open_qs, must_ask):
    """Two question lists (or one list against an empty second one, for plain
    self-dedup) as ONE list with one entry per DISTINCT question. First
    wording wins; order is preserved so _needs_from_owner still asks the top
    question first."""
    out = []
    for q in list(open_qs or []) + list(must_ask or []):
        if not isinstance(q, str) or not q.strip():
            continue
        q = q.strip()
        if not any(_same_question(q, k) for k in out):
            out.append(q)
    return out


# -- duplicate-title check: SUGGEST, never judge -----------------------------
# pm-lean-advisor phase 3 (2026-09-04). A zero-model check that turns "two
# cards look the same" into a TAP, not a document. Its sibling goal_check
# (haiku, active titles only) was STRUCK 2026-09-13: it could not see done
# or archived cards, so it re-proposed shipped work ("Publish to Play Store")
# as missing - and Henry, who sees the whole board, answers "was fehlt zum
# Ziel?" better himself. The duplicate check goes through _ask_owner (the
# SAME tap-with-options channel PM budget/quota warnings already use) and
# remembers what it last asked, so a dismissed/ignored suggestion is
# not re-asked within the cooldown window - UX rule 4 ("abgelehnt = gemerkt").
# There is no separate accept/reject event to listen for (a tapped option
# routes to HENRY as an ordinary chat message, not back into this module), so
# "remembered" here means "not re-surfaced for a while", the honest thing
# code alone can guarantee without a second channel.
_SUGGEST_COOLDOWN_S = 24 * 3600


def _suggestion_due(sig):
    """True the FIRST time this exact suggestion signature is seen, or again
    once the cooldown has passed. Persisted in the same loop.json the PM
    already owns (pm_state._loopstate), so it survives a daemon restart."""
    st = _loopstate()
    seen = st.setdefault("suggestions_asked", {})
    last = seen.get(sig)
    if last and time.time() - last < _SUGGEST_COOLDOWN_S:
        return False
    seen[sig] = time.time()
    # cap growth: keep the 200 most recent signatures, oldest dropped first
    if len(seen) > 200:
        for k in sorted(seen, key=seen.get)[:len(seen) - 200]:
            seen.pop(k, None)
    _save_loopstate(st)
    return True


def _normalize_title(s):
    return " ".join(sorted(_q_tokens(s)))


def duplicate_titles():
    """PURE CODE, zero model cost: two ACTIVE cards whose titles are near-
    identical (same content-word set, via the same Jaccard machinery
    _same_question uses) are the one board-hygiene signal hard enough to
    surface without a human reading both bodies first - a shared title is
    evidence a title alone CAN give, unlike "is this card still needed"
    (Play-Store lesson: a title never proves a card is stale). Conservative
    by construction: _same_question already refuses to fire on two questions
    that merely share their object, so it refuses here too on two titles that
    merely share a topic."""
    from cells.engineer.cards import sessions
    tracks = [t for t in sessions.list_tracks()
              if not t.get("archived") and t.get("lane") != "done" and (t.get("task") or "").strip()]
    pairs = []
    for i, a in enumerate(tracks):
        for b in tracks[i + 1:]:
            if _same_question(a["task"], b["task"]):
                pairs.append((a, b))
    return pairs


def duplicate_check_async():
    """Fire-and-forget nudge; the check itself is free (no
    thread needed for the compute - only for _ask_owner's chat/push I/O, kept
    consistent with every other PM-speaks call)."""
    def run():
        try:
            for a, b in duplicate_titles():
                sig = "dup:" + "|".join(sorted([a["id"], b["id"]]))
                if not _suggestion_due(sig):
                    continue
                _ask_owner(
                    "Zwei Karten sehen fast identisch aus: „%s“ und „%s“. Zusammenlegen?"
                    % (a["task"][:70], b["task"][:70]),
                    ["Anzeigen", "Ignorieren"],
                    header="Mögliches Duplikat", card=a["id"])
                return   # one at a time - never more than one open question, see _ask_owner
        except Exception as e:
            print("pm: duplicate_check failed:", e)
    threading.Thread(target=run, daemon=True, name="pm-dup-check").start()


def _dispose_questions(raw):
    """(kept, evidence, dropped) from the planner's open_questions. Accepts
    both shapes - a plain string (legacy) and {"question", "checked"} - and
    KEEPS only questions that carry a non-empty `checked` trail (what was
    searched: tools run, notes/cards read). A bare string or an empty
    `checked` means the planner never looked, so it does not get to block
    the Scope corner on it; it lands in `dropped` (artifact + activity line)
    where the owner can still see what the planner wanted to know."""
    kept, evidence, dropped = [], {}, []
    for q in raw or []:
        if isinstance(q, dict):
            text = str(q.get("question") or "").strip()
            checked = q.get("checked")
            if isinstance(checked, (list, tuple)):
                checked = "; ".join(str(c).strip() for c in checked if str(c).strip())
            checked = str(checked or "").strip()
        else:
            text, checked = str(q or "").strip(), ""
        if not text:
            continue
        if checked:
            kept.append(text)
            evidence[text] = checked[:400]
        else:
            dropped.append(text)
    if dropped:
        _activity("planned", "Frage(n) ohne Belegsuche verworfen: %s"
                  % "; ".join(d[:80] for d in dropped[:3]))
    return kept, evidence, dropped


_STALE_Q_PLANS = 3


def _recent_plans(n):
    """The last n plan artifacts (oldest first), for measuring repetition.
    Read from the store each time - no stored counter to drift."""
    try:
        from spine.storage import db
        return db.pm_plans_recent(n)
    except Exception:                                            # noqa: BLE001
        return []


def _stale_question_guard(questions, prev):
    """A question the planner has now asked in >= _STALE_Q_PLANS consecutive
    plans without an answer is not going to be answered by asking again
    (measured: scope stayed blocked 12 days straight, 2026-09-01..12). Hand
    it to Henry - he has the chat, the memory and the owner - as ONE open
    exception (escalations dedupe by kind while it is open), instead of
    letting the gate sit red in silence. The question stays in the plan; this
    adds a route, it never removes the block."""
    if not questions:
        return
    history = _recent_plans(_STALE_Q_PLANS)
    if len(history) < _STALE_Q_PLANS:
        return
    for q in questions:
        if all(any(_same_question(q, k) for k in (h.get("open_questions") or [])
                   if isinstance(k, str)) for h in history):
            _to_henry("pm-question-stale",
                      "Der Planer stellt diese Frage seit %d Plaenen ohne Antwort - der Scope "
                      "bleibt deshalb rot und nichts wird gestartet: \u201e%s\u201c\n"
                      "Klaer sie: aus deinem Gedaechtnis/den Karten beantworten (dann als "
                      "clarify_goal festhalten) oder den Owner EINMAL konkret mit Optionen fragen."
                      % (_STALE_Q_PLANS, q),
                      feed="Frage seit %d Plaenen offen - an Henry: %s" % (_STALE_Q_PLANS, q[:80]))
            return


def brief(goal=None, model=""):
    """The PM/CTO report: milestones, next actions, risks. ONE model turn
    (pm-lean-advisor, 2026-09-04: the old verify/repair/re-verify loop - up
    to 4 turns, ~7 minutes, measured - was the self-verification anti-pattern
    research shows makes reasoning WORSE, not better; the endless-red
    Play-Store gate was its predicted symptom). `goal` overrides + persists
    the MVP goal. CODE, not this turn, now owns dates/triage/plan_status -
    see _gate_triangle in pm_triangle.py."""
    from cells.copilot.chat import copilot
    from spine.agent import turnopts
    from spine.storage import events
    if goal is not None and goal.strip():
        set_goal(goal)
    goal = (goal or "").strip() or get_goal()
    econ = economics()
    quota = _quota_signal()
    prev = latest_plan()      # MEMORY: read the last plan BEFORE we overwrite it
    cli_model, _ = turnopts.resolve_model(model or "auto", goal or "plan the mvp",
                                          False, signals={"priority": "high"})
    # SYSTEM = the role only (stable bytes, cacheable); TURN = every volatile
    # fact, the memory INDEX and the evidence tools (planner-with-hands,
    # 2026-09-12 - see _ask's docstring and EVIDENCE_TOOLS).
    system = _role()
    turn = ("GOAL:\n" + (goal or "(no goal set - infer a reasonable MVP from the board and debt)")
            + "\n\nPOLICY:\n" + json.dumps(events.settings().get("policy") or {})
            + "\n\nECONOMICS (real, to date):\n" + json.dumps(econ)
            + "\n\nQUOTA/BUDGET (live - judge budget-fit against THIS):\n" + json.dumps(quota)
            + "\n\nSYSTEM STATE (provisioned OUTSIDE the card lanes - derive scope from THIS too, "
              "not just the cards):\n" + _system_state()
            + _reconcile_block(prev)
            + _clarifications_block()
            + _memory(prev, econ)
            + _memory_index()
            + "\n\nBOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M") + copilot._snapshot()
            + EVIDENCE_TOOLS % _hidden_history_count())
    out = _ask(turn, cli_model, system=system, hands=True, timeout=900)

    # Effort in CODE: the LLM judges est_turns per milestone; code sums the
    # REMAINING work (done + calendar_wait milestones cost nothing - a wait is
    # not your throughput). No dates are derived here at all anymore - see
    # pm_triangle._eta_range, which turns this sum + measured pace into a
    # RANGE, never a single invented day.
    est_turns = 0
    for ms in out.get("milestones", []):
        done = str(ms.get("status")) == "done"
        tt = 0 if (done or ms.get("calendar_wait")) else int(ms.get("est_turns") or 0)
        ms["est_turns"] = int(ms.get("est_turns") or 0)
        est_turns += tt

    out["economics"] = econ
    # carry forward any owner-run corner reconciliations so the evidence persists
    # across re-plans (and stays visible to the NEXT brief's _reconcile_block).
    if (prev or {}).get("reconcile"):
        out["reconcile"] = prev["reconcile"]
    out["goal"] = goal
    out["model"] = cli_model or "default"
    out["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # Style law: clip LLM prose at the SOURCE so every surface inherits the cap.
    out["summary"] = _clip_prose((out.get("summary") or "").strip(), 300)
    # "Der Weg": the ONE thing StatusPanel shows standing (pm-lean-advisor
    # phase 3.1, 2026-09-04). Malformed/oversized entries degrade to nothing
    # rather than a half-rendered chain - the UI falls back to milestones.
    cp = []
    for step in (out.get("critical_path") or [])[:4]:
        if not isinstance(step, dict) or not str(step.get("step") or "").strip():
            continue
        who = step.get("who") if step.get("who") in ("du", "agent", "extern") else "agent"
        cp.append({"step": _clip_prose(str(step["step"]).strip(), 90), "who": who,
                   "why": _clip_prose(str(step.get("why") or "").strip(), 110),
                   "card": step.get("card") or None})
    out["critical_path"] = cp
    # self-dedupe (the planner can still repeat itself in one turn) - the old
    # verifier-vs-planner merge is gone with the verifier, the utility stays
    # useful for this narrower job (ops/tests/test_pm_clarifications.py pins it).
    # QUESTION DISCIPLINE (code disposes, 2026-09-12): a question reaches the
    # owner only with its evidence trail - what the planner searched and did
    # not find. An unchecked question is dropped (kept visible in the
    # artifact), and one the planner keeps asking plan after plan is handed
    # to Henry instead of blocking the gate in silence for another day.
    out["open_questions"], out["question_evidence"], out["dropped_questions"] = \
        _dispose_questions(out.get("open_questions"))
    out["open_questions"] = _merge_questions(out["open_questions"], [])
    _stale_question_guard(out["open_questions"], prev)
    out["evidence"] = {k: v for k, v in (out.pop("_meta", None) or {}).items() if v is not None}
    # pm.py PROPOSES (milestones, scope, questions); pm_triangle DISPOSES -
    # plan_status/triage/gate/eta are entirely CODE-derived from here on,
    # never re-graded by a second model pass. Scope is blocked exactly when
    # open_questions is non-empty: an unresolved owner decision IS the
    # unbounded scope, measured rather than a second LLM's opinion about it.
    _gate_triangle(out, econ, est_turns, pace=_pace(econ))
    _write_artifact(out)
    return out


def _epic_description(ms):
    """The PMP-scoped, owner-language body for ONE epic card: a user story,
    acceptance criteria (Definition of Done), why it's next, and the work
    breakdown (WBS) as an in-card checklist - never separate tickets. No card
    ids, file paths, or internal jargon; the owner reads this cold."""
    parts = []
    story = (ms.get("user_story") or "").strip()
    if story:
        parts.append("NUTZERGESCHICHTE\n" + story)
    done_when = [str(d).strip() for d in (ms.get("done_when") or []) if str(d).strip()]
    if done_when:
        parts.append("FERTIG, WENN\n" + "\n".join("- " + d for d in done_when))
    why_now = (ms.get("why_now") or "").strip()
    if why_now:
        parts.append("WARUM JETZT\n" + why_now)
    steps = [str(s).strip() for s in (ms.get("steps") or []) if str(s).strip()]
    if steps:
        parts.append("ENTHÄLT\n" + "\n".join("- " + s for s in steps))
    return "\n\n".join(parts) or (ms.get("name") or "")


def plan_items(b=None):
    """The actionable NEW epics from a brief (milestones not yet on the board),
    ordered by priority - what an executor (the night ticker) should file as
    cards. ONE card PER MILESTONE (epic): its steps stay a checklist inside
    that card, not separate tickets, so a card is a long-lived, context-rich
    chat instead of a fragment. Returns (items, brief). Each item:
    {title, description, priority, repo}."""
    from spine.storage import events
    b = b or brief()
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    default_repo = events.settings().get("default_repo") or ""
    items = []
    for ms in b.get("milestones", []):
        if str(ms.get("status")) == "done" or ms.get("card"):
            continue
        title = (ms.get("name") or "").strip()
        if not title:
            continue
        items.append({"title": title,
                      "description": _epic_description(ms),
                      "priority": ms.get("priority", "medium"),
                      "repo": ms.get("repo") or default_repo})
        # no due date is set here or anywhere else from a milestone
        # (pm-lean-advisor, 2026-09-04): dates are retired entirely, see
        # pm_triangle._eta_range for the one remaining, code-derived ETA.
    items.sort(key=lambda x: order.get(x.get("priority"), 2))
    return items, b


# -- Phase 3: stream-card consolidation (propose -> confirm -> merge) ---------
# Fewer, bigger, context-rich cards: 2-5 durable STREAM cards per repo
# (backend / ux / feature / infra / docs), so a card is a long-lived chat with
# context - not a pile of micro-tickets that fragment it. The PM PROPOSES the
# mapping (read-only); applying it is explicit and NON-DESTRUCTIVE (members are
# reversibly archived, their gist rolled into the stream card).

_CONSOLIDATE_ASK = """The board has too many small cards, which fragments context.
Propose consolidating the BACKLOG cards into 2-5 durable STREAM cards PER REPO
(streams: backend / ux / feature-<x> / infra / docs). For each stream give a
clear title and the EXISTING backlog card ids that roll into it. Leave
working/review/done cards alone. Prefer FEW streams. Reply with ONLY JSON:
{"repos":[{"repo":"<abs repo path>","streams":[
  {"name":"backend","title":"<stream card title>","members":["<card id>", ...],"why":"<one line>"}]}]}"""


def consolidation_proposal(model=""):
    """Read-only: the PM's proposed roll-up of backlog cards into stream cards."""
    from cells.copilot.chat import copilot
    from spine.agent import turnopts
    cli_model, _ = turnopts.resolve_model(model or "auto", "consolidate the board",
                                          False, signals={"priority": "high"})
    prompt = _CONSOLIDATE_ASK + "\n\nBOARD SNAPSHOT:\n" + copilot._snapshot()
    out = _ask(prompt, cli_model)
    return {"repos": out.get("repos", []) if isinstance(out, dict) else [],
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def apply_consolidation(repos, actor="owner"):
    """Non-destructive: create each stream card, then REVERSIBLY archive its
    BACKLOG members (their titles roll into the stream card's description).
    Members that are not in backlog are refused and reported, never archived -
    a roll-up may not sweep a card somebody is actually working. Returns what
    changed so the caller can show/undo it."""
    from cells.engineer.cards import sessions
    tracks = {t["id"]: t for t in sessions.list_tracks()}
    created, archived, refused = [], [], []
    for rp in repos or []:
        repo = rp.get("repo") or ""
        if not repo:
            continue
        for st in rp.get("streams", []):
            # _CONSOLIDATE_ASK says "Leave working/review/done cards alone" -
            # but that was only ever a PROMPT, and this loop archived whatever
            # ids came back. One slipped active card is invisible afterwards:
            # archiving hides it from every board view but the Archive scope,
            # and it stays needs_you forever because nothing works an archived
            # card (turn/blockers.py skips them). The rule the proposal is
            # asked to follow is enforced here instead of hoped for.
            wanted = [m for m in (st.get("members") or []) if m in tracks]
            members = [m for m in wanted
                       if (tracks[m].get("lane") or "backlog") == "backlog"
                       and not tracks[m].get("archived")]
            refused += [m for m in wanted if m not in members]
            if not members:
                continue
            rolled = "\n".join("- " + (tracks[m].get("task") or "") for m in members)
            body = ("Stream-Karte (%s) - kontextreich, langlebig.\n\nEingerollte Tickets:\n%s"
                    % (st.get("name") or "stream", rolled))
            slug = re.sub(r"[^a-z0-9]+", "-", (st.get("name") or "stream").lower())[:20]
            nt = sessions.new_track(repo, "stream-" + slug,
                                    st.get("title") or st.get("name") or "Stream",
                                    lane="backlog", description=body,
                                    priority="medium", actor=actor)
            created.append({"id": nt["id"], "title": nt.get("task"), "members": members})
            for m in members:
                try:
                    sessions.archive_track(m, on=True, actor=actor)
                    archived.append(m)
                except Exception:
                    pass
    # `refused` is reported, never silently dropped - a roll-up that quietly
    # left cards out would read as "all of it landed".
    return {"created": created, "archived": archived, "refused": refused}


# ============================================================================
# THE SINGLE PROACTIVE LOOP  (this replaced daemon/nightshift.py)
#
# Pattern: helpful, not nagging.
#   1. QUIET BY DEFAULT   - it updates the plan/board silently; silence = on-track.
#   2. PRESENCE-AWARE     - acts only while you are AWAY (idle >= idle_minutes) and
#                           backs off the moment you touch any surface; never
#                           competes for your attention or quota.
#   3. REVERSIBLE->AUTO   - it files + dispatches work within the WIP/quota gates
#      IRREVERSIBLE->ASK    (all reversible); merge/accept stay at the gate/human.
#   4. RATE-LIMITED       - a daily dispatch cap + a ~5h pause on the flat-plan
#                           quota signal (_limit_hit). Interrupts only for blockers.
#   5. ONE VOICE          - one loop, one plan artifact, one Dashboard digest.
# ============================================================================



def _limit_hit(track):
    """Flat-plan budget signal: the driver hit a usage limit. Prefer the
    structured subtype/error the driver surfaced; fall back to prose for legacy."""
    subtype = (track.get("last_subtype") or "").lower()
    if subtype:
        err = (track.get("last_error") or "").lower()
        return ("limit" in subtype or "usage limit" in err or "rate limit" in err
                or "limit reached" in err)
    txt = (track.get("last_reply") or "").lower()
    return "usage limit" in txt or "rate limit" in txt or "limit reached" in txt


def make_plan(actor="owner"):
    """Run the PM role now and file its NEW items as backlog cards (deduped).
    The reviewable brief is the day's plan artifact. One planning brain."""
    from cells.engineer.cards import sessions
    items, brief = plan_items()
    # When a goal is set it is managed as a PROCESS (epic): the process owns the goal-path
    # cards (step -> card, dated, in a SoW), built from THIS plan's vetted milestones once
    # triage is green. Keep the brief as the analysis artifact but never flat-file cards for
    # a goal - that was the duplication that left tickets unassigned.
    if get_goal():
        items = []
    have = {t.get("task", "").strip().lower() for t in sessions.list_tracks()}
    allow = {os.path.normcase(r) for r in (_pm().get("repos") or [])}
    filed = 0
    for it in items:
        repo = it.get("repo") or ""
        if not repo or not os.path.isdir(repo):
            continue
        if allow and os.path.normcase(repo) not in allow:
            continue                      # safety allowlist
        if it["title"].strip().lower() in have:
            continue
        sessions.new_track(
            repo, "pm-" + re.sub(r"[^a-z0-9]+", "-", it["title"].lower())[:24],
            it["title"], lane="backlog", description=it.get("description", ""),
            priority=it.get("priority", "medium"), actor="pm")
        filed += 1
        have.add(it["title"].strip().lower())
    st = _loopstate()
    st["last_plan"] = time.strftime("%Y-%m-%d %H:%M")
    st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
    _save_loopstate(st)
    summary = (brief.get("summary") or "").strip()
    _activity("planned", (("Geplant: %d neue Aufgabe(n) angelegt." % filed)
                          + ((" " + summary[:350]) if summary else "")) if filed
              else "Plan geprüft – nichts Neues nötig.")
    # DASHBOARD ONLY (owner decree 2026-08-30): filing cards is the PM doing its
    # job, not a decision for the owner - the new cards are on the board and the
    # line above is in the activity feed. The chat version carried 350 chars of
    # LLM plan summary on top, which is the "zu viel info" shape exactly.
    print("PM plan: %d Kandidaten, %d neue Karten" % (len(items), filed))
    return {"filed": filed, "candidates": len(items), "brief": brief}


def _notify_deliveries(day, tracks, st, pm):
    """Essential-only, rate-limited PUSH (the 'notify' channel): when a card the
    PM started DELIVERS (needs your review) or BOUNCES, ping ONCE. Silence
    otherwise - this is the proactive-not-nagging bit. NOT presence-gated: a
    delivery matters whether or not you're idle.

    A bounce is only escalated to you AFTER the coordinator has EXHAUSTED its
    delegation attempts (id in day['resolved']) - or immediately if autonomy isn't
    'act', when the PM won't auto-resolve. Every escalation carries a CONCRETE
    unblock proposal (_unblock_proposal), never just 'it is stuck'. The chat
    message goes out even without FCM - push is an extra channel, not the gate."""
    auto = pm.get("autonomy", "act")
    resolved = set(day.get("resolved", []))
    fcm = None
    try:
        from spine.comms import notify
        if notify.fcm_ready():
            fcm = notify
    except Exception:
        pass
    notified = set(day.setdefault("notified", []))
    disp = set(day.get("dispatched", []))
    changed = False
    for t in tracks:
        if t["id"] in notified:
            continue
        s = t.get("status")
        task = (t.get("task") or "").replace("\n", " ")[:60]
        if s == "needs_you" and t["id"] in disp and t.get("waiting_on") == "background":
            continue        # waiting on its OWN background task: not delivered and
                            # not the owner's move - stay quiet (Phase 2.5)
        if s == "needs_you" and t["id"] in disp and t.get("question"):
            # asking, not finished. notify.card_event already pushed this one
            # through the presence policy (and deduped it), so the PM only
            # speaks in chat here - a second push would defeat that policy.
            from spine.ops import ask
            _say(_i18n.t("pm.asking", task=task,
                         question=ask.summary(t["question"])[:140]))
            notified.add(t["id"]); changed = True
        elif s == "needs_you" and t["id"] in disp:
            if fcm:
                fcm.push_fcm(_i18n.t("push.pmDone"), _i18n.t("push.pmDoneBody", task=task), t["id"])
            _say(_i18n.t("pm.delivered", task=task))
            notified.add(t["id"]); changed = True
        elif s == "bounced" and (t["id"] in resolved or (auto != "act" and t["id"] in disp)):
            # escalate only once the coordinator gave up (or won't auto-resolve) -
            # and ALWAYS with a concrete next step attached
            prop = _unblock_proposal(t)
            if fcm:
                fcm.push_fcm(_i18n.t("push.pmStuck"),
                             _i18n.t("push.pmStuckBody", task=task, proposal=prop[:140]), t["id"])
            _say(_i18n.t("pm.stillStuck", task=task, proposal=prop))
            notified.add(t["id"]); changed = True
    if changed:
        day["notified"] = list(notified)
        _save_loopstate(st)


def _backlog(tracks, pm, day):
    """Dispatch candidates: un-started backlog cards in ALLOWED repos, prio-first."""
    allow = {os.path.normcase(r) for r in (pm.get("repos") or [])}
    rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        (t for t in tracks
         if t.get("lane") == "backlog" and t["id"] not in day.get("dispatched", [])
         and t.get("mode") not in ("human", "teach", "cowork")
         and not t.get("example")
         and (not allow or os.path.normcase(t.get("repo") or "") in allow)),
        key=lambda t: (rank.get(t.get("priority"), 2), t.get("created") or ""))


# -- RESOLVE + BURN GUARD: extracted to pm_resolve.py (god-file breakup). ----
# Re-imported here so every existing pm.<name> caller (routes_pm.py,
# processes.py's autopilot, sessions.flag_burn) stays unchanged.
from cells.copilot.planning.pm_resolve import (
    _RESOLVE_MAX, _resolving, _resolving_lock, _bounce_kind, _unblock_proposal,
    _bump_attempt, _give_up, _bounced_to_resolve, _resolve_next, mark_notified,
    _burn_lock, _burn_active, review_burn, _burn_judge, _push_burn,
    _review_burn, resolve_card_now, _resolve_card)


def _launch_checkin(pm, st):
    """Proactive coordinator question, ONCE per goal: surface the human-only
    launch prerequisites for the store deploy so the owner isn't the late
    bottleneck. The PM drives everything else itself. Re-asks only if the goal
    text changes (a new north star)."""
    goal = pm.get("goal") or ""
    if not any(k in goal.lower() for k in ("launch", "store", "android", "play", "deploy")):
        return
    if st.get("launch_asked") == goal:
        return
    st["launch_asked"] = goal
    _save_loopstate(st)
    _say(_i18n.t("pm.launchCheck"))



# _usage_checkin (the standalone quota-pacing notice to Henry) was REMOVED
# 2026-09-13: it had no caller in _tick() - never wired in after extraction -
# and _triangle_watch's own "Budget" corner already reads the SAME
# usage.weekly_pacing_flag() and reports it to Henry as part of the triangle
# escalation. Wiring the orphan back in would not have closed a gap, it would
# have doubled the same signal into two separate Henry escalations from one
# underlying number - exactly the kind of fan-out that turned today's single
# 86%-used reading into a false "at_risk" owner ask AND a false "erschöpft"
# triangle corner (see _stakeholder_update / _triangle_watch, same commit).


def _clip_prose(text, n):
    """Length NET under the style law (owner decree 2026-08-22 "sehr langer
    Text immer"): LLM-authored prose surfaced to the phone gets clipped at the
    last sentence boundary within n chars - the prompt asks for brevity, this
    guarantees it even when the model rambles."""
    if len(text) <= n:
        return text
    cut = text[:n]
    for stop in (". ", "! ", "? "):
        i = cut.rfind(stop)
        if i > n * 0.3:
            return cut[:i + 1]
    return cut.rsplit(" ", 1)[0] + " …"


_NOTICE_COOLDOWN_S = 24 * 3600


def _notice_due(st, name, key):
    """Anti-repeat gate for proactive notices (owner 2026-08-22 "wiederkehrende
    Nachrichten" + NN/g state-change-only law): speak when the SEMANTIC state
    changes (stable key, never LLM wording - a re-plan that rewords the same
    problem stays silent) or as a once-a-day heartbeat while it persists.
    key=None clears the episode so the NEXT occurrence speaks immediately."""
    slot = st.get("notice_" + name) or {}
    if key is None:
        if slot:
            st.pop("notice_" + name, None)
            _save_loopstate(st)
        return False
    if slot.get("key") == key and time.time() - (slot.get("at") or 0) < _NOTICE_COOLDOWN_S:
        return False
    st["notice_" + name] = {"key": key, "at": time.time()}
    _save_loopstate(st)
    return True


def _plan_gate_notice(st):
    """The planning GATE speaks: when the plan isn't 'ready' - a decision, a spike, or a
    prerequisite blocks a confident estimate - the PM says so plainly and holds, instead of
    pretending with a shallow schedule. Deduped on the STABLE state (which corners are
    red), not the wording - a re-plan that re-describes the same red stays silent.

    TO HENRY, not to the owner (owner decree 2026-08-30). The message's own
    closing move - "sag „prüfe Budget", dann hole ich die echte Evidenz zu der
    roten Ecke nach" - is work the harness can do without being asked, so
    routing it through the owner only added a hop and a bulleted issue list to
    a chat that wanted neither. The hold itself stays visible where a hold
    belongs: the dashboard's state/state_reason and the feed line below."""
    plan = latest_plan() or {}
    if not get_goal() or _triage_green(plan):     # gate is GREEN (or no goal) -> nothing to say
        _notice_due(st, "plan_gate", None)
        return
    tri = plan.get("triage") or {}
    red = [k for k in ("budget", "timeline", "scope") if tri.get(k) == "blocked"]
    # `gate` is CODE-authored now (pm_triangle._gate_triangle) - a short sentence
    # naming which measured corner is blocked and why, never a second model's
    # prose grading the first one's optimism.
    gate = _clip_prose((plan.get("gate") or "").strip(), 240)
    if not _notice_due(st, "plan_gate", "|".join(sorted(red)) or "noestimate"):
        return
    corner = {"budget": "Budget", "timeline": "Timeline", "scope": "Scope"}
    head = ("Ziel-Plan-Gate ROT — die Triage hält (%s). Kein Dispatch, bis das grün ist."
            % ", ".join(corner[c] for c in red) if red else
            "Ziel-Plan-Gate ROT — ich kann noch nicht seriös schätzen. Kein Dispatch, bis geklärt.")
    msg = head + ((" Gate: %s" % gate) if gate else "")
    if red:
        # never dead-end: name the actual move for THIS corner. Scope-red is
        # now measured directly from an unresolved open_question - point at
        # answering it, not at re-investigating evidence that isn't the issue.
        if "scope" in red:
            oq = next((q for q in (plan.get("open_questions") or []) if isinstance(q, str) and q.strip()), "")
            msg += ("\nOffene Entscheidung, die den Scope blockiert: %s" % oq if oq else
                    "\nHenry: eine offene Entscheidung blockiert den Scope - klär sie mit dem Owner.")
        else:
            msg += ("\nHenry: „prüfe %s“ holt die echte Evidenz zu der roten Ecke nach "
                    "und plant damit neu." % corner[red[0]])
    _to_henry("plan-gate-red", msg,
              feed="Plan-Gate ROT (%s) - kein Dispatch, an Henry"
                   % (", ".join(corner[c] for c in red) or "keine Schätzung"))


def _needs_from_owner(st):
    """The PM ASKS instead of silently guessing: surface the plan's open_questions
    (material info the PM is missing) to the owner. Best-effort planning still needs
    answers a good PM chases. Deduped by content, so the same set isn't re-asked every
    plan - it re-asks only when the questions actually change, and stays silent when
    the plan has none."""
    plan = latest_plan() or {}
    qs = [q.strip() for q in (plan.get("open_questions") or []) if isinstance(q, str) and q.strip()]
    # STABLE key: goal + how many questions - a re-plan that merely REWORDS the
    # same asks stays silent; a genuinely new question (count grows) speaks.
    if not _notice_due(st, "questions", ("%s|%d" % (get_goal(), len(qs))) if qs else None):
        return
    # ONE question, not a bulleted five (owner decree 2026-08-30). This notice
    # STAYS in the chat - a missing answer is by definition the owner's move and
    # nothing else on the board can supply it - but a list of five asks is a form,
    # not a question, and the owner answered none of them. Asking the first and
    # re-asking as the set changes (the _notice_due key counts them) walks the
    # same list one answerable step at a time; the full set stays on the plan.
    # The question goes in WHOLE - the [:180] that stood here was a raw slice
    # that could land inside a word, and the chat has no length budget to
    # justify it (2026-08-30; spine/comms/notice.short's docstring says where a
    # clip does belong). Brevity here comes from asking ONE question - the line
    # above - not from cutting it in half.
    more = (" (%d weitere im Plan.)" % (len(qs) - 1)) if len(qs) > 1 else ""
    _say("Mir fehlt Info: %s%s" % (qs[0], more))


def _triangle_watch(st):
    """Management by exception: between the DAILY plans, inspect the iron triangle
    (Budget / Timeline / Scope) against today's baseline and ESCALATE to the owner the
    moment a corner tilts. Daily planning sets the baseline; this is the ongoing monitor.
    Deduped by the tilt's content; clears itself when the triangle is level again."""
    corners = []
    # BUDGET — the weekly quota is burning ahead of pace
    try:
        from spine.ops import usage
        bf = usage.weekly_pacing_flag()
    except Exception:
        bf = None
    if bf and bf.get("reset_risk"):
        # weekly_pacing_flag() also fires on used_pct >= 85 alone, or on a
        # bare exhaust_before_reset with NO noise buffer (see spine/ops/
        # usage.py pacing() - reset_risk is the one field that carries
        # both: proj >= 105% AND exhaust_before_reset). Two measured false
        # positives if read loosely: 2026-09-13 86% used/2.8h to reset/proj
        # 87.5% (used>=85 alone), and 2026-09-14 06% into a FRESH window
        # with proj 100.7% - exhaust_before_reset was True on pure noise,
        # no buffer. Only reset_risk means "vor dem Reset erschöpft" is true.
        corners.append("Budget: Wochenkontingent voraus (projiziert ~%s%%, vor dem Reset erschöpft)"
                       % round(bf.get("projected_pct") or 0))
    # TIMELINE + SCOPE — from the goal's process (epic)
    gp = st.get("goal_process") or {}
    if gp.get("pid") and gp.get("goal") == get_goal():
        try:
            from cells.engineer.chains import processes
            p = processes.get(gp["pid"])
        except Exception:
            p = None
        if p:
            steps = p.get("steps") or []
            today = time.strftime("%Y-%m-%d")
            overdue = [s for s in steps if s.get("status") != "done" and (s.get("due") or "9999") < today]
            if overdue:
                corners.append("Timeline: %d Schritt(e) über Termin (z. B. „%s“ seit %s)"
                               % (len(overdue), (overdue[0].get("title") or "")[:40], overdue[0].get("due")))
            base = st.get("scope_baseline")
            if not base or base.get("goal") != get_goal():
                st["scope_baseline"] = {"goal": get_goal(), "n": len(steps)}   # self-baseline
                _save_loopstate(st)
            elif len(steps) > base.get("n", len(steps)):
                corners.append("Scope: %d neue Schritt(e) seit Baseline (%d → %d)"
                               % (len(steps) - base["n"], base["n"], len(steps)))
    # STABLE key: WHICH corners tilt (the prefix before ':'), never the numbers
    # in the text - a projection drifting 108%->111% is the same escalation.
    kinds = "|".join(sorted(c.split(":", 1)[0] for c in corners)) if corners else None
    if not _notice_due(st, "triangle", kinds):
        return
    # TO HENRY (owner decree 2026-08-30). "Welche Ecke ist dir heilig
    # (Zeit/Budget/Scope)?" is not a decision the owner can make from a bullet
    # list of drifts - it is the question a PM answers himself from context and
    # only escalates once he has a concrete trade to propose. Henry has that
    # context and the hands; if he concludes the owner really must choose, he
    # wakes him with ONE question, which is what his mandate already says.
    msg = ("Dreieck schief - Abweichung von der Tages-Baseline:\n"
           + "\n".join("• " + c for c in corners)
           + "\nGegensteuern (Prioritäten, Dispatch, Scope) oder dem Owner EINE konkrete "
             "Trade-off-Frage stellen - keine Statistik weiterreichen.")
    _to_henry("triangle-tilt", msg,
              feed="Dreieck schief (%s) - an Henry" % kinds.replace("|", ", "))


# -- per-card budget watchdog: extracted to pm_watchdog.py (god-file breakup).
# Re-imported here so every existing pm.<name> caller stays unchanged.
from cells.copilot.planning.pm_watchdog import (
    _WATCH_PRIO, _watch_budget_ctx, _watch_bac_pct, _cost_watch)


# -- goal->process (PMP epic): extracted to pm_goal.py (god-file breakup). --
# Re-imported here so every existing pm.<name> caller stays unchanged.
from cells.copilot.planning.pm_goal import (
    _goal_has_process, _goal_process, _goal_process_status)


def _stakeholder_update(st):
    """PMP core: reconcile GOAL vs BUDGET against the LIVE weekly quota. Managing
    goal-vs-budget IS the PM's primary job - but INFORMING is not the same as
    INTERRUPTING, and this notice is the one the owner quoted back (2026-08-30):

      "Diese Karte sollte in der Form nicht mehr im Chat sein. Zu viel info..
       bzw ich weiss nicht was ich dazu machen soll."

    He was right about the whole class. The daily "Ziel vs. Budget" block was
    five sentences of projections - used%, projected%, reset time, turns open,
    ETA, pace, feasibility, milestone counts - and on-track or tight there is
    no move in any of them. So:

      on_track / tight -> the DASHBOARD (activity feed + the PM panel, which
                          already renders the same numbers as a panel rather
                          than as prose). Silent in the chat.
      at_risk          -> ONE line and two BUTTONS. This one IS his call: the
                          quota runs out before the reset, and only he can say
                          whether non-goal work gets held or the goal slips.

    The daily/risk dedup below is unchanged - what changed is the CHANNEL, not
    when the PM considers this news."""
    goal = get_goal()
    if not goal:
        return
    try:
        from spine.ops import usage
        snap = usage.snapshot()
    except Exception:
        return
    weekly = None
    if snap.get("status") == "ok":
        weekly = next((w for w in snap.get("windows", []) if w.get("id") == "weekly"), None)
    budget = (latest_plan() or {}).get("budget") or {}
    est, eta, pace = budget.get("est_turns_to_goal"), budget.get("eta_days"), budget.get("pace_turns_per_day")
    pacing = (weekly or {}).get("pacing") or {}
    used = (weekly or {}).get("usedPct") or 0
    # at_risk MUST mean what the owner-facing sentence says ("leer vor dem
    # Reset"): usage.pacing's `flag` also fires on used_pct >= 85 alone, with
    # hours left irrelevant (measured 2026-09-13, 86% used/2.8h to reset/proj
    # UNDER 100% - still asked "Nicht-Ziel-Arbeit zurückstellen?" for a slip
    # that was never going to happen). Nor is bare exhaust_before_reset safe:
    # it has NO noise buffer (measured 2026-09-14, 6% into a FRESH window -
    # 6% used, proj 100.7% on pure noise - exhaust_before_reset True on
    # nothing). reset_risk is the one field with BOTH proj >= 105% and
    # exhaust_before_reset - the actual claim; anything less is "tight",
    # same bucket as the 80% rung right below it.
    verdict = ("at_risk" if pacing.get("reset_risk")
               else ("tight" if used >= 80 else "on_track"))
    risk_key = (weekly or {}).get("resetsAt") or ""
    risk_new = verdict == "at_risk" and st.get("stakeholder_risk") != risk_key
    if st.get("stakeholder_day") == _today() and not risk_new:
        return                                       # already updated today, nothing worse
    st["stakeholder_day"] = _today()
    if verdict == "at_risk":
        st["stakeholder_risk"] = risk_key
    _save_loopstate(st)
    msg = _goal_budget_text(goal, weekly, est, eta, pace, verdict)
    feas = (latest_plan() or {}).get("feasibility") or {}   # the brain's budget-fit judgement
    if feas.get("budget"):
        de = {"fits": "Budget reicht", "tight": "Budget knapp", "insufficient": "Budget reicht NICHT"}
        fl = de.get(feas["budget"], feas["budget"])
        if feas.get("note"):
            fl += " (%s)" % feas["note"]
        msg += " Machbarkeit: %s." % fl
    ps = _goal_process_status(st)         # timeline straight from the goal's process (epic)
    if ps and ps.get("total"):
        line = "Prozess: %d/%d Schritte fertig" % (ps["done"], ps["total"])
        if ps.get("next"):
            line += ", nächster Milestone „%s“%s" % (
                ps["next"][:50], (" bis %s" % ps["next_due"]) if ps.get("next_due") else "")
        if ps.get("process_due"):
            line += " · Ziel-Deadline %s" % ps["process_due"]
        msg += " " + line + "."
    # the full block still gets WRITTEN - just to the dashboard feed, where a
    # status report with no move belongs and where the owner reads it when he
    # wants it instead of being handed it.
    _activity("status", msg)
    if verdict != "at_risk":
        return
    if not risk_new:
        return                       # same risk_key already asked - Henry has it
    # no timestamp in the ASK, deliberately: "~So 30.08. 22:00" is a number the
    # owner cannot act on differently depending on its value, and a chain of
    # those is the shape the decree bans. The exact exhaust time is in the
    # dashboard block written just above, where a number belongs.
    _ask_owner("⚠ Das Wochenkontingent ist vor dem Reset leer — dann steht „%s“ still. "
               "Nicht-Ziel-Arbeit bis zum Reset zurückstellen?" % goal[:60],
               [{"label": "Zurückstellen",
                 "description": "Nur Ziel-Karten laufen bis zum Reset"},
                {"label": "Slip akzeptieren",
                 "description": "Alles läuft weiter, die Ziel-ETA rutscht"}],
               header="Budget vs. Ziel", title=_i18n.t("push.pmQuota"))


def _overview_stale(plan, tracks):
    """True if the dashboard layout isn't set yet. Used to give each card its
    milestone's target date on the board Timeline (pm-lean-advisor, 2026-09-04:
    retired - milestones no longer carry any date at all, LLM-estimated or
    otherwise; stamping an LLM's est_turns-derived date onto a card's real due
    field was exactly the invented-calendar-date class this rewrite removes)."""
    from spine.storage import events
    return not (events.settings().get("policy") or {}).get("dashboard", {}).get("tiles")


def _build_overview(plan):
    """OVERVIEW state action: ensure a sensible DASHBOARD layout exists.
    (Per-milestone Timeline due-dating retired - see _overview_stale.)
    Reversible edits only; this is a LOOP STATE, not bespoke capability code."""
    from spine.storage import events
    pol = dict(events.settings().get("policy") or {})
    if not (pol.get("dashboard") or {}).get("tiles"):
        pol["dashboard"] = {"tiles": ["value_delivered", "ai_spend", "margin", "yield", "automation", "leverage"],
                            "panels": ["capacity", "gates", "work"]}
        events.save_settings({"policy": pol})
        _activity("overview", "Uebersicht gebaut: Dashboard-Layout gesetzt.")
        return 1
    return 0


# The proactive loop is now a STATE MACHINE - same idea as ops/tools/loop_state.py:
# the STATE is computed from REALITY (board + plan + config) each tick and drives
# the next action. A new capability = a new STATE (e.g. OVERVIEW), not new code.
def _state():
    """(STATE, plain reason). First actionable state wins. Surfaced to you so you
    can SEE what the PM is doing / about to do. WAIT = wants to act but you're here."""
    pm = _pm()
    if not pm.get("loop_enabled"):
        return ("OFF", "Proaktiv ist aus.")
    from cells.engineer.cards import sessions
    tracks = [t for t in sessions.list_tracks()
              if not t.get("archived") and not t.get("example")]
    st = _loopstate()
    day = st.get(_today(), {})
    disp = set(day.get("dispatched", []))
    notif = set(day.get("notified", []))
    res = set(day.get("resolved", []))
    auto0 = pm.get("autonomy", "act")
    if any(t["id"] not in notif and (
            (t.get("status") == "needs_you" and t["id"] in disp)
            or (t.get("status") == "bounced"
                and (t["id"] in res or (auto0 != "act" and t["id"] in disp))))
           for t in tracks):
        return ("NOTIFY", "Fertige/haengende Karten melden (mit Vorschlag).")
    acting = _in_window(pm) and _board_idle(pm)          # you're away -> may act
    if st.get("last_plan_day") != _today():
        return ("PLAN", "Tagesplanung steht aus.") if acting else ("WAIT", "Tagesplan faellig, aber du bist da.")
    plan = latest_plan()
    if plan and _overview_stale(plan, tracks):
        return ("OVERVIEW", "Dashboard + Timeline aus dem Plan bauen.") if acting else ("WAIT", "Uebersicht veraltet, aber du bist da.")
    # COORDINATOR: unblock what's stuck (delegate + re-submit, bis zu
    # _RESOLVE_MAX Anlaeufe mit anderem Ansatz) BEFORE starting new work
    if pm.get("autonomy", "act") == "act" and _bounced_to_resolve(tracks, pm, day):
        return ("RESOLVE", "Gebouncte Karte entstoeren (delegieren + neu einreichen).") if acting else ("WAIT", "Bounce zu fixen, aber du bist da.")
    # HARD GATE: a goal exists but its plan hasn't passed the golden triage
    # (Budget/Timeline/Scope green) -> hold ALL dispatch and surface the gate. Ranks
    # after PLAN (today's plan runs first) and RESOLVE (unblocking stuck work still runs).
    if get_goal() and not _triage_green(latest_plan()):
        return ("TRIAGE", "Gate rot: Budget/Timeline/Scope nicht gruen - kein Dispatch, ich kläre/frage.") \
            if acting else ("WAIT", "Plan-Gate rot, aber du bist da.")
    # HARD GATE 2 (owner decree 2026-08-22: "ohne die Haupt-Info sollte er
    # nicht arbeiten"): the plan still carries OPEN QUESTIONS to the owner ->
    # no new dispatch on assumptions. Answering in chat (clarify_goal) folds
    # the answer in and re-plans immediately, which clears this hold.
    if get_goal() and any(isinstance(q, str) and q.strip()
                          for q in ((latest_plan() or {}).get("open_questions") or [])):
        return ("ASK", "Offene Schlüsselfragen an dich - kein Dispatch auf Annahmen, "
                       "bitte kurz im Chat beantworten.") \
            if acting else ("WAIT", "Fragen an dich offen, aber du bist da.")
    paused = day.get("paused_at") and time.time() - day["paused_at"] < 5 * 3600
    if not paused and len(day.get("dispatched", [])) < pm.get("max_dispatch_per_day", 3) and _backlog(tracks, pm, day):
        return ("DISPATCH", "Naechste Karte starten.") if acting else ("WAIT", "Arbeit da, aber du bist da.")
    return ("IDLE", "Alles im Griff - nichts zu tun.")


def _dispatch_next(pm, st, day):
    from cells.engineer.cards import sessions
    from spine.storage import events
    if sum(1 for t in sessions.list_tracks() if t.get("lane") == "working") >= events.wip_limit_of():
        return                                           # respect WIP headroom
    todo = _backlog(sessions.list_tracks(), pm, day)
    if not todo:
        return
    # BUDGET MANAGEMENT: if the weekly quota is burning ahead of pace, hold
    # non-urgent cards so the quota lasts to the reset - the PM spends the budget,
    # it doesn't just warn about it. Silent when it can still run high-prio work;
    # announces once per window only when it's actually holding everything back.
    floor = _quota_floor()
    if floor is not None:
        rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        kept = [t for t in todo if rank.get(t.get("priority"), 2) <= floor]
        if not kept:
            key = ""
            try:
                from spine.ops import usage
                key = (usage.weekly_pacing_flag() or {}).get("resetsAt") or ""
            except Exception:
                pass
            if st.get("quota_held_reset") != key:
                st["quota_held_reset"] = key; _save_loopstate(st)
                only = "nur dringende" if floor == 0 else "nur dringende + hohe"
                # DASHBOARD ONLY (owner decree 2026-08-30): the PM already DID the
                # thing. Raising a card's priority is a board action he takes when
                # he wants that card, not an answer this message needs - and the
                # hold is on the dashboard as quota_paused / the feed line.
                _activity("blocked", "Quota-Management: nicht-dringende Karten bis zum "
                          "Reset zurueckgestellt (%s Prioritaet startet noch)." % only)
            return
        todo = kept
    t = todo[0]
    day["dispatched"].append(t["id"]); _save_loopstate(st)
    _activity("started", "Gestartet: " + (t.get("task", "")[:70]), card=t["id"])
    t = sessions.move_lane(t["id"], "working", actor="pm")
    if _limit_hit(t):
        day["paused_at"] = time.time(); _save_loopstate(st)
        _activity("blocked", "Quota erschoepft - pausiere ~5 Stunden.")


def _position(tracks, plan):
    """Phase 2+3 distilled: WHERE WE STAND, judged by the triangle. Its JSON
    digest is the delta key - communication fires only when THIS changes."""
    tri = (plan or {}).get("triage") or {}
    return {
        "goal": get_goal(),
        "done_pct": (plan or {}).get("done_pct"),
        "triage": {k: tri.get(k) for k in ("budget", "timeline", "scope")},
        "reasons": (plan or {}).get("triage_reasons") or {},
        "plan_status": (plan or {}).get("plan_status"),
        "needs_you": sorted(t["id"] for t in tracks if t.get("status") == "needs_you"),
        "bounced": sorted(t["id"] for t in tracks if t.get("status") == "bounced"),
        "open_q": (plan or {}).get("open_questions") or [],
    }


def _tick():
    """ONE loop, four phases (the owner's model):
        1 GATHER    all info: board, plan, economics/quota
        2 STAND     read the last plan + chat -> where we are
        3 TRIANGLE  judge Budget/Timeline/Scope (measured, in the plan)
        4 DELTA     communicate ONLY when the position changed
    then the acting states run - but only while you are away. Proactive on/off +
    the notify/ask/act ladder is a Settings control now, not a dashboard one."""
    # 1 - GATHER
    from spine.registry import cells
    # "copilot", NOT "pm": the pm cell merged into copilot (2026-09-03) and
    # enabled_id fails OPEN for an unknown id - left reading "pm", this guard
    # would have silently stopped guarding anything.
    if not cells.enabled_id("copilot"):
        # ADDITIONAL early-return, not a replacement: loop_enabled (below) is
        # the owner's proactive on/off Settings control; cellEnabled is the
        # separate whole-cell kill switch (Phase 2 of the cell-registry decree).
        return
    pm = _pm()
    if not pm.get("loop_enabled"):
        return
    st = _loopstate()
    day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
    from cells.engineer.cards import sessions
    tracks = sessions.list_tracks()
    plan = latest_plan()

    # deliveries are EVENT-driven (a card just finished/bounced), not a position
    # delta - always run, they dedup internally.
    _notify_deliveries(day, tracks, st, pm)

    # per-card burn watchdog: code thresholds, and like the deliveries NOT
    # behind the acting/idle gates below - the €843 card burned precisely
    # WHILE the owner was present and steering it.
    _cost_watch(st, tracks)

    # 2+3 - STAND, judged by the TRIANGLE
    pos = _position([t for t in tracks if not t.get("archived") and not t.get("example")], plan)
    _pkey = json.dumps(pos, sort_keys=True, ensure_ascii=False)

    # 4 - COMMUNICATE ONLY ON DELTA. Persist the new digest FIRST so a substep
    # that re-reads loopstate can't lose it, then run the (internally-deduped)
    # communication paths. Nothing changed -> the loop stays quiet.
    if st.get("pos_digest") != _pkey:
        st["pos_digest"] = _pkey
        _save_loopstate(st)
        _launch_checkin(pm, st)      # ask launch prereqs once
        _goal_process(pm, st)        # new goal -> process (epic) + intake
        _triangle_watch(st)          # escalate when a corner tilts
        _plan_gate_notice(st)        # honest "blocked" over a shallow estimate
        _needs_from_owner(st)        # surface missing-info questions
        _stakeholder_update(st)      # goal vs budget, keep the owner informed
        # Phase 3 (pm-lean-advisor, narrowest safe slice): PURE CODE, zero
        # model cost, only on a real board change - never autonomous, always
        # a tap-with-options via _ask_owner, and cooled down per pair.
        duplicate_check_async()

    if not _in_window(pm) or not _board_idle(pm):
        return                                           # acting states need you away
    state, _reason = _state()
    auto = pm.get("autonomy", "act")
    try:
        if state == "PLAN":
            brief() if auto == "notify" else make_plan(actor="pm")
            st = _loopstate(); st["last_plan_ts"] = time.time()
            st["last_plan_day"] = _today()          # daily planning cadence
            st.pop("scope_baseline", None)          # today's plan re-baselines the triangle
            shape = _triage_shape(live_plan())      # re-baseline the flip detector too
            if shape:
                st["plan_triage_shape"] = shape
            _save_loopstate(st)
        elif state == "OVERVIEW":
            _build_overview(latest_plan() or {})         # build Dashboard + Timeline
        elif state == "RESOLVE" and auto == "act":
            _resolve_next(pm, st, day)                   # coordinator: delegate the fix
        elif state == "DISPATCH" and auto == "act":
            _dispatch_next(pm, st, day)
    except Exception as e:
        print("PM tick error [%s]:" % state, e)


def status():
    """Surfaced by /pm/* + /nightshift (alias) + /automation."""
    st = _loopstate()
    sname, sreason = _state()
    return {"config": _pm(), "plan": latest_plan(), "state": sname, "state_reason": sreason,
            "today": st.get(_today(), {"dispatched": [], "paused_at": 0}),
            "last_plan": st.get("last_plan")}


# -- the communication layer: plain-language "what am I doing" (DAU) ----------
# Extracted to pm_comm.py (god-file breakup). Re-imported here so every
# existing pm.<name> caller (routes_pm.py, this file's own many callers)
# stays unchanged.
from cells.copilot.planning.pm_comm import (
    _activity, _say, _escalation_tid,
    _escalate, _ask_owner, _to_henry, _short, _read_activity)


def activity():
    """The DAU narrative: what's running now, what's next, what needs you, and
    the blockers - all from live card state, plus the recent activity feed."""
    from cells.engineer.cards import sessions
    # PRESENTED, not stored: "arbeitet gerade an X" was a lie for any card whose
    # turn had died - it reads `running` in the store until the reconciler heals
    # it, so the narrative claimed work was in flight AND left the card out of
    # "needs you". present() derives the truth at read time (invariant I2).
    tracks = [sessions.present(t) for t in sessions.list_tracks()
              if not t.get("archived") and not t.get("example")]
    st = _loopstate()

    def lbl(t):
        return (t.get("task") or "").replace("\n", " ")[:70]

    now = []
    for t in tracks:
        if t.get("lane") != "working":
            continue
        s = t.get("status")
        if s == "running":
            now.append("arbeitet gerade an: " + lbl(t))
        elif s == "needs_you":
            # Since Phase 2 the three reasons a card parks ARE distinguishable,
            # so say which one it is instead of lumping them together.
            if t.get("waiting_on") == "background":
                now.append("wartet auf einen Hintergrund-Task: " + lbl(t))
            elif t.get("question"):
                now.append("fragt dich etwas: " + lbl(t))
            else:
                now.append("wartet auf dich: " + lbl(t))
        elif s == "bounced":
            continue        # a bounced card is surfaced ONCE as a blocker below, not here
        else:
            now.append(lbl(t))
    # "waiting on you" = genuinely handed back (needs_you/submitted). A BOUNCED card is
    # NOT that - it's stuck/failed, listed only under blockers, never double-counted.
    # A card waiting on its own background task is nobody's move but the machine's,
    # so it must not pad the owner's to-do count either.
    #
    # Both buckets come out of the ONE derivation (sessions.owner_blockers),
    # split by reason: re-deriving "blocked on you" per surface is exactly what
    # let this narrative and the glasses feed answer the same question
    # differently. It also picks up the case neither of them had - a card whose
    # turn DIED, still stored as `running`, which no status test can see.
    _STUCK = ("gate", "conflict", "failed")
    needs, blockers = [], []
    for t, b in sessions.owner_blockers(tracks):
        (blockers if b["reason"] in _STUCK else needs).append(lbl(t))
    rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    todo = sorted((t for t in tracks if t.get("lane") == "backlog"
                   and t.get("mode") not in ("human", "teach", "cowork")),
                  key=lambda t: (rank.get(t.get("priority"), 2), t.get("created") or ""))
    sname, sreason = _state()
    return {
        "loop_enabled": _pm().get("loop_enabled"),
        "autonomy": _pm().get("autonomy"),
        "state": sname,
        "state_reason": sreason,
        "now": now,
        "next": lbl(todo[0]) if todo else None,
        "next_count": len(todo),
        "needs_you": needs,
        "blockers": blockers,
        "quota_paused": bool(st.get(_today(), {}).get("paused_at")),
        "last_plan": st.get("last_plan"),
        "feed": _read_activity(20),
    }


def start_loop():
    """Background ticker - a cheap no-op while loop_enabled is false."""
    def loop():
        while True:
            try:
                _tick()
            except Exception as e:
                try:
                    from spine.storage import events
                    events.log("pm", "tick error: %s" % e)
                except Exception:
                    pass
            time.sleep(120)
    threading.Thread(target=loop, daemon=True, name="pm-loop").start()
