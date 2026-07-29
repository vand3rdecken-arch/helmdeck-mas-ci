# -*- coding: utf-8 -*-
"""The structural debt register - the program's own list of load-bearing
shortcuts. Debt lives IN the code (reviewed like code, updated when paid),
is visible in the History view, known to the copilot, and convertible to a
fix card with one click. A shortcut that isn't written down here is either
not known yet or not a shortcut.

status: open | in_progress | paid  (paid items stay listed - they document
why the code looks the way it does)"""

DEBT = [
    {
        "id": "turn-locks",
        "title": "No per-track turn locks",
        "status": "paid",
        "what": "Steers/dispatches run in threads with nothing serializing "
                "turns per card.",
        "why_it_bites": "Two simultaneous turns on one card (user + chain, or "
                        "two users) run `claude --resume` against the same "
                        "session; session ids rotate, one continuation is "
                        "orphaned, last_reply can be overwritten.",
        "trigger": "second concurrent user, or heavy chain automation",
        "fix": "threading.Lock per track id around _turn(); queue + visible "
               "'agent busy' state. NOTE: the lock alone DEADLOCKED - it wrapped "
               "an unbounded stdout read, so a stalled turn held it forever and "
               "every later steer hung. Superseded by the persistent stream-json "
               "session port (drivers._ClaudeSession, Paseo's model): run_turn is "
               "now BOUNDED (tree-kill on timeout) so the lock always releases.",
        "order": 1,
    },
    {
        "id": "json-storage",
        "title": "JSON-file storage (tracks/events/users)",
        "status": "paid",
        "what": "Every save is read-modify-write of a whole file from "
                "concurrent threads; the event log is re-parsed fully on "
                "every dashboard request.",
        "why_it_bites": "Lost updates under concurrent writes; dashboard cost "
                        "grows linearly with history forever.",
        "trigger": "multi-user writes, or months of events.jsonl",
        "fix": "SQLite (stdlib): tracks/events/users tables, transactions, "
               "indexed metrics queries. Import script for existing JSON.",
        "order": 2,
    },
    {
        "id": "polling",
        "title": "5s polling instead of push (SSE)",
        "status": "paid",
        "what": "Every client refetches all board data every 5 seconds.",
        "why_it_bites": "Staleness between users, wasted requests, and the "
                        "class of re-render bugs that polling forces the UI "
                        "to defend against.",
        "trigger": "more than one concurrent user who expects live state",
        "fix": "Server-Sent Events endpoint (works in ThreadingHTTPServer, "
               "cookie auth as-is); store patches state from events instead "
               "of refetching.",
        "order": 3,
    },
    {
        "id": "single-secret-transport",
        "title": "Plain HTTP on the LAN",
        "status": "open",
        "what": "Credentials and session cookies travel unencrypted on the "
                "local network.",
        "why_it_bites": "Any hostile device on the same network can read "
                        "them.",
        "trigger": "first remote/client access from outside a trusted LAN",
        "fix": "Tailscale for own devices; Cloudflare Tunnel + TLS the day a "
               "client gets a URL.",
        "order": 4,
    },
    {
        "id": "vanilla-fallback-ui",
        "title": "Legacy single-file UI still served at :8140",
        "status": "paid",
        "what": "The pre-Next fallback UI shares no code with web/ and drifts.",
        "why_it_bites": "Confusion (features missing there look like bugs) - "
                        "already caused one 'I don't see it' incident.",
        "trigger": "anyone opening :8140 expecting the real UI",
        "fix": "Replace with a redirect page to the Next app once the Next "
               "app is served in production mode.",
        "order": 5,
    },
    {
        "id": "nightshift-limit-sniff",
        "title": "Night shift detects usage limits by string-matching replies",
        "status": "paid",
        "what": "nightshift._limit_hit() greps the card's last_reply for "
                "'usage limit'/'rate limit' instead of reading a structured "
                "error from the driver.",
        "why_it_bites": "A rephrased CLI error means the night shift keeps "
                        "starting cards into a dead quota; a false match in a "
                        "legitimate reply stops it early.",
        "trigger": "Claude CLI changing its limit wording, or a card whose "
                   "reply merely mentions rate limits",
        "fix": "PAID: drivers surfaces the stream-json result event's subtype/"
               "is_error/errors into meta; _record_turn stores last_subtype/"
               "last_error on the track; _limit_hit reads those STRUCTURED fields "
               "first (prose grep only for legacy turns). Remaining: match the "
               "exact usage-limit subtype string once observed from a real limit.",
        "order": 6,
    },
    {
        "id": "session-restart-on-optchange",
        "title": "Model/mode/tool change kills & resumes the session (no control plane)",
        "status": "paid",
        "what": "A steer with a different model/permission-mode/allowed-tools than "
                "the running process tree-killed it and respawned; Stop hard-killed.",
        "why_it_bites": "A respawn re-pays session init/context cost and briefly "
                        "drops streaming; rapid model-toggling churns processes.",
        "trigger": "owner flipping model/mode often mid-conversation on one card",
        "fix": "PAID: drivers._ClaudeSession speaks the CLI's stream-json control "
               "plane (verified against the real binary): model/mode changes apply "
               "LIVE via set_model / set_permission_mode; Stop sends a soft "
               "interrupt first (process stays alive, resumable) and only "
               "tree-kills as a fallback. Only an allowed-tools change (no live "
               "control subtype) or a failed control op still forces a respawn.",
        "order": 7,
    },
    {
        "id": "orphan-reap-pid-reuse",
        "title": "Startup orphan reap trusted a bare recorded PID list",
        "status": "paid",
        "what": "reap_orphans() tree-killed PIDs recorded by a prior daemon, "
                "guarded only by a tasklist image-name check (claude/node/cmd).",
        "why_it_bites": "A recycled PID that happens to be an unrelated node/cmd "
                        "process could be killed after a crash-restart.",
        "trigger": "daemon crash-restart on a busy machine with heavy PID churn",
        "fix": "PAID: driver_pids.json now records (pid -> spawn epoch); reap_orphans "
               "matches the OS-reported process start time (PowerShell Get-Process "
               "StartTime) against the recorded spawn within 6s - a recycled pid "
               "shows a later start and is skipped. Image-name guard remains only "
               "as a fallback when the start time can't be read.",
        "order": 8,
    },
]

def list_debt():
    return sorted(DEBT, key=lambda d: (d["status"] == "paid", d["order"]))

def fix_task(item):
    return ("STRUCTURAL DEBT FIX [%s]: %s\n\nWhat: %s\nWhy it bites: %s\n"
            "Planned fix: %s\n\nWhen done and verified, set this item's status "
            "to 'paid' in daemon/debt.py (keep it listed) and note the commit."
            % (item["id"], item["title"], item["what"], item["why_it_bites"],
               item["fix"]))
