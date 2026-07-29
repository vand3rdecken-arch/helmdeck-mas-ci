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
        "id": "session-restart-on-optchange",
        "title": "Model/mode/tool change kills & resumes the session (no control plane)",
        "status": "open",
        "what": "drivers._ClaudeSession keeps one persistent `claude` process per "
                "card, but a steer whose model/permission-mode/allowed-tools "
                "differ from the running process tree-kills it and respawns with "
                "`--resume`. Stop (cancel) does the same. Paseo instead uses the "
                "SDK control plane (query.interrupt / setPermissionMode) to change "
                "these in place on the live query.",
        "why_it_bites": "A respawn re-pays session init/context cost and briefly "
                        "drops streaming; rapid model-toggling churns processes.",
        "trigger": "owner flipping model/mode often mid-conversation on one card",
        "fix": "Speak the stream-json control protocol (control_request: interrupt, "
               "set_permission_mode) on the existing stdin instead of respawning.",
        "order": 7,
    },
    {
        "id": "orphan-reap-pid-reuse",
        "title": "Startup orphan reap trusts a recorded PID list",
        "status": "open",
        "what": "drivers.reap_orphans() tree-kills PIDs recorded in "
                "driver_pids.json by a prior daemon. It guards against PID reuse "
                "with a tasklist image-name check (claude/node/cmd), but that is "
                "best-effort, not an identity match.",
        "why_it_bites": "A recycled PID that happens to be an unrelated node/cmd "
                        "process could be killed; a very fast reuse into claude.exe "
                        "of a DIFFERENT session could hit the desktop's own agent.",
        "trigger": "daemon crash-restart on a busy machine with heavy PID churn",
        "fix": "Record (pid, create_time) or a per-process marker env var and only "
               "reap on an exact identity match.",
        "order": 8,
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
        "status": "open",
        "what": "nightshift._limit_hit() greps the card's last_reply for "
                "'usage limit'/'rate limit' instead of reading a structured "
                "error from the driver.",
        "why_it_bites": "A rephrased CLI error means the night shift keeps "
                        "starting cards into a dead quota; a false match in a "
                        "legitimate reply stops it early.",
        "trigger": "Claude CLI changing its limit wording, or a card whose "
                   "reply merely mentions rate limits",
        "fix": "Have drivers._claude() surface the stream-json result error "
               "type as a structured track field; night shift reads that.",
        "order": 6,
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
