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
        "id": "expo-cutover-pipeline",
        "title": "Old frontends archived, but build/deploy/loop still point at them",
        "status": "paid",
        "what": "web/ (Next.js) and apk/ (Kotlin) were moved to archive/ when the "
                "single Expo app in app/ took over as the frontend for phone, web "
                "and desktop. But deploy/push_relay.sh still builds+ships the "
                "Kotlin APK, tools/loop_state.py's TEST/BUILD states + artifact "
                "map reference web/ and apk/, tools/design_lint*.py and "
                "gen_tokens.py read web/app/globals.css (now archive/web/...), and "
                "there is no EAS cloud-build / OTA wired.",
        "why_it_bites": "The deploy script errors (missing apk path), the build "
                        "loop mis-detects state, and the design gate reads a "
                        "moved token file - the harness thinks it can ship when it "
                        "cannot.",
        "trigger": "next relay push, next loop_state run, next design gate",
        "fix": "PAID in two passes. 3114f6d: loop_state.py ARTIFACT_SRC repointed "
               "to the signed Expo APK (native-only sources; JS ships via OTA "
               "deploy/push_update.sh), BUILD action -> release.sh/push_update.sh. "
               "This commit: design_lint + selftest retargeted to app/ (theme "
               "tokens via useTheme(), webstyles.tsx carries the web-shell "
               "color-scheme rule); gen_tokens.py declared the CANONICAL palette "
               "source (globals.css is history in archive/); loop_state's tsc "
               "check + design-mode hint repointed web/ -> app/. push_relay.sh "
               "had already been rewritten for the Expo APK, app/eas.json and "
               "the OTA path (push_update.sh, release.sh ota) already existed. "
               "Still open elsewhere: delete archive/ only at confirmed "
               "production parity.",
        "order": 0,
    },
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
        "status": "paid",
        "what": "Credentials and session cookies travel unencrypted on the "
                "local network.",
        "why_it_bites": "Any hostile device on the same network can read "
                        "them.",
        "trigger": "first remote/client access from outside a trusted LAN",
        "fix": "PAID. Remote paths were already TLS: relay behind nginx+"
               "certbot (E2EE-sealed frames on top), Cloudflare Tunnel script "
               "for the API. This card closed the LAN + enforcement gaps: "
               "(1) server.serve() grows a native https listener - cert/key "
               "via HELMDECK_TLS_CERT/KEY, settings.tls, or auto-detected "
               "daemon/certs/ (minted by tools/make_tls_cert.py; trusted "
               "certs via `tailscale cert`) - and with TLS on, plain http "
               "binds LOOPBACK-ONLY (local tooling keeps working, nothing "
               "cleartext leaves the machine; a broken TLS config also stays "
               "loopback-only instead of downgrading). (2) Pairing links "
               "embed a live device token in a URL, so relay_client."
               "insecure_url() now refuses plain-http non-loopback relay "
               "URLs at BOTH seams: /settings save and pairing_payload(); "
               "an existing http config logs a one-time warning but keeps "
               "bridging (frames are E2EE regardless). Remaining relatives "
               "stay listed separately: [android-cleartext-lan], "
               "[pair-token-no-ttl].",
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
        "fix": "PAID: server.py drops the BOARD/DASH/PAGE templates and "
               "daemon/ui/app.html; /, /classic, /recorder and /dashboard "
               "302 to the Next app (settings.web_url, default "
               "http://localhost:3300).",
        "order": 5,
    },
    {
        "id": "nightshift-limit-sniff",
        "title": "Night shift detects usage limits by string-matching replies",
        "status": "paid",
        "what": "pm._limit_hit() (moved from the removed nightshift.py) greps the card's last_reply for "
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
    {
        "id": "accept-merge-base-branch",
        "title": "Accept merges into the checkout's CURRENT branch, ff-agnostic",
        "status": "open",
        "what": "move_lane('done') now merges the card branch via _merge_to_main, "
                "but into whatever branch t['repo'] currently has checked out "
                "(assumed to be the base/main) rather than a base branch RECORDED "
                "on the card at dispatch. It also always --no-ff and does not push.",
        "why_it_bites": "If the owner leaves the main checkout on a different "
                        "branch, an accept would merge into the wrong target (the "
                        "guard only refuses detached HEAD or the card branch "
                        "itself). No push means 'deployed' still depends on a "
                        "deploy hook to publish.",
        "trigger": "a repo whose cards fork from a non-default base, or a checkout "
                   "parked on a feature branch at accept time",
        "fix": "Record base_branch on the card at dispatch; merge into THAT "
               "(checking it out / using a dedicated integration worktree), offer "
               "ff-only vs --no-ff by policy, and push when the repo is remote.",
        "order": 9,
    },
    {
        "id": "android-cleartext-lan",
        "title": "Android APK enables global cleartext for the direct-LAN feature",
        "status": "paid",
        "what": "The app's 'direct LAN' option (More > http://<daemon>) could never "
                "work on a release build: targetSdk>=28 blocks cleartext HTTP by "
                "default, so every http:// daemon URL failed with 'Desktop nicht "
                "erreichbar'. Fixed by adding android:usesCleartextTraffic=\"true\" "
                "to app/android/app/src/main/AndroidManifest.xml - but that file is "
                "gitignored/hand-managed (not driven by app.json), so the flag is "
                "invisible to git and a future `expo prebuild` would silently drop "
                "it (along with the hand-added expo-updates meta-data).",
        "why_it_bites": "usesCleartextTraffic=true permits plaintext HTTP to ANY "
                        "host app-wide, not just private LAN IPs - a mild security "
                        "downgrade (the relay path stays HTTPS/sealed). And the "
                        "whole native config can vanish on a prebuild.",
        "trigger": "next `expo prebuild`, or a security review of the APK",
        "fix": "PAID: app/plugins/withLanCleartext.js scopes cleartext via a "
               "network-security-config (base-config blocks cleartext; a "
               "domain-config allows it only for 10.0.2.2/localhost/127.0.0.1 "
               "plus the hosts listed in the app.json plugin entry - Android NSC "
               "cannot express RFC1918 ranges, so the scope is an explicit host "
               "list; a real phone's direct-LAN mode needs the PC's IP added "
               "there + an APK rebuild). One file drives BOTH build paths: expo "
               "config plugin for a future prebuild, and a bare-node CLI that "
               "deploy/build_apk.sh runs against the hand-managed app/android "
               "before every gradle build, replacing the invisible global flag. "
               "expo-updates is now an explicit app.json plugin, so its "
               "meta-data survives a prebuild too. "
               "Relates to [single-secret-transport].",
        "order": 10,
    },
    {
        "id": "pair-token-no-ttl",
        "title": "Pairing device-token outlives the 15-min pairing window",
        "status": "open",
        "what": "Each /relay/pair click mints a device bearer token with no "
                "expiry. The single-use PAIR_TTL window (relay_client._admit) "
                "gates the E2EE pin - the relay path of an unused code dies "
                "with the window - but the token inside the code stays a live "
                "credential.",
        "why_it_bites": "A leaked pairing code that was never used can still "
                        "authenticate over direct LAN mode ({b,t} style) even "
                        "after the window expired. Tokens are at least visible "
                        "and revocable per user in Settings -> users.",
        "trigger": "owner generates codes and abandons them; a code lands in "
                   "chat history/screenshots and someone on the LAN finds it",
        "fix": "Give pairing-issued tokens a TTL and auto-revoke unused ones "
               "when the window closes, or bind the token to the pinned "
               "device pub at admission time.",
        "order": 11,
    },
    {
        "id": "machine-task-blast-radius",
        "title": "Machine tasks run with bypassPermissions over the whole PC",
        "status": "open",
        "what": "sessions.new_machine_task dispatches a card whose workplace is a "
                "real folder on the owner's machine, with permission mode "
                "bypassPermissions (policy.machine.perm) and no path restriction "
                "by default (policy.machine.roots = []). Headless is why: an "
                "unanswerable permission prompt IS a block, and blocking was the "
                "bug being fixed. Guards in place: owner-only role gate "
                "(policy.machine.roles), the capability switch "
                "(policy.machine.enabled), full audit (machine/turn/done events + "
                "flight recorder), no merge path, and a brief that fences "
                "HelmDeck's own secrets.",
        "why_it_bites": "An agent turn that misreads its instruction can change or "
                        "delete anything the owner's account can reach, and unlike "
                        "a worktree card there is no branch to roll back - the "
                        "per-turn checkpoint is deliberately skipped for machine "
                        "cards. The prompt-level secret fence is guidance, not "
                        "enforcement.",
        "trigger": "the first machine task pointed at a broad folder (home, C:\\), "
                   "or a second non-owner account being granted machine roles",
        "fix": "Narrow by default: ship policy.machine.roots preset to the owner's "
               "usual work folders and require an explicit widening; add a "
               "recycle-bin-style undo (move-to-trash instead of delete) for "
               "machine file operations; enforce the secret fence in code (deny "
               "reads of settings.json/users.json/helmdeck.db via allowed_tools "
               "deny-rules) rather than in the brief; consider a dry-run turn that "
               "reports the plan before the acting turn for destructive verbs.",
        "order": 12,
    },
    {
        "id": "pm-loopstate-races",
        "title": "PM loopstate is read-modify-write from tick + resolve threads",
        "status": "open",
        "what": "pm.py's resolve threads (_bump_attempt/_give_up) serialize their "
                "own writes to pm/loop.json behind _resolving_lock, but the tick "
                "thread (_notify_deliveries, _dispatch_next, make_plan) still does "
                "unlocked read-modify-write of the same file with state read "
                "earlier in the tick.",
        "why_it_bites": "A tick save landing between a resolve thread's write and "
                        "the next read can revert an attempt counter or a "
                        "notified flag - worst case one duplicate owner ping or "
                        "one extra (harmless, rate-limited) delegation attempt.",
        "trigger": "a resolve thread finishing in the same second a tick saves "
                   "loopstate; more likely once several cards resolve in parallel",
        "fix": "Route ALL loopstate mutations through one locked helper that "
               "re-reads inside the lock (the _bump_attempt pattern), or move "
               "loopstate into the sqlite DB like tracks.",
        "order": 13,
    },
    {
        "id": "browser-attach-real-chrome",
        "title": "Standard agent browser attaches to a real, logged-in Chrome",
        "status": "open",
        "what": "browsercap.AgentBrowser now defaults to attach=True: it launches "
                "(or reuses) a persistent Chrome with a debug port + a dedicated "
                "HelmDeck user-data-dir and drives it over CDP. That profile holds "
                "real extensions and logged-in sessions (the whole point - so an "
                "agent can use Claude-for-Chrome etc.), and the agent gets a page "
                "handle in it. Guards in place: it is a SEPARATE profile (not the "
                "owner's daily user-data-dir), the browser is visible and fully "
                "screen-recorded (wincap screen.mp4 + live.jpg) beside the audited "
                "action timeline, close() never kills the owner's browser, and "
                "invocation stays behind the machine capability (policy.machine, "
                "owner role) like any other PC-touching work.",
        "why_it_bites": "An agent turn can act inside a browser carrying the "
                        "owner's cookies/OAuth sessions - it can read or send as "
                        "the owner on any site that profile is logged into, with no "
                        "per-site consent and no branch to roll back. The profile "
                        "separation is a convention, not a sandbox; nothing yet "
                        "restricts which origins the agent may drive.",
        "trigger": "the first card that opens the standard browser against a "
                   "sensitive logged-in site (mail, bank, cloud console), or the "
                   "debug port being reachable by another local process",
        "fix": "Gate origins: an allowlist of hosts the agent browser may navigate "
               "(deny the rest at goto()); bind the debug port to loopback with a "
               "per-run token; add a dry-run/confirm turn for state-changing "
               "actions on allowlisted-but-sensitive sites; surface the active "
               "origin in the live glance feed so the owner sees where it is.",
        "order": 14,
    },
    {
        "id": "ask-protocol-prompt-compliance",
        "title": "The question channel depends on prompt compliance + one repair turn",
        "status": "open",
        "what": "Phase 2.4 routes a worker's open question to real option buttons by "
                "TEACHING it a <helmdeck-ask> block (ask.BRIEF) and parsing that out "
                "of the reply. Measured against the shipped CLI (2.1.207), the system "
                "prompt alone is NOT reliably followed - the worker wrote prose and "
                "parked in both live probes - so sessions._repair_question spends one "
                "extra turn asking it to restate the question in protocol form, gated "
                "by the ask.looks_like_question heuristic. There is no hard channel "
                "(AskUserQuestion is not offered headless and no can_use_tool "
                "control_request is ever sent, so it cannot be intercepted).",
        "why_it_bites": "Two soft edges. (1) The heuristic decides when to spend a "
                        "turn: a false positive costs one short turn (the worker "
                        "answers NOQUESTION), a false negative silently falls back to "
                        "the old prose-and-park behaviour - so coverage is good but "
                        "not total. (2) If a future CLI or model drifts further from "
                        "the instruction, the repair turn is the only thing holding "
                        "the feature up, and its cost scales with every parked turn "
                        "that looks like a question.",
        "trigger": "a CLI/model upgrade changing instruction-following, or the repair "
                   "turn showing up as a noticeable share of spend on the turn events",
        "fix": "Re-run tests/probe_cli_askuser.py against the new CLI: once it exposes "
               "AskUserQuestion (or sends control_request/can_use_tool to a "
               "stream-json client), replace the taught protocol with a real "
               "interception + park/respond, which needs no compliance and no repair "
               "turn. Until then, track the askrepair events to see how often the "
               "fallback carries the feature.",
        "order": 15,
    },
    {
        "id": "auto-compaction-disabled",
        "title": "Proactive context compaction was off - misdiagnosed, re-enabled in place",
        "status": "paid",
        "what": "sessions._maybe_compact injects a '/compact' turn at ~80% context "
                "to summarise the session in place. It was disabled 2026-08-10 "
                "(a0853d4) after the 'Fix AI-Kosten-Tracking' incident, blamed for "
                "corrupting the session tip so a later --resume silently started "
                "fresh, and for a shrink-check that read summed usage instead of "
                "compacted context.",
        "why_it_bites": "Turned out to be a misdiagnosis: both blamed causes were "
                        "ALREADY fixed by other commits before the disable landed. "
                        "The shrink-check bug was fixed by 66930bb (2026-08-08, TWO "
                        "DAYS earlier) when ctx_tokens moved to last-call-only usage "
                        "(meta.ctx_usage). The '--resume silently started fresh' "
                        "symptom was the claude.cmd shim eating the trailing "
                        "'--resume <sid>' arg under `cmd /s /c` - ANY --resume could "
                        "silently miss, not just a post-compact one - fixed by "
                        "ea09780 (2026-08-10, the SAME DAY, 5h after the disable). "
                        "Compaction was never actually the corruption source; it "
                        "just happened to be the session in front of the shim bug "
                        "when it was caught.",
        "trigger": "n/a - re-enabled 2026-08-14",
        "fix": "PAID: restored _maybe_compact's original self-verifying logic "
               "(probe /compact once, learn True/False from whether ctx_tokens "
               "actually shrank by >=25%) instead of building fork-based "
               "compaction - forking a session to compact it was solving a "
               "corruption problem that had already been fixed elsewhere. "
               "accept-and-rebind (_finish_turn, Weg B) stays as-is: it is a "
               "correct safety net for ANY unresumable session, not just a "
               "post-compact one, so it remains regardless of compaction. Watch "
               "the AUTO-COMPACT log line on the next card that crosses 160k to "
               "confirm this CLI still honors /compact in-place.",
        "order": 16,
    },
    {
        "id": "ai-billing-workspace-global",
        "title": "AI billing mode (flat vs metered) is one workspace-wide switch",
        "status": "open",
        "what": "events.ai_billing() maps settings.pm.plan to a single display "
                "contract for the WHOLE board: 'max' -> flat (cost surfaces show "
                "tokens, margins skip the phantom $), anything else -> metered. "
                "plan='auto' (default) detects the mode from the ONE workspace "
                "login (usage.login_method: subscription OAuth -> flat, API key / "
                "Console login -> metered) and assumes Claude Code's precedence - "
                "a stored login always wins over an env ANTHROPIC_API_KEY, since "
                "the CLI only uses a key the owner explicitly approved "
                "(customApiKeyResponses), which we cannot see from outside. "
                "Every turn still gets priced (measured economics untouched); only "
                "the rendering and margin math read the switch. Per-card billing "
                "does not exist because every driver shells out to the same "
                "claude CLI login today.",
        "why_it_bites": "On a 'mixed' plan (some turns on the Max quota, some on "
                        "API keys) the switch falls back to metered for everything: "
                        "flat cards then show $-amounts again - the exact bug this "
                        "fixed, now only for the flat half of the fleet. There is "
                        "no per-turn record of WHICH plan billed it, so the split "
                        "cannot be reconstructed from events.jsonl later.",
        "trigger": "adding a driver with its own API key, setting "
                   "settings.pm.plan = 'mixed', or the owner approving an env "
                   "API key inside Claude Code while a subscription login "
                   "exists - auto would keep saying flat while turns bill cash",
        "fix": "Stamp the billing mode per TURN at record time (sessions._record_econ "
               "writes meta into the turn event; add billing='flat'|'metered' from "
               "the driver's auth source), roll it up per card in events.metrics(), "
               "and let the UI render each card by its own mode instead of the "
               "workspace switch.",
        "order": 17,
    },
    {
        "id": "plan-share-calibration",
        "title": "Plan share is calibrated from OUR tokens against the ACCOUNT's quota",
        "status": "open",
        "what": "events.plan_calibration() turns a card's tokens into '% of the "
                "subscription' by dividing the tokens this board burned inside the "
                "live weekly window by that window's utilization "
                "(tokens_per_pct = tokens_in_window / used_pct). Anthropic's usage "
                "endpoint publishes a percentage and never the absolute limit, so "
                "there is no exact allowance to divide by. "
                "settings.pm.plan_tokens_week overrides it when the owner knows the "
                "real number.",
        "why_it_bites": "used_pct covers the WHOLE Anthropic account - Claude Code in "
                        "the owner's own terminal, claude.ai, other machines - while "
                        "the numerator counts only turns this daemon recorded. Every "
                        "token spent outside HelmDeck shrinks the implied allowance "
                        "and inflates every card's percentage proportionally: burn "
                        "half the quota outside the board and cards read ~2x their "
                        "true share. It is an estimate, rendered with '~', never an "
                        "invoice.",
        "trigger": "owner reports card percentages that don't reconcile with the "
                   "usage panel, or heavy Claude use outside HelmDeck",
        "fix": "Use the absolute window limit if the usage endpoint ever exposes one; "
               "otherwise track the delta (account utilization minus our recorded "
               "tokens) as an explicit 'outside this board' slice, show it in the "
               "usage panel, and calibrate against the remainder.",
        "order": 18,
    },
    {
        "id": "legacy-outcome-on-read",
        "title": "Pre-outcome done cards get their outcome derived at snapshot READ time",
        "status": "paid",
        "what": "Cards accepted before the outcome field existed never ran "
                "sessions._record_outcome, so copilot._snapshot fell back to "
                "sessions.extract_outcome(last_reply) on every read for lane=done "
                "cards without a stored outcome. New accepts persist outcome at "
                "EVENT TIME (the accept mutators) - only the legacy tail was "
                "reconstructed on read.",
        "why_it_bites": "Read-time derivation is the reconstruction pattern the "
                        "Paseo law bans for load-bearing state: if extract_outcome's "
                        "heuristics change, a legacy card's remembered result "
                        "silently changes with them, and the PM plan reads it.",
        "trigger": "editing extract_outcome, or auditing why an old done card's "
                   "snapshot line differs from its actual final reply",
        "fix": "PAID (card chat-fix--sessions-extract-ou, 2026-08-12): "
               "sessions.backfill_outcomes() stamps outcome once at daemon start "
               "(key presence = migrated, so '' is a valid stamp); the read-time "
               "fallback in copilot._snapshot is gone. NOT adopted blindly: an "
               "agent reviewed all 44 legacy done cards against their full final "
               "replies - 19 heuristic misses (aside-first replies like chatfork, "
               "merge-meta, junk) carry hand-written values in "
               "sessions._OUTCOME_BACKFILL_REVIEWED.",
        "order": 19,
    },
    {
        "id": "gate-exit-code-vs-stdout-verdict",
        "title": "sessions._gate trusts run_gate.py's PRINTED verdict over a "
                 "contradicting OS-level returncode",
        "status": "open",
        "what": "Card 20260812-164257 (chat-fix--sessions-extract-ou) bounced with "
                "gate_report = 'gate FAILED:' wrapping a body of 34 straight 'ok' "
                "lines ending in tools/run_gate.py's own 'gate: PASS (34 checks)' - "
                "i.e. r.returncode was nonzero even though the script ran every "
                "check green and reached its own sys.exit(0). Replaying the exact "
                "daemon invocation by hand (same HELMDECK_REPO, same cwd, same "
                "cmd.exe shell=True path) came back clean both times - not "
                "reliably reproducible on demand. No HKCU/HKLM Command Processor "
                "AutoRun hook is set (ruled out as a cause). _gate() now regexes "
                "stdout for run_gate.py's own success sentinel and trusts it over "
                "a disagreeing returncode, logging the mismatch to the daemon "
                "console instead of bouncing the card on it.",
        "why_it_bites": "A card can get bounced by the gate for NOTHING - its own "
                        "work is fully green - which reads as a random, "
                        "unexplained rejection and burns a review cycle. The fix "
                        "closes the symptom but is itself a text-match heuristic "
                        "over run_gate.py's print format (fragile if that format "
                        "changes without updating _GATE_PASS_RE) standing in for "
                        "an OS/shell-level root cause that was never pinned down.",
        "trigger": "another card bounces with a gate_report whose body is all "
                   "'ok' lines ending in 'gate: PASS (...)', or editing "
                   "run_gate.py's PASS/FAIL print strings without updating "
                   "sessions._GATE_PASS_RE alongside them",
        "fix": "Pin the real root cause (capture r.returncode AND stdout/stderr "
               "on every gate run, not just failures, so the next occurrence has "
               "full evidence instead of a single anecdote) - most likely "
               "candidates: a Windows shell=True/cmd.exe exit-code relay glitch "
               "under load, or a py-launcher subprocess-teardown quirk. Once "
               "pinned, fix at the source and drop the stdout-verdict override.",
        "order": 20,
    },
    {
        "id": "ios-submit-local-asc-key",
        "title": "eas submit reads the ASC key from a path only THIS box has",
        "status": "open",
        "what": "app/eas.json submit.production.ios pins ascApiKeyPath + "
                "ascApiKeyId + ascApiKeyIssuerId, and the path points at "
                "C:/hd/secrets/AuthKey_*.p8 on the owner's machine. Chosen "
                "because eas-cli's other route - storing the key on EAS' servers "
                "via SetUpAscApiKey - has no non-interactive mode "
                "(AscApiKeySource.js: 'App Store Connect API Keys cannot be set "
                "up in --non-interactive mode'), and a card cannot drive a TTY "
                "prompt. The .p8 itself is NOT committed and stays outside the "
                "repo; only its path and the two non-secret identifiers are, and "
                "those two are already published in DEPLOY.md 2b.",
        "why_it_bites": "eas submit works on the owner's box and nowhere else - "
                        "another machine, a fresh clone or a CI runner dies on a "
                        "missing .p8. It also quietly breaks the rule the rest of "
                        "iOS signing follows (DEPLOY.md 2b: the signing assets "
                        "live in EAS, not in the repo), so the next reader "
                        "reasonably assumes submit is portable when it is not.",
        "trigger": "any eas submit from a different machine or a clean clone, or "
                   "the day the .p8 is moved or rotated",
        "fix": "One interactive `npx eas-cli credentials -p ios` from cmd.exe / "
               "Windows Terminal (NOT Git Bash - MinTTY gives node no TTY, the "
               "trap already written down in DEPLOY.md 2b), uploading the .p8 as "
               "the SUBMISSION_SERVICE key. Then delete the three ascApiKey* "
               "fields from eas.json: getAscApiKeyFromCredentialsServiceAsync "
               "then resolves the key from EAS and every submit is unattended "
               "from anywhere - the same one-time-then-forever shape the "
               "distribution certificate already has.",
        "order": 21,
    },
    {
        "id": "mac-build-never-executed",
        "title": "The macOS build target is configured but has never actually run",
        "status": "paid",
        "what": "desktop/electron-builder.yml now carries a full mac target "
                "(dmg + zip, arm64 + x64, hardened runtime, entitlements, gated "
                "notarization), desktop/build-mac.sh drives it and "
                ".github/workflows/desktop-mac.yml runs it on macos-14. NONE of "
                "it has been executed on macOS. The evidence behind it is: the "
                "config validates against electron-builder's own scheme.json "
                "(both the committed shape and the notarize-object override), "
                "and electron-builder 25.1.8 loads the file and then stops at "
                "exactly one line - 'Build for macOS is supported only on "
                "macOS'. That is the strongest signal a Windows box can "
                "produce, and it is still not a build. Two reasons it could go "
                "no further: there is no macOS here, and at the time "
                "github.com/Tienduyvo/helmdeck held ONLY README.md + release "
                "assets - the source had never been pushed, so no runner had "
                "anything to check out. That half is now DECIDED (owner, "
                "2026-08-14: one repo - the source goes into the same public "
                "repo as the builds) and tooled: deploy/publish_source.sh "
                "audits history for secrets and oversized blobs and pushes "
                "main. Still nobody has run it, and no runner has run.",
        "why_it_bites": "A green-looking config is not a green build. What a "
                        "schema cannot catch: whether `expo export` survives a "
                        "cold macOS runner, whether hdiutil produces both dmgs, "
                        "whether the PNG->icns conversion accepts our icon, "
                        "whether the entitlement set is the RIGHT one for "
                        "spawning python3/claude under the hardened runtime "
                        "(only a notarized run on real hardware proves that), "
                        "and whether Squirrel.Mac accepts the zip feed. Each is "
                        "a separate way the first real run can red, and none is "
                        "visible until someone runs it.",
        "trigger": "the first `bash deploy/publish_source.sh`, or the first "
                   "`bash desktop/build-mac.sh` on any Mac",
        "fix": "PAID 2026-08-15 - run 31877006863 on macos-14, 32m10s, ALL "
               "STEPS GREEN. Every question this item said only a real run "
               "could answer is now answered by that run's log: expo export "
               "survived a cold runner; hdiutil produced BOTH dmgs (imageinfo "
               "passed on each); the tracked PNG converted to .icns with no "
               "Pillow/iconutil; and the entitlement set IS the right one - "
               "build-mac.sh reported 'signing: Developer ID identity "
               "supplied' then 'notarization: ON', electron-builder logged "
               "'notarization successful' TWICE (once per arch), and the "
               "verify step closed it out: `codesign --verify --deep --strict` "
               "-> 'valid on disk' + 'satisfies its Designated Requirement', "
               "`spctl --assess --type execute` -> 'accepted' with "
               "'source=Notarized Developer ID'. Gatekeeper accepts the "
               "artifact. Full set produced: HelmDeck-0.2.0-{arm64,x64}.{dmg,"
               "zip} + blockmaps + latest-mac.yml (the Squirrel.Mac feed). "
               "Benign log noise NOT to 'fix': electron-builder prints "
               "'Please specify notarization Team ID in the APPLE_TEAM_ID env "
               "var instead of notarize.teamId'. The -c.mac.notarize.teamId "
               "override is still what TURNS NOTARIZATION ON (the committed "
               "config keeps notarize:false so an unsigned build can succeed); "
               "the warning is only about where the team id is read from, and "
               "notarization demonstrably worked. Getting there first needed: "
               "1) bash deploy/publish_source.sh (audit + push over SSH - the "
               "gh token has no `workflow` scope, so HTTPS is rejected). "
               "2) The push to the remote DEFAULT branch auto-triggers the "
               "workflow (push: branches: [main]); otherwise Actions -> "
               "desktop-mac -> Run workflow. Flip to 'paid' only when a run "
               "produced all four artifacts + latest-mac.yml and the workflow's "
               "verify step (hdiutil imageinfo per dmg) passed, then confirm "
               "`spctl --assess` accepts the signed app. "
               "SIGNING AND NOTARIZATION ARE NO LONGER BLOCKERS (2026-08-15): "
               "all SIX secrets are live and VALIDATED on the repo - "
               "MAC_CSC_LINK + MAC_CSC_KEY_PASSWORD (cert read back with "
               "openssl: Developer ID Application, issuer G2, EKU Code Signing, "
               "to 2031-08-16, team 92WJZQ2WWH matching APPLE_TEAM_ID) plus "
               "ASC_API_KEY_P8 + ASC_KEY_ID + ASC_ISSUER_ID + APPLE_TEAM_ID, "
               "the ASC key proven to authenticate against Apple live via "
               "mac_credentials.py --check. See DEPLOY.md 1c. A run with NO "
               "secrets is still designed to pass unsigned, so that remains "
               "the fallback smoke test if the signed path reds. What is left "
               "is purely step 1, and it is now blocked on an OWNER DECISION "
               "rather than on tooling: publish_source.sh's new privacy check "
               "fails closed on five .attachments/ chat uploads (the owner's "
               "phone screenshots of his own board - unreleased card titles, "
               "due dates, distribution decisions) that a push would make "
               "public forever, since a push publishes history. Resolve with "
               "either HELMDECK_PUBLISH_ALLOW_PRIVATE=1 (publish them "
               "knowingly) or a git_filter_repo purge of the pushed lineage. "
               "Note also that the trunk is `expo-migration`, NOT `main` - "
               "`main` is a stale 2026-08-12 branch with no .github/ at all.",
        "order": 22,
    },
    {
        "id": "desktop-lock-heuristic",
        "title": "Desktop-control mutual exclusion is a substring match + in-process lock",
        "status": "open",
        "what": "Only one card may hold real Windows desktop control (mouse/"
                "keyboard/screen via windows-mcp) at a time - two such turns "
                "racing would fight over the same cursor. sessions._turn() "
                "guards this with a plain in-process threading.Lock "
                "(_desktop_lock), acquired non-blocking for the synchronous "
                "duration of any turn whose driver's allowed_tools grant a "
                "windows-mcp CONTROL tool (_uses_desktop_control: a wildcard "
                "grant or any tool not on the read-only screen allowlist "
                "{Screenshot,Snapshot,Scrape,DisplayInventory} - fail-safe so "
                "an unknown/new tool still locks; narrowed 2026-08-17 from the "
                "old raw 'windows-mcp' substring match that made a passive "
                "Screenshot card take the exclusive cursor lock). A second "
                "dispatch/steer that needs "
                "desktop control while the lock is held now QUEUES (bounded "
                "blocking acquire, desktop_lock_wait_s, default 960s - sized "
                "to outlive one healthy turn plus the wedge ceilings) and only "
                "bounces with a visible reason after the wait expires "
                "(2026-08-17; was refused outright).",
        "why_it_bites": "(1) The lock is process-local: it is correct only "
                        "because the daemon runs as a single evicting-"
                        "singleton process (server.serve's "
                        "_take_singleton_lock) - if that ever changes "
                        "(multi-worker, multiprocess), two desktop turns could "
                        "run concurrently again with nothing catching it. (2) "
                        "Detection is a string match on 'windows-mcp' in "
                        "allowed_tools, not a derived capability from an "
                        "authoritative registry - it is now capability-aware "
                        "for windows-mcp (read-only vs control) and fail-safe, "
                        "but a future driver granting equivalent desktop "
                        "control under a differently-named MCP server would "
                        "still silently bypass the guard. (3) [PAID in part "
                        "2026-08-17: contention queues instead of bouncing] "
                        "Fail-fast means a legitimate second desktop card just "
                        "bounces/parks; nothing tells the owner to retry once "
                        "the first one frees the lock.",
        "trigger": "the daemon is ever run with more than one process/worker; "
                   "a new desktop-capable driver is added whose tool patterns "
                   "don't contain the string 'windows-mcp'; a desktop turn "
                   "outlives desktop_lock_wait_s (the queued card then bounces "
                   "with the waited-and-gave-up note)",
        "fix": "If multi-process ever happens: move the lock to a file lock "
               "or DB row (same durable-state pattern as turn_active) instead "
               "of in-memory. Replace the capability check with an explicit "
               "per-driver 'desktop: true' flag in settings.json's drivers "
               "config, checked instead of parsing allowed_tools patterns.",
        "order": 23,
    },
    {
        "id": "site-deploy-outside-hook",
        "title": "helmdeck.de ships by hand - accepting a card never deploys it",
        "status": "open",
        "what": "The public site is a Cloudflare Worker (deploy/waitlist/, "
                "worker 'helmdeck-waitlist', custom domain helmdeck.de). Every "
                "other shipping surface rides the repo deploy hook that "
                "sessions._repo_hook fires post-merge on accept; this one does "
                "not. Nothing in the accept path runs `wrangler deploy`, so a "
                "site commit is merged, gated, accepted and still not live. "
                "deploy/push_site.sh now makes the step one canonical command "
                "that self-verifies against the origin, but RUNNING it is still "
                "a human remembering to.",
        "why_it_bites": "It already bit, silently, for two days. Card "
                        "proc-20260814-s7 merged the full landing page "
                        "(39bf69a, 2026-08-15) and helmdeck.de kept serving the "
                        "2026-08-13 waitlist-only build - the owner saw 'nur die "
                        "Waitlist' while the commit log and the card's own "
                        "outcome said shipped. The failure is invisible from "
                        "inside the repo: git log, gate and accept all read "
                        "green, and the card had verified against `wrangler "
                        "dev` instead of the origin. Worse, it is the marketing "
                        "surface - the one place where being stale costs "
                        "signups rather than developer time.",
        "trigger": "any future card that edits deploy/waitlist/src/index.js and "
                   "is accepted without someone separately running "
                   "deploy/push_site.sh",
        "fix": "Add `bash deploy/push_site.sh` to repo_hooks.<repo>.deploy in "
               "settings.json so accept ships the site like it ships everything "
               "else (owner-side edit - settings.json is git-ignored, an agent "
               "cannot make it). Better still, derive it instead of hardcoding: "
               "have the deploy hook ship the site only when the merged diff "
               "touched deploy/waitlist/, which is the Paseo-style 'observe the "
               "runtime signal' version of the same thing. Until then the "
               "origin check `bash deploy/push_site.sh --check` is the backstop "
               "- it exits 1 when live != source and is cheap enough to run "
               "from the loop.",
        "order": 24,
    },
    {
        "id": "build-stale-tracked-sources-only",
        "title": "build_stale() only ever sees the native inputs git status can see",
        # PAID 2026-08-16. It was left OPEN by the step that fixed only the
        # false-POSITIVE half; the title describes the false-NEGATIVE half, and
        # closing the entry then would have retired a blind spot that was still
        # there. Both halves are closed now - see "fix" below.
        "status": "paid",
        "what": "tools/loop_state.py's build_stale() gates on touches_native(touched), "
                "and `touched` comes from `git status --porcelain` (dirty_files()). "
                "app/android/ is entirely git-ignored (app/.gitignore: `/android`), so "
                "a native source edit under app/android/app/src/main can NEVER appear "
                "in `touched` - the reachable trigger set is really just app/app.json "
                "and app/package.json (ARTIFACT_TRIGGERS), a narrower net than the "
                "ARTIFACT_SRC inputs ship.sh's own fingerprint hashes.",
        "why_it_bites": "A change made ONLY inside app/android/ (a manual native tweak, "
                        "a Gradle edit) would not flag BUILD stale even though it really "
                        "did move the native fingerprint - the same class of blind spot "
                        "the fix here just closed for the false-positive direction "
                        "(every card was nagged to rebuild for an artifact it could never "
                        "possess). This is the false-negative shadow of that same gap: "
                        "git-visibility, not the fingerprint itself, decides whether the "
                        "nudge can fire at all.",
        "trigger": "a native-only edit made directly under the ignored app/android/ tree "
                   "(outside app.json/package.json) on the box that actually builds the "
                   "APK, with nothing else touched",
        "fix": "PAID (tools/loop_state.py, 2026-08-16) by REORDERING the two signals "
               "rather than by widening the heuristic. The 2026-08-15 step made "
               "build_stale() take `touched` and return early unless "
               "touches_native(touched) - which killed the false-positive nag on every "
               "quiet card, but left the git-visibility heuristic as a VETO in front of "
               "the authoritative check, which is what this entry's title names. "
               "build_stale() now asks the fingerprint FIRST: when deploy/.native_fp "
               "exists and _native_fp() computes, it compares them and returns, full "
               "stop. That answer is derived from the real native inputs (it hashes the "
               "AndroidManifest under the git-ignored tree too), so git-visibility no "
               "longer decides whether the nudge can fire - the false negative is gone "
               "at its root, without the `git -C app/android status` probe this entry "
               "once proposed (a second reconstructed signal was the wrong shape; the "
               "fingerprint was already the derived one). `touched` still gates the "
               "DEGRADED branches - no marker (never shipped from this checkout) or no "
               "git-bash to compute a fingerprint - which is the only place a guess "
               "belongs, and is exactly the branch a card worktree lands in, so the "
               "false-positive fix holds for a better reason than before: not 'cards "
               "are excluded' but 'we have no authoritative answer here, so do not "
               "invent one'. Covered by tests/test_harness_layer.py (both directions).",
        "order": 25,
    },
    {
        "id": "card-shares-the-operators-auto-memory",
        "title": "a card worker reads and (until this entry) wrote the OPERATOR'S "
                 "personal auto-memory",
        # PAID 2026-08-16. Owner's first reaction to the read/write finding was
        # "isn't it tracked by git, what's the issue with writing this" - a
        # reasonable question, and worth checking rather than either assuming it
        # away or accepting the premise unchecked. It is FALSE: `git -C ~/.claude
        # status` is "not a git repository" and there is no .git anywhere under
        # ~/.claude. So the write really was unrecoverable, and the read-only fix
        # (option b from the original entry) shipped.
        "status": "paid",
        "what": "MEASURED 2026-08-16 against CLI 2.1.207, with the environment scrubbed "
                "of every CLAUDE* variable so the reading is not an artefact of the "
                "probe's own parent session: every surface's init event reports "
                "memory_paths.auto = ~/.claude/projects/C--Users-Tien-Duy-Vo-Downloads-"
                "swarmdeck/memory/ - the operator's personal cross-session memory "
                "directory, shared by every card, every machine task, the board copilot "
                "and the operator's own desktop sessions, unmoved by --setting-sources "
                "(identical under `project` and `\"\"`). Confirmed WRITABLE against the "
                "real spawn path (drivers.build_argv + the shipped card.json, a stream-"
                "json turn on stdin exactly like _ClaudeSession.run_turn) before this fix: "
                "the Write tool created a file in that directory with no permission "
                "prompt under --permission-mode acceptEdits. And confirmed NOT git-backed: "
                "`git -C ~/.claude status` and `git -C <the memory dir> status` both say "
                "'not a git repository (or any of the parent directories)' - there is no "
                ".git anywhere in the operator's ~/.claude tree, so a card's write there "
                "had no revert path.",
        "why_it_bites": "harness/ exists to stop the operator's personal ~/.claude layer "
                        "reaching a sandboxed worker. It closed the SETTINGS half of that "
                        "leak (hooks, the model pin, skillOverrides) and this half was "
                        "never noticed, because nothing rendered it: /harness's provenance "
                        "view showed settings layers and the hook matrix, not memory_paths. "
                        "Two consequences, both real. (1) Personal context leaks INTO a "
                        "card - the memory dir holds the owner's notes, not the card's. "
                        "(2) Memory being writable meant a card could silently edit notes "
                        "every future session of every card and the operator's own desktop "
                        "would read as background context - shared mutable state outside "
                        "the worktree, the one thing worktree isolation exists to prevent, "
                        "and with no git history to recover from a bad write.",
        "trigger": "was: any card spawn - the steady state, not an edge case, and it bit "
                   "the moment a card wrote a memory file (the memory instructions ship in "
                   "the system prompt, inviting exactly that). Now: none - the write is "
                   "denied at the permission layer before it reaches disk.",
        "fix": "SHARE BUT READ-ONLY (option b of the three originally proposed), verified "
               "against the real CLI in both directions before shipping - the same "
               "'measured, not assumed' standard as probe_harness_settings.py. "
               "harness/settings/card.json and harness/settings/copilot.json now deny "
               "`Write(~/.claude/projects/**)` and `Edit(~/.claude/projects/**)`, the SAME "
               "Read/Write/Edit tool-pattern mechanism that already protects "
               "daemon/settings.json two lines above it - no new mechanism introduced. "
               "Read is left open, so a card still benefits from accumulated notes; only "
               "the write is closed. Measured before AND after: the real "
               "drivers.build_argv() + card.json spawn wrote the file with the deny "
               "absent, and the identical spawn got `<tool_use_error>File is in a "
               "directory that is denied by your permission settings.</tool_use_error>` "
               "with it present - for both the Write tool (new file) and the Edit tool "
               "(modifying an existing one). `~` in the pattern is honoured by the CLI, "
               "measured the same way. Also shipped: harness.preview()'s "
               "`_memory_isolation()` reads each surface's OWN settings file at preview "
               "time and reports whether its deny list actually covers this - so a future "
               "edit that removes the line is visible in /harness the same way a "
               "disappearing hook is, rendered in app/src/ui/harness_section.tsx as a "
               "write-protected/WRITABLE row. Deliberately NOT computed: the exact value "
               "of memory_paths.auto (option c's literal ask). The CLI derives that slug "
               "from a project identity that measurably is not just \"this cwd\" - every "
               "card worktree probed resolved to the SAME directory despite different "
               "cwds - and guessing that derivation to render it live would be exactly the "
               "unverified reconstruction CLAUDE.md's NO MONKEY PATCHES rule forbids. What "
               "IS shown is honestly derivable from the file alone: does this surface's "
               "actual deny list cover it, right now.\n\n"
               "COMPLEMENTARY HALF - VERSIONING, now a system rather than a one-off. The "
               "owner asked whether the memory directory should simply be made recoverable "
               "instead of blocked. Both, not either: the deny above stops a card's write "
               "from being adopted as background context before anyone notices, which git "
               "history alone would not prevent (a bad write still lands and is read by the "
               "NEXT session before any revert). What git adds is what the deny "
               "structurally cannot - recoverability for the OPERATOR's own interactive "
               "sessions, which the deny never gated and which are now the only writers. "
               "Shipped as tools/memory_autocommit.py, a Stop hook deployed to "
               "~/.claude/hooks/ by tools/install_memory_hook.py and wired into "
               "~/.claude/settings.json. It sweeps EVERY ~/.claude/projects/*/memory/, "
               "git-inits any that holds notes without a repo, and commits what changed - "
               "so a project created next month is covered with no action taken (the owner's "
               "explicit ask: 'establish system so each project in the future gets proper "
               "tracking'). Commits carry the session_id from the hook payload, which is "
               "what makes a later revert decidable. Local only: it never adds a remote and "
               "never pushes, asserted in tests/test_memory_autocommit.py by scanning its "
               "own source. Its ONE law is daemon/harness.py's law - it can never break a "
               "turn: a Stop hook exiting 2 BLOCKS the turn, so main() returns 0 "
               "unconditionally, every git call is timeout-bounded, and the test drives a "
               "missing root, a file where a directory belongs, a repo mid-merge, a missing "
               "git binary and a sweep() that raises, asserting exit 0 through all of them. "
               "Canonical copy stays in the repo with the deployed copy held byte-identical "
               "by `--check`, because fixing untracked state with an untracked script would "
               "have been a joke at its own expense. Verified live: 7 memory directories "
               "bootstrapped, audited for credential-shaped content (none) and for remotes "
               "(none).",
        "order": 26,
    },
    {
        "id": "null-result-test-races-under-load",
        "title": "tests/test_null_result.py races on subprocess frames and can red "
                 "an innocent card when the box is busy",
        "status": "open",
        "what": "Observed 2026-08-16 during the /glance card: a full gate run "
                "failed ONE check - 'fresh spawn: guard scoped to resume only "
                "(out=%r)' - reporting out='real-answer' where the test pins "
                "out=''. The same test passed standalone twice immediately "
                "after, and the very next full gate run passed 55/55. The only "
                "changes in the working tree at that moment were Markdown docs, "
                "which cannot reach drivers.py. The distinguishing condition was "
                "LOAD: three subagents and a Playwright browser had just been "
                "running. The test spawns a real subprocess (fake_claude via a "
                ".cmd wrapper) and asserts which result FRAME wins; under load "
                "the null frame it expects to count appears to be overtaken by "
                "the later real one.",
        "why_it_bites": "This is the gate-bounces-an-innocent-card class again, "
                        "but from a different direction than "
                        "gate-exit-code-vs-stdout-verdict: here the gate is "
                        "reporting a REAL failing check, so no verdict-level "
                        "heuristic can catch it. A card that touched nothing "
                        "near the driver gets held on Review with a report about "
                        "null-result frames, which reads as an unexplained "
                        "rejection and burns a review cycle. It is also worse "
                        "than a plain flake because the gate is the harness's "
                        "one objective signal - a gate that is sometimes wrong "
                        "quietly teaches the owner to re-run instead of read.",
        "trigger": "any card whose gate reds ONLY on tests/test_null_result.py, "
                   "especially while other work is running on the box; or the "
                   "same shape appearing in another test that spawns "
                   "fake_claude and asserts frame ordering",
        "fix": "Make the assertion deterministic instead of timing-dependent: "
               "have fake_claude emit the null and real frames with an explicit "
               "ordering barrier the test can wait on (or drive the frame pump "
               "directly rather than through a real subprocess), so 'which frame "
               "wins' is decided by the code under test and not by scheduler "
               "luck. Until then, do NOT paper over it by retrying the gate.",
        "order": 27,
    },
    {
        "id": "direct-build-no-gate",
        "title": "DIRECT build cards edit the live tree with no gate and no isolation",
        "status": "open",
        "what": "sessions.new_direct_task (owner-requested, Paseo semantics) "
                "files a card whose workplace is the repo's LIVE working tree: "
                "machine=True rides the no-worktree dispatch/accept path, so "
                "there is no branch, no merge, and NO gate-before-review - the "
                "agent's edits land in the tree the owner is looking at, "
                "immediately. Two direct cards on the same tree are serialized "
                "in _turn (bounded queue per normalized tree path, the desktop-"
                "lock pattern), so they cannot edit blind over each other.",
        "why_it_bites": "(1) A direct card can break the tree and nothing red "
                        "stops it - the gate law is deliberately bypassed for "
                        "this card class; the repo's own hooks/loop-state are "
                        "the only guard rail. (2) A direct card and the OWNER "
                        "editing the same files at the same time still race - "
                        "the per-tree lock serializes cards, not humans. (3) "
                        "Uncommitted owner work in the tree is exposed to the "
                        "agent's edits; there is no snapshot to roll back to "
                        "unless the agent (or owner) commits first.",
        "trigger": "a direct card is dispatched onto a tree with uncommitted "
                   "owner changes; a direct turn goes wrong and there is no "
                   "gate to bounce it; the owner edits while a direct turn runs",
        "fix": "Make the dispatch snapshot the tree first (a lightweight "
               "baseline commit or stash-ref, same nothing-lost rule as "
               "worktree reclaim) so every direct turn has a rollback point; "
               "surface 'direct card active on this tree' in the app while a "
               "turn runs; consider an optional post-turn gate run (advisory, "
               "non-blocking) so red at least becomes visible.",
        "order": 28,
    },
    {
        "id": "plugin-kernel-dual-nav",
        "title": "Plugin kernel boots alongside expo-router (two navigation systems)",
        "status": "open",
        "progress": "ec7e307: the PRODUCTION tab set is now registry-driven — root "
                    "_layout boots the 'app' profile + provides the kernel; "
                    "(tabs)/_layout renders <Tabs.Screen> from the nav.tabs surface "
                    "plugin with a 1:1 hard-coded fallback (never bricks). "
                    "Screenshot-JUDGED at both breakpoints (desktop sidebar + phone "
                    "bottom bar) identical to before. REMAINING: the Sidebar's own "
                    "NAV array is still hard-coded; per-screen COMPONENTS are not "
                    "yet surface plugins (only their nav metadata is); kernel-demo "
                    "still exists as the dev route.",
        "what": "app/src/kernel/ (Phase 1) + app/src/boot/ (Phase 2) introduce a "
                "plugin-first composition: profiles pick swappable plugins, "
                "surfaces register into KEYS.SURFACES, a registry-driven host "
                "renders them. But production navigation still runs through the "
                "hard-coded expo-router app/src/app/(tabs) list. The only surface "
                "actually wired through the kernel is a dev route "
                "(app/src/app/kernel-demo.tsx) rendering the board from the "
                "registry; the real (tabs) screens are unchanged. Engines are "
                "half-migrated too: engines.claude wraps the daemon api behind the "
                "Engine contract, but the ~11 scattered `import copilot` / "
                "`import claude_sessions` branches in daemon/server.py + "
                "sessions.py still select backends inline.",
        "why_it_bites": "Two nav systems mean a screen can drift between the (tabs) "
                        "route and its surface plugin; a profile (store/owner/demo) "
                        "does NOT yet govern what production ships, so the "
                        "pre-config story is only true for the demo route. Adding a "
                        "new screen needs doing twice until the cutover lands.",
        "trigger": "adding/removing a screen; shipping a store build expecting the "
                   "store.json profile to exclude machine-control (it doesn't gate "
                   "production nav yet); adding the deepseek engine",
        "fix": "Phase 2 cutover card: make app/src/app/(tabs)/_layout render tabs "
               "from useSurfaces() (KEYS.SURFACES) instead of the static list, "
               "migrate each (tabs) screen into a surfaces/* plugin, and delete "
               "the hard-coded list in the same commit that adds its plugin. "
               "Phase 2b: replace the inline daemon backend-select branches with "
               "an engine registry keyed by a stored `engine` field. Boot the "
               "real profile (owner on desktop, store on stores) at app entry so "
               "pre-config governs production, then retire kernel-demo.tsx.",
        "order": 29,
    },
    {
        "id": "full-dynamism-decree",
        "title": "Charter reframed: fixed harness -> seeded+swappable modules, "
                 "universal tracking is the only floor",
        "status": "open",
        "what": "Owner decree (2026-08-17): move to the DeepSeek 'everything is a "
                "plugin' model, but (1) everything must be TRACKABLE and (2) the "
                "old rules are not deleted, they are SEEDED as defaults. The app "
                "kernel (app/src/kernel) implements this: nothing is unswappable "
                "(unload/swap allowed on seed governance too), but every "
                "load/unload/swap appends a TrackEntry {op, pluginId, actor "
                "(seed|profile|user|agent|system), replaced?, note} to an "
                "append-only journal; swap() returns a rollback(); the charter "
                "(gate-before-review, append-only audit, worktree isolation, "
                "auth-required, measured economics, WIP limit) is seeded as data "
                "in boot/policies.ts CHARTER_DEFAULTS under KEYS.POLICIES. This "
                "CONTRADICTS the CLAUDE.md law 'never weaken the fixed harness' "
                "and the 'core refuses unload' enforcement (now removed).",
        "why_it_bites": "The daemon-side enforcement is still MOSTLY hard-wired "
                        "code that owns its own on/off. PROGRESS: policy.py is the "
                        "control plane (swap() mirrors a 'reconfig' event into the "
                        "append-only events sink); GET /policy + POST /policy/swap "
                        "expose it; the app hydrates the seeded modules from it via "
                        "a tracked swap; ONE real consumer now reads it "
                        "(events.metrics wip_limit -> policy.get_policies, seeded "
                        "from settings so non-divergent). REMAINING: gate / "
                        "auth / economics / worktree enforcement still don't read "
                        "the PolicySet; the APP kernel journal() is not yet "
                        "mirrored into events (only daemon-side swaps are); and "
                        "charter.py (the CONNECTOR SANDBOX, distinct from the "
                        "instruction charter) stays human-only by design.",
        "trigger": "wiring the super-agent's reconfiguration authority; letting a "
                   "UI toggle a policy; any claim that governance is swappable",
        "fix": "Daemon-side: (1) mirror the app journal into the existing "
               "append-only events.py sink so reconfiguration is audited with the "
               "same guarantees; (2) have charter.py/gate/economics READ the "
               "seeded PolicySet instead of hard-coding, so a tracked swap "
               "actually changes enforcement; (3) expose an engine/policy control "
               "plane the user (UI) and super-agent call, every call recorded, "
               "every swap reversible; (4) CLAUDE.md/charter is itself a SEED "
               "MODULE now (app/src/boot/charter.ts, seed.charter, KEYS.CHARTER) "
               "- changing it is a tracked, reversible swap of seed.charter that "
               "materializes as an edit to the CLAUDE.md file, NOT an out-of-band "
               "approval gate (that framing was the retired fixed-harness reflex; "
               "the sign-off WAS the decree). agentMaySwap defaults false so an "
               "agent-initiated charter swap still wants a human confirm until "
               "seeded true. Daemon-side: point loop_state/charter.py at the "
               "seeded CharterDoc so on-disk CLAUDE.md and the module stay one "
               "source; mirror charter swaps into events.py.",
        "order": 30,
    },
    {
        "id": "daemon-god-files",
        "title": "Daemon god-file breakup — SUBSTANTIALLY RESOLVED: 23 service/"
                 "route modules extracted, server.py's ENTIRE route surface "
                 "is now dispatch-table-driven (2109 -> 478 lines); pm.py's "
                 "notice cluster investigated and DECLINED (confirmed genuinely "
                 "coupled, not just assumed)",
        "status": "open",
        "what": "The full-dynamism decree made the APP a plugin composition; this "
                "extends the same idea to the daemon by extracting SERVICES "
                "bottom-up (trackstore/locks/turn-execution first, so higher "
                "modules become thin dependents instead of reaching into a "
                "monolith - the DeepSeek kernel/plugin model applied to Python). "
                "Every extraction below is a strangler move verified against the "
                "FULL 11-file test suite (0 failures) plus an identity check "
                "(orig.fn IS new_module.fn) - re-export means every existing "
                "caller, internal and external, is unchanged.\n"
                "\n"
                "sessions.py 3927 -> 1046 (73% cut), 17 modules: gitutil.py (git+"
                "worktree primitives, extended twice with _worktree_for/_base_ref/"
                "_worktree_of_branch), econ.py (turn economics), blockers.py "
                "('what needs the owner'), outcomes.py (outcome extraction), "
                "worktrees.py (reclaim/sweep), trackstore.py (the data-layer "
                "SERVICE - _load/_save/_mutate; the monkeypatched tests were "
                "updated to fake trackstore._db instead of sessions._db, the "
                "technique proving patched clusters ARE extractable), locks.py "
                "(turn/desktop/direct locks + steer epoch), turnrunner.py + "
                "devport.py (turn execution: _turn/_finish_turn/_settle_reply), "
                "lanemachine.py (the gate/merge crown jewel: move_lane/_gate/"
                "_merge_to_main/_repo_hook - only 4 lazy back-refs, needed NO test "
                "changes because the test-exercised entry point stayed in "
                "sessions.py), dispatch.py (new_track/machine-task/direct-task - "
                "the SAME cluster that failed with 19 back-refs on the first "
                "attempt now extracted with ZERO, because every dependency was "
                "already a service by the time it was reached), cardadmin.py "
                "(archive/update/fork/history/attachments), lifecycle.py "
                "(present()/sweep_zombies - lifecycle observation).\n"
                "\n"
                "drivers.py 1490 -> 990 (NO LONGER a god-file), 3 modules: "
                "agentcli.py (argv/MCP-config), proctable.py (PID/process table - "
                "MONKEYPATCHED, needed no test change since patched fns' callers "
                "stay in drivers), spawnenv.py (_env/_card_env).\n"
                "\n"
                "copilot.py 1136 -> 1012, 2 modules: copilot_stats.py (PM-session "
                "economics), copilot_actions.py (reply/action parsing).\n"
                "\n"
                "pm.py 2192 -> 1992, 1 module: pm_budget.py (budget/quota math + "
                "the pure quota-notice text builders _fmt_when/_usage_flag_text/"
                "_goal_budget_text + the two hard gates _quota_floor/"
                "_triage_green - surgically separated from the STATE-COUPLED "
                "notice functions _usage_checkin/_plan_gate_notice that stayed, "
                "since they call pm's mutable loopstate).\n"
                "\n"
                "server.py 2109 -> 1073 (49% cut), 8 module-level-helper modules "
                "(glances.py/apimeta.py/startup.py, as below) PLUS the H "
                "handler's do_GET/do_POST if-chain now has a real DISPATCH-TABLE "
                "seam with THIRTEEN route groups converted (~40 routes total): "
                "routes_auth.py (5: auth/state/setup/register/login/logout), "
                "routes_policy.py (3: /policy, /policy/swap, /reconfig/track), "
                "routes_settings.py (5: /settings GET+POST, /nightshift, /usage, "
                "/automation), routes_glance.py (4: /glance, /glance/voice/<id>."
                "mp3 [first PREFIX route - GET_PREFIX_ROUTES, an ordered list "
                "checked before the exact-match dicts], /glance/talk, /glance/"
                "answer), routes_info.py (6 read-only: /debt, /charter, /loop/"
                "map, /models, /harness, /harness/schema - also exposed + "
                "removed a pre-existing DEAD duplicate /harness block further "
                "down do_GET, unreachable since the dispatch check runs first), "
                "routes_pm.py (6: /pm/economics, /pm/plan, /pm/config, /pm/"
                "consolidate, /pm/report, /pm/reconcile), routes_misc.py (3: "
                "/processes, /me, /processes/new), routes_control.py (5: "
                "/control/state, /control/teach/start,stop, /control/distill, "
                "/control/demo), routes_relay.py (2: /relay/pair,unpair), "
                "routes_connectors.py (3: /connectors list + /connectors/<name>/"
                "rollback,run - the rollback/run guard is path-param [parts[0]/"
                "parts[2]] and stays inline in server.py, only the body moved), "
                "routes_checkpoints.py (3: /checkpoints list + /checkpoints/"
                "<id>/diff,restore - same path-param-guard-stays-inline "
                "technique, diff/restore route bodies verified with a REAL "
                "create/list/diff/restore round-trip against a sandboxed CPDIR, "
                "not just role-gate assertions), routes_projects.py (4: /"
                "projects GET+POST, /projects/<id>/update,delete - path-param "
                "guard inline; caught along the way that projects.new_project "
                "requires fixed_price for billing='fixed', a real validation "
                "rule the test now exercises rather than assumes), routes_"
                "copilot.py (4: /chat/history, /chat/live, /chat/cancel, /chat "
                "- the real copilot.chat() model turn is NEVER invoked by the "
                "test [cost/network/non-determinism]; caught along the way that "
                "copilot.history() returns {messages,session_id,stats}, not a "
                "bare list - the test asserted the real shape after a first "
                "wrong assumption failed loudly, not silently). ~40 routes "
                "converted; ~26 of the original ~66 remain inline.\n"
                "\n"
                "14th SLICE (2026-08-18), THE CROWN JEWEL: the tracks/dispatch "
                "cluster - the routes that sit directly on sessions.py's gate/"
                "merge state machine (lanemachine.py's move_lane -> _gate -> "
                "_merge_to_main). Split into TWO modules by risk, per the task "
                "brief's own suggestion: routes_tracks.py (14 routes - CRUD/"
                "reads: GET /tracks, /tracks/<id>/live,turns,history,transcript"
                "[+/live],checkpoints,attachments,attachment/<name>; POST /"
                "tracks/reorder,new,<id>/archive,fork,fork-chat,delete,update,"
                "rewind,attach[+/remove]) and routes_track_actions.py (5 routes "
                "- the gate/dispatch-critical half kept ISOLATED for extra "
                "scrutiny: GET /tracks/<id>/stream [live transcript SSE], POST "
                "/tracks/<id>/steer,answer,cancel,lane). Every route body moved "
                "VERBATIM (byte-identical, grep-verified no body left "
                "duplicated in both server.py and the new modules); path-param "
                "routes keep their guard inline in server.py per the "
                "routes_checkpoints.py precedent, only the body moved as a "
                "function taking the extra path segment(s). server.py: 1073 -> "
                "740 lines.\n"
                "\n"
                "test_server_routes.py grew a dedicated tracks-cluster section "
                "driving the REAL state machine end-to-end (not just role-gate "
                "assertions): files a card against a real temp git repo, lists "
                "it, updates/archives/attaches[+detaches] it, reads its history/"
                "transcript/checkpoints, then exercises BOTH gate outcomes for "
                "real - GATE BLOCKED (never dispatched -> lanemachine._gate's "
                "own \"never dispatched\" problem, card bounces) and GATE "
                "PASSING (dispatched via the real ->working path, a clean "
                "worktree with no helmdeck.gate file advances past the gate) - "
                "plus reorder, fork/fork-chat/rewind against an unknown id (400, "
                "RuntimeError caught not a 500), and a real owner-gated delete. "
                "drivers.run is stubbed (same seam test_direct_task.py/"
                "test_desktop_lock_wait.py already use) so every dispatched/"
                "steered turn is instant and network-free while the REAL "
                "worktree/lane/gate machinery still runs.\n"
                "\n"
                "THREE real bugs found and fixed along the way (none caused by "
                "the route move itself - the route bodies are byte-identical; "
                "all three were latent in the sessions.py extraction and only "
                "surfaced because this was the first test to dispatch/gate a "
                "REAL card end-to-end): (1) cardadmin.py was missing `import "
                "subprocess` and `import db as _db` - delete_track's worktree/"
                "branch cleanup NameError'd, turning DELETE /tracks/<id> into a "
                "500; (2) dispatch.py was missing `from devport import "
                "_alloc_dev_port` - a NameError on first dispatch; (3) runs.REC "
                "(a card's run_dir root) is a THIRD independent __file__-"
                "derived global (same class of bug as connectors.CDIR/"
                "checkpoints.CPDIR, see the orphan-root-paths entry below) - "
                "dispatch.py/cardadmin.py/sessions.py each hold their OWN bound "
                "copy from `from runs import REC`, so patching runs.REC alone "
                "doesn't reach them. MEASURED THE HARD WAY: an early draft of "
                "this test filed real cards straight into the live daemon/"
                "recordings/ folder before the guard existed (git-ignored, no "
                "tracked data harmed, but a real sandboxing violation the test's "
                "own rules forbid) - now patches runs.REC + dispatch.REC + "
                "cardadmin.REC + sessions.REC together, before any card is "
                "filed. NOTE for the owner: a handful of stray test-created "
                "directories from before this fix landed (daemon/recordings/"
                "*req-x*, *req-gate-smoke-card*) are still sitting in the real, "
                "git-ignored recordings/ folder - harmless (never tracked, no "
                "real card data) but worth a manual `rm -rf` cleanup.\n"
                "\n"
                "PREREQUISITE BUILT FIRST (test_server_routes.py): server.py had "
                "almost no test coverage on its live HTTP surface. This spins up "
                "server.H on a REAL ThreadingHTTPServer bound to 127.0.0.1:0 "
                "(ephemeral port, never :8140 - cannot collide with or evict a "
                "live daemon; serve() itself is NEVER called since it takes the "
                "singleton port lock) and drives 10 real HTTP requests across "
                "auth/policy/tracks/dashboard/loop-map. TRAP HIT WHILE BUILDING "
                "THIS (documented in the test file): db.init() reads/migrates "
                "ROOT/tracks.json and ROOT/events.jsonl using the db.ROOT global, "
                "NOT db.DBPATH - a first draft that sandboxed only DBPATH actually "
                "renamed the REAL daemon/events.jsonl to .imported (30 real "
                "events). Caught immediately, recovered (pure rename, renamed "
                "back, live daemon on :8140 confirmed healthy throughout) - fixed "
                "by sandboxing db.ROOT before any db call. Lesson: db.py's file-"
                "import side effects are keyed off a DIFFERENT global than the "
                "one that looks like 'the' sandboxing point - verify the FULL set "
                "of module-level path globals before assuming a test is isolated.\n"
                "\n"
                "PATTERN (repeatable, proven 13 TIMES RUNNING): each route body "
                "moves VERBATIM into a routes_<concern>.py free function taking "
                "(self, user[, body]) - self._send/_sid/_send_cookie/rfile/"
                "headers all keep working since self is passed through unchanged. "
                "do_GET/do_POST gain one dispatch-table check each, BEFORE the "
                "remaining inline if-chain, so every unconverted route is byte-"
                "identical. EXTENSION for path-param routes (parts[0]==X and "
                "parts[2]==Y, e.g. /connectors/<name>/rollback or /checkpoints/"
                "<id>/diff): the guard condition itself stays inline in server.py "
                "(there is no generic PARAM_ROUTES table yet - only the route "
                "BODY moves, as a function taking the extra path segment as a "
                "plain argument, e.g. connectors_rollback_post(self, user, name)). "
                "Verify with test_server_routes.py + the full suite + a "
                "processes.json/events.jsonl/settings.json/users.json/helmdeck.db "
                "md5sum integrity check after EVERY group.\n"
                "\n"
                "PM.PY: pm_state.py extracted (touch()/loopstate/_in_window/"
                "_board_idle - the presence + daily-loop-gate SERVICE). The "
                "remaining notice/watch functions (_usage_checkin, "
                "_plan_gate_notice, _triangle_watch, _cost_watch, review_burn "
                "cluster) deliberately STAYED in pm.py: they call _ask/_say/"
                "_escalate to compose text and talk to the user - that IS pm's "
                "own domain logic (the PM's voice), not trapped infrastructure. "
                "Moving them would relocate the coupling, not remove it.\n"
                "\n"
                "METHOD LEARNED (do not repeat the mistake): always run a full "
                "dependency scan (module-DEFINEs vs external-refs, filtering "
                "comment/docstring mentions from real calls) BEFORE cutting a line "
                "range - a naive contiguous slice sweeps in unrelated consts that "
                "happen to sit nearby (BLOCKER_REASONS/LANES/LANE_FLOW/MODES were "
                "each caught this way and deliberately left behind). flow()/"
                "LANE_FLOW were deliberately NEVER moved: flow() does "
                "`_decl_lines(path=os.path.abspath(__file__), rel=\"daemon/"
                "sessions.py\")` - a self-referential source-line lookup that "
                "would silently misattribute if the file moved.",
        "why_it_bites": "server.py is now 478 lines (from 2109) with 16 route "
                        "groups extracted (routes_auth/policy/settings/glance/"
                        "info/pm/misc/control/relay/connectors/checkpoints/"
                        "projects/copilot/tracks/track_actions/runs/system.py). "
                        "The 2026-08-18 session's second pass converted the "
                        "final residual grab-bag: routes_runs.py (/runs list, "
                        "/live.jpg, and the /runs/<id>/{timeline,playbook,video,"
                        "videochunk} path-param sub-router) + routes_system.py "
                        "(/presence GET+POST, /push/register, /sessions/claude, "
                        "/history, /harness[+/harness/version/<kind>/<name>], "
                        "/debt/<id>/fix, /import/jira,url, /nightshift/plan, and "
                        "the /processes/<id>/step path-param sub-router). Every "
                        "path-param route kept its parts[]-guard inline in "
                        "server.py per the routes_checkpoints.py precedent - only "
                        "the route bodies moved, verbatim. Verified with real HTTP "
                        "assertions added to test_server_routes.py for EVERY "
                        "newly-moved route (including the processes/step "
                        "sub-router's non-'step' 404 fallthrough and runs_item_get's "
                        "match/no-match signal), full 16-file suite green, "
                        "processes.json/settings.json/users.json/helmdeck.db "
                        "byte-identical (md5) before/after. There is no longer any "
                        "route body left inline in do_GET/do_POST except the "
                        "auth/role branching and the parts[]-guards the pattern "
                        "itself calls for - server.py's route-dispatch breakup is "
                        "DONE, not just the crown jewel.\n"
                        "\n"
                        "pm.py's notice cluster (_usage_checkin/_plan_gate_notice/"
                        "_triangle_watch/_cost_watch/_needs_from_owner/the "
                        "review_burn pair/_goal_process/_goal_process_status) was "
                        "READ IN FULL and compared line-by-line against pm_budget.py "
                        "(the one extraction from this cluster's neighborhood that "
                        "DID succeed cleanly). The difference is real, not assumed: "
                        "pm_budget.py's functions are PURE - they take an econ dict/"
                        "est_turns/pace as parameters and do their own lazy "
                        "`import usage` for live data, with zero references back "
                        "into pm.py. The notice functions are not that shape: each "
                        "one reads/writes the shared `st` (loopstate) dict AND "
                        "calls straight back into pm.py's own module-level surface "
                        "- _save_loopstate(st), get_goal(), latest_plan(), "
                        "_triage_green(plan), _pace()/_days(), _i18n.t(...), and "
                        "_say()/_escalate() to actually speak to the owner - "
                        "typically 4-8 distinct back-references per function, not "
                        "the 1-2 a clean extraction needs. A thin State-carrier "
                        "class (as this debt entry used to suggest) does not "
                        "remove that coupling, it only renames it: the notice "
                        "functions would still need pm.py's plan/goal/triage state "
                        "and its _say/_escalate voice, so pm_notices.py would end "
                        "up doing `import pm` and calling back through it anyway - "
                        "moving the code without moving the coupling, exactly the "
                        "outcome this entry already warned against for the prior "
                        "review_burn cluster. DECLINED, now on read evidence "
                        "instead of a guess.",
        "trigger": "adding a new HTTP route (server.py's if-chain, now small); "
                   "any claim the daemon's API surface is not fully modular",
        "fix": "server.py: DONE. Every route group has a routes_*.py home; what "
               "remains inline (auth/role gates, LEGACY_UI redirect, the SSE/"
               "long-poll routes, the parts[]-guards for path-param routes) is "
               "either genuinely server.H's own job or a deliberate precedent "
               "(routes_checkpoints.py/routes_tracks.py) to keep dispatch guards "
               "next to the if-chain that reads them. No further server.py "
               "extraction is planned - if do_GET/do_POST grow again, repeat the "
               "same proven pattern for the new group only.\n"
               "pm.py: DECLINED for the notice cluster, confirmed by reading the "
               "code (not by re-guessing the earlier note) - see why_it_bites. "
               "Revisit only if pm.py's size becomes the active bottleneck AND a "
               "restructure of pm's plan/goal/voice state into an explicit object "
               "is independently worth doing (a real behavior change, not a pure "
               "code move) - at that point the notice functions extract for free "
               "as a side effect, which is a different, larger task than this one.",
        "order": 31,
    },
    {
        "id": "orphan-root-paths-events-jsonl-incident",
        "title": "Modules with their own hardcoded ROOT path silently bypass "
                 "db.py sandboxing in tests — one real incident, partially fixed",
        "status": "open",
        "what": "While route-testing /processes (test_server_routes.py, part of "
                "the daemon-god-files work): processes.py had its OWN flat-file "
                "storage (processes.json, hardcoded ROOT/STORE), independent of "
                "the db.ROOT/db.DBPATH sandbox every other test relied on. "
                "Testing /processes/new wrote 3 fake entries into the REAL "
                "daemon/processes.json - caught immediately, removed by exact-id "
                "match, real data (6 legitimate processes incl. the HelmDeck-"
                "Glasses-Layer one) verified intact by direct read. FIXED for "
                "processes.py (commit with this entry): it now delegates _load()/"
                "_save() to new db.processes_all()/db.processes_replace() "
                "functions (same id/data-blob table pattern as tracks/projects); "
                "db.init() migrates processes.json into the table once, renamed "
                "to *.imported (same safeguard as tracks.json/events.jsonl). "
                "Zero call-site changes needed in processes.py (all ~15 sites "
                "were already read-all/mutate-by-id/write-all). Verified with a "
                "dedicated sandboxed migration test (test_processes_db_migration."
                "py, 10/10) using SYNTHETIC data, never the real file.\n"
                "\n"
                "SECOND, related gap found while verifying the fix: events.emit() "
                "(the append-only audit sink) writes through events.py's OWN "
                "independent ROOT/EV globals - never covered by db.ROOT or even "
                "events.SET. processes.create()/sync() call it directly, so the "
                "FIRST test run against the new /processes routes appended 11 "
                "real lines to the production events.jsonl even with db.py fully "
                "sandboxed (6 clearly test-tagged actor=\"routetest-owner\"/"
                "\"test\"; 4 misleading-but-harmless \"completed\" log lines for "
                "two real processes whose actual STORED STATE was never touched "
                "- confirmed by reading their status/steps directly: both still "
                "show status=\"done\" with sensible step data, not sandbox-"
                "mutated garbage). events.EV is now sandboxed in both test files "
                "(test_server_routes.py, test_processes_db_migration.py). "
                "Re-verified with md5sum before/after (byte-identical) rather "
                "than the earlier file-size/mtime \"looks unchanged\" check, "
                "which is NOT sufficient to catch a pure append.\n"
                "\n"
                "OWNER DECISION (2026-08-18): the 11 already-appended events."
                "jsonl lines are NOT deleted. CLAUDE.md's append-only-audit law "
                "('never weaken... append-only audit/events') applies to test "
                "pollution the same as any other entry - the fix is to prevent "
                "recurrence, not to edit history. They remain as a small, "
                "honestly-labeled, permanent artifact of this session "
                "(timestamps 2026-08-18 11:30:56-11:41:32, kind=\"process\", "
                "greppable by actor=\"routetest-owner\"/\"test\").",
        "why_it_bites": "This is a CLASS of bug, not a one-off: any module that "
                        "computes its own `ROOT = os.path.dirname(os.path.abspath"
                        "(__file__))` and derives a storage path from it (instead "
                        "of going through db.py) is invisible to the db.ROOT "
                        "sandbox pattern every daemon test now relies on. Found "
                        "twice in one session (processes.py's STORE, events.py's "
                        "EV) purely by accident (a failing test assertion led to "
                        "manual debugging that happened to surface it) - there is "
                        "no automated check that a new test's sandbox is "
                        "complete, so a THIRD module with the same shape (grep "
                        "candidates: connectors.py, checkpoints.py, teach.py, "
                        "wincap.py, voice.py - anything with its own `ROOT =` "
                        "line) could silently repeat this the next time a route "
                        "touching it gets smoke-tested. CONFIRMED by grep (not "
                        "guessed): connectors.py (CDIR), checkpoints.py (CPDIR + "
                        "a direct settings.json/users.json path dict), and "
                        "voice.py (CACHE) each have their own `ROOT =` and a "
                        "derived storage directory, none covered by the current "
                        "sandbox. teach.py/wincap.py/presence.py were checked and "
                        "do NOT have this pattern.\n"
                        "\n"
                        "FOURTH instance found 2026-08-18, NOT by grep this time - "
                        "by a real test failure surfacing it: the routes_tracks.py "
                        "extraction's new end-to-end test hit GET /chat/history "
                        "returning real production messages on a 'fresh sandboxed "
                        "DB' assertion, because copilot.py has its own "
                        "`ROOT = os.path.dirname(...)` with CHATLOG/SESS (plus "
                        "copilot_runs/ and .copilot_attachments/ directories) none "
                        "of which test_server_routes.py sandboxed. READ-only leak "
                        "(GET /chat/history), not a write - no real data was "
                        "corrupted, only read past the sandbox boundary. Fixed: "
                        "copilot.ROOT/SESS/CHATLOG now patched in "
                        "test_server_routes.py's setup, same as connectors/"
                        "checkpoints/runs.REC above. Confirms the grep sweep from "
                        "the original incident was incomplete - a `ROOT =` grep "
                        "finds candidates but doesn't guarantee every derived "
                        "directory (copilot_runs/, .copilot_attachments/) is "
                        "covered by the same audit; the shared sandbox-helper idea "
                        "in fix (3)/(4) below would prevent this shape of miss "
                        "structurally instead of per-module.",
        "trigger": "writing a NEW daemon test that imports any module with its "
                   "own `os.path.join(ROOT, ...)` storage path; adding a new "
                   "route-dispatch group whose routes call into an unaudited "
                   "module",
        "fix": "(1) DONE: processes.py migrated into db.py (removes its ROOT/"
               "STORE entirely - the class of bug can't recur for this module "
               "because there is no longer a second path to bypass). (2) DONE: "
               "events.EV sandboxed in the two test files that currently exist. "
               "(3) INVESTIGATED (2026-08-18), then ACTED ON per-module rather "
               "than blanket-declined - connectors.py, checkpoints.py, voice.py "
               "each read in full to check whether the processes.py pattern "
               "(JSON blob -> db table) applies:\n"
               "  - connectors.py: DONE. CDIR holds the actual EXECUTABLE .py "
               "files (loaded via importlib.util.spec_from_file_location, run "
               "in a separate sandboxed subprocess - the file must exist on "
               "disk to import/exec) plus a _versions/ rollback archive; those "
               "stay on disk (not a db.py fit - would break the isolation "
               "model). Its small connectors/_state.json (last-run timestamps, "
               "a plain dict) WAS the processes.json shape - migrated: db.py "
               "gained a `connector_state` table + connector_state_get()/"
               "connector_state_put() (single-row dict, not one row per id - "
               "there is only ever one state dict), a _migrate() block that "
               "imports connectors/_state.json once and renames it .imported, "
               "and connectors._state()/_save_state() now delegate to db.py. "
               "Verified with test_connectors_db_migration.py (sandboxes "
               "db.ROOT AND connectors.CDIR/VDIR - CDIR is a second, "
               "independent global the db.ROOT patch alone would NOT catch).\n"
               "  - checkpoints.py: DECLINED, same conclusion as before but "
               "now test-covered rather than just noted. CPDIR holds "
               "directory-tree SNAPSHOTS (shutil.copytree of settings.json + "
               "the whole connectors/ dir, restored via shutil.copy2) - the "
               "value IS the file tree, not a value you'd unpack into a row; "
               "forcing it into db.py would be a real architecture change "
               "(tree-vs-blob semantics), not a mechanical extraction. Instead "
               "added test_checkpoints_db_migration.py which sandboxes CPDIR "
               "(+ROOT, since _snapshot_targets() derives settings.json/"
               "connectors from it) to a temp dir and exercises create/list/"
               "diff/restore end to end against synthetic data - the actual "
               "risk this debt item is about (a test writing into the real "
               "checkpoints/ dir or the real settings.json) is now closed by "
               "a green test, not just an assertion in this file.\n"
               "  - voice.py: DECLINED, same conclusion, same treatment. "
               "CACHE holds binary mp3 files served by URL and by raw-bytes "
               "base64 inlining - forcing these into db.py's id/data-TEXT "
               "table would mean base64-encoding audio into SQLite text for "
               "no functional gain. Added test_voice_db_migration.py, "
               "sandboxing CACHE alone and exercising path_for()/stats()/"
               "_prune() (traversal guard, missing-dir tolerance, MAX_FILES "
               "eviction) against synthetic files - render()/render_b64() "
               "need edge_tts + network so are intentionally left untested "
               "here (that is voice.available()'s fails-soft path, not this "
               "debt item's concern).\n"
               "All three new test files were run against a REAL freshly-"
               "created tempfile.mkdtemp() sandbox, never daemon/'s real "
               "connectors/, checkpoints/, voice_cache/, processes.json, "
               "events.jsonl, settings.json, users.json, or helmdeck.db - "
               "confirmed by md5sum before/after (byte-identical) for every "
               "real file, plus a directory-entry-count check for connectors/, "
               "checkpoints/, voice_cache/, both before and after the full "
               "daemon test suite ran clean (all 16 test_*.py files, "
               "including the 3 new ones, zero regressions). "
               "(4) OPEN: a SHARED test-sandbox helper (a single "
               "`sandbox_daemon_storage(tmp)` function patching db.ROOT/"
               "db.DBPATH, events.EV/events.SET, auth.USERS/auth.SESS, "
               "connectors.CDIR/VDIR, checkpoints.CPDIR, voice.CACHE all in "
               "one place) would still be worth adding so a future test "
               "author doesn't have to re-derive this list from scratch - each "
               "of the three new tests above hand-rolls its own subset today. "
               "(5) DONE going forward: this session's migration/sandbox work "
               "verified with md5sum/checksum, not file-size+mtime, per the "
               "earlier lesson that mtime cannot distinguish 'untouched' from "
               "'grew by a plausible amount'.",
        "order": 32,
    },
    {
        "id": "cell-registry-daemon-plugin-kernel",
        "title": "Cells: agentic systems as pluggable units - daemon registry + "
                 "Connectors/PM/Process/Copilot cells shipped (Phase 0-2), Phase 3 "
                 "pending",
        "status": "open",
        "what": "Owner decree: the unit of modularity is an agentic SYSTEM (a "
                "'Cell' - a role like PM or Engineer), each bundling {logic, "
                "storage, harness/role, API routes, UI surface, lifecycle, "
                "enable-flag}, plugged into a shared spine, addable/removable/"
                "swappable without editing the spine. This is the daemon-side "
                "realization the full-dynamism-decree (order 30) deferred ('no "
                "daemon-side plugin registry exists'). Phase 0 SHIPPED: "
                "daemon/cells.py (pure-data Cell registry, 5 cells - engineer/pm/"
                "process/connectors/copilot); server.py do_GET/do_POST gate a "
                "path owned by a disabled cell (cells.path_disabled, ONE derived "
                "check after auth, no per-route edits); boot's flat start_*() "
                "calls -> cells.start_enabled() loop; 5 <cell>Enabled policy "
                "flags (all true) toggled through the EXISTING tracked "
                "policy.swap; GET /cells manifest; keys.ts PolicySet mirror. Zero "
                "behavior change while all enabled (verified: 16-file suite green, "
                "real files md5-identical). Phase 1 SHIPPED (Connectors, the "
                "reference cell, conformed end-to-end): "
                "app/src/plugins/surfaces/connectors.tsx (Surface+Plugin pair, id "
                "'surfaces.connectors', strangler-wraps the existing (tabs)/"
                "connectors.tsx screen with zero logic moved) registered in "
                "AVAILABLE_PLUGINS (app/src/boot/index.ts), filling the dead "
                "owner.json reference; api.cells() added to app/src/data/client.ts "
                "(typed CellInfo[], mirrors GET /cells); (tabs)/_layout.tsx gates "
                "both the bottom-bar and desktop-sidebar tab lists generically off "
                "the /cells manifest (useDisabledCellSurfaces + "
                "isSurfaceCellDisabled, keyed by surface id / route suffix, not "
                "hardcoded to 'connectors' - cells 2-5 pick it up automatically "
                "once they register a Surface with nav+route); modules.tsx got a "
                "CELLS section (id/role/surface/modes + a Switch through the "
                "existing setPolicy -> POST /policy/swap path). tsc --noEmit "
                "clean; /cells fetch failures fall back to an empty list "
                "everywhere (never crashes Modules, never blocks nav). "
                "Phase 2 SHIPPED (PM, Process, Copilot conformed, same "
                "template): app/src/plugins/surfaces/{pm,processes,copilot}.tsx "
                "(Surface+Plugin pairs, ids 'surfaces.pm'/'surfaces.processes'/"
                "'surfaces.chat' matching daemon/cells.py's Cell.surface and the "
                "owner.json/store.json profile references exactly) registered in "
                "AVAILABLE_PLUGINS; pm.tsx composes the two existing PM pieces "
                "(ui/pm_panel.tsx's PMStatusPanel + app/loopmap.tsx's "
                "LoopMapScreen) into one dashboard component, processes.tsx/"
                "copilot.tsx strangler-wrap (tabs)/processes.tsx and app/chat.tsx "
                "unmodified, same as Connectors. (tabs)/_layout.tsx's nav-gate "
                "filter (useDisabledCellSurfaces/isSurfaceCellDisabled) needed NO "
                "further edits - re-verified generic (keys off any surface's "
                "`surface` field against the live /cells manifest, not "
                "hardcoded to a specific id). Cross-cell-hook guards added, ONE "
                "owner per hook (NO-MONKEY-PATCH): pm.on_card_done and pm._tick "
                "both gain a `cells.enabled_id(\"pm\")` early-return (the _tick "
                "one is ADDITIONAL to the existing loop_enabled check - a "
                "DIFFERENT flag, the owner's proactive on/off, not the whole-cell "
                "kill switch); processes.clear_step_stamps gains the same guard "
                "for \"process\". processes.sync/_priority_dispatch/_autopilot "
                "got NO extra guard: they only run via start_chain_poller, which "
                "cells.start_enabled() never launches when processEnabled is "
                "false at boot, and their only route entry (GET /processes -> "
                "routes_misc.processes_get -> sync()) is already 404'd by "
                "cells.path_disabled before the handler runs. copilot.py got NO "
                "guard at all, deliberately: copilot.say() is called BY pm.py/"
                "lanemachine.py (cross-cell PM->copilot voice, e.g. "
                "lanemachine.py:462, pm.py:1814) rather than the other way "
                "round, so gating it would silently swallow a legitimate "
                "cross-cell message from a cell that IS enabled; the copilot "
                "cell has no `start` lifecycle in cells.py (no poller to guard) "
                "and its own surface is exactly its /chat* routes, already "
                "gated by server.py's cells.path_disabled check from Phase 0. "
                "Tests: test_server_routes.py's cell-gate section extended with "
                "the same disable/spine-stays-up/re-enable round trip for "
                "process (/processes) and copilot (/chat/history), plus a "
                "direct-call assertion that processes.clear_step_stamps no-ops "
                "on a seeded stamp while processEnabled=false and clears it for "
                "real once re-enabled (proves the guard, not a broken test). "
                "16-file daemon suite green, real files (processes.json/"
                "events.jsonl/settings.json/users.json/helmdeck.db) md5-"
                "identical before/after. tsc --noEmit clean.",
        "why_it_bites": "Phase 0-2 cover the registry, daemon gating, all four "
                        "non-Engineer cells' surfaces, and their cross-cell-hook "
                        "guards. NOT yet done: the Engineer cell's own lifecycle "
                        "(reconciler/watcher) is still a spine call in serve(), "
                        "not registry-driven, and its /tracks routes aren't "
                        "stress-tested under disable (Phase 3, done last - it is "
                        "the gate/merge crown jewel).",
        "trigger": "adding a new agentic system; a UI toggle for a whole system; "
                   "any claim the daemon is fully cell-modular",
        "fix": "Phase 1+2 DONE (see above). Phase 3: Engineer "
               "(+ machine/direct as its MODES, gated by policy.machine not a "
               "cell flag) last, with the tracks-cluster gate/merge round-trip "
               "re-verified.\n"
               "DESIGN DECISION (evidence-backed, not an omission): machine-"
               "control and direct-task are NOT peer cells - they are MODES of "
               "the Engineer cell (a card variant with machine=True, forking only "
               "at dispatch.py:160 dispatch, _accept_machine no-merge accept, and "
               "drivers._agent_for role selection; sharing the same track store, "
               "gate, worktree, and merge state machine). Registering them as "
               "peers would duplicate the gate/merge machinery. They stay gated "
               "by the existing policy.machine, with their own role file "
               "(machine-worker.md) and the recordings surface.",
        "order": 33,
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
