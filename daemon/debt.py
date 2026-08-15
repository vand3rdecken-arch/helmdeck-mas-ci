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
        "status": "open",
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
        "fix": "1) bash deploy/publish_source.sh (audit + push over SSH - the "
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
                "duration of any turn whose driver's allowed_tools contains a "
                "pattern matching the substring 'windows-mcp' "
                "(_uses_desktop_control). A second dispatch/steer that needs "
                "desktop control while the lock is held is refused outright "
                "(RuntimeError), which the existing dispatch/steer paths "
                "already surface as a bounced card / needs_you note - it does "
                "NOT queue or auto-retry.",
        "why_it_bites": "(1) The lock is process-local: it is correct only "
                        "because the daemon runs as a single evicting-"
                        "singleton process (server.serve's "
                        "_take_singleton_lock) - if that ever changes "
                        "(multi-worker, multiprocess), two desktop turns could "
                        "run concurrently again with nothing catching it. (2) "
                        "Detection is a string match on 'windows-mcp' in "
                        "allowed_tools, not a derived capability from an "
                        "authoritative registry - a future driver granting "
                        "equivalent desktop control under a differently-named "
                        "MCP server would silently bypass the guard. (3) "
                        "Fail-fast means a legitimate second desktop card just "
                        "bounces/parks; nothing tells the owner to retry once "
                        "the first one frees the lock.",
        "trigger": "the daemon is ever run with more than one process/worker; "
                   "a new desktop-capable driver is added whose tool patterns "
                   "don't contain the string 'windows-mcp'; two desktop cards "
                   "dispatched back-to-back (second one bounces silently "
                   "unless the owner reads the note)",
        "fix": "If multi-process ever happens: move the lock to a file lock "
               "or DB row (same durable-state pattern as turn_active) instead "
               "of in-memory. Replace the substring match with an explicit "
               "per-driver 'desktop: true' flag in settings.json's drivers "
               "config, checked instead of grepping allowed_tools. Consider "
               "an automatic re-dispatch/notification when the lock frees, "
               "instead of leaving the bounced card for the owner to notice.",
        "order": 23,
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
