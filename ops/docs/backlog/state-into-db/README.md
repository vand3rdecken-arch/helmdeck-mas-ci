# state-into-db - runtime state written as files that belongs in the db

**Trigger (owner, 2026-09-12):** `daemon/board_full.txt` (283 lines, 104 KB)
showed up as an uncommitted file. "Why are things like this not saved in the
db but as file. Need full refactor."

**Root cause of the trigger, traced (session transcript, 2026-09-11 22:01Z):**
the PM planner (`cells/copilot/planning/pm.py` `brief()`, Sonnet 5, cwd
`daemon/`) ran `board_state.py --full`, got a 105k-char text blob it could not
search inside a turn, and redirected it to a file (`> /tmp/board_full.txt`,
then `> board_full.txt`) so it could Grep it. Three things allowed that:

1. **The tool answered a query with a dump.** `--full` is the whole board as
   prose. The planner needed "cards about Play Store", not 29k tokens.
   (`--find`/`--card` were added the same night, uncommitted - that is the
   fix for the NEED.)
2. **The permission layer cannot stop a shell redirect.** `pm.json` allows
   `Bash(py -3.12 ../ops/tools/board_state.py:*)`; the `:*` prefix rule
   accepts `... > file`. `--permission-mode plan` did not stop it either
   (Bash is "read-only" only by the model's judgement).
3. **The planner's cwd is the repo.** Any accidental write lands in
   `daemon/` and shows up in `git status`.

So the file is agent scratch, not a HelmDeck store - but the same sweep
found the REAL offenders: state HelmDeck itself writes as files although the
rule (debt `config-consolidation-and-canonical-cell-structure`, ARCHITECTURE
storage section) says config and id-keyed JSON records live in `helmdeck.db`.

---

## The rule (existing, restated so every item below is judged by it)

| class | goes to | why |
|---|---|---|
| config (anything exportable/importable per install) | db (`workspace_config`, `policy_doc`, `user_config`, `project_config`) | owner decree: "wenn es hier bleibt erreicht es niemanden" |
| records keyed by id (cards, events, memory, chat, escalations, plans, runs, versions) | db, one table per kind, append-only where the law says so | transactions, indexed queries, one backup story |
| machine-local bookkeeping a *foreign process* must read (pid, locks, gpg conf, chrome profile, `daemon-dir.txt`) | file under `daemon/state/` or the OS location the foreign program dictates | nothing else can open a SQLite row |
| byte artifacts (mp4, mp3, jpg, apk, model weights, uploads the CLI needs as paths) | disk under `daemon/content/` or `recordings/` | ARCHITECTURE declined db for these on purpose |
| client-side caches and credentials (app SecureStore/AsyncStorage, glasses localStorage) | device | offline mirror or secret that must never reach the daemon |
| scratch produced by an agent turn | OS temp, swept | never inside the repo tree |

## Inventory - every runtime write found (3 sweeps: daemon/, spine+cells, surfaces+ops)

### A. MOVE TO DB (JSON/JSONL records or config, no external reader)

| path | writer | size / growth | db target |
|---|---|---|---|
| `daemon/recordings/<run>/timeline.jsonl` | `spine/agent/timeline_store.py:70 append` | **54.6 MB / 134 files**, one row per streamed step, forever | `timeline(run_id, seq, ts, kind, data)` append-only |
| `daemon/recordings/<run>/actions.jsonl` | `spine/ops/actionlog.py:30 ActionLog.log` | 2.6 MB / 320 files | `actions(run_id, seq, ts, data)` append-only |
| `daemon/recordings/<run>/meta.json` | `spine/ops/runs.py:13-32` | 14 small docs, list_runs = dir scan | `runs(id, kind, title, status, started, ended, data)` |
| `daemon/state/escalations.jsonl` | `spine/registry/escalations.py:24 _append` | 386 KB, full re-parse on every `fold()`/`list_open()` | `escalations(seq, id, ts, kind, track, data)` append-only; open-set folded by query |
| `daemon/state/copilot_log.json` | `cells/copilot/chat/copilot.py:743 _append_log` | 58 KB, whole-file read-modify-write per Henry turn (the `json-storage` lost-update shape, db.py:26-38 admits it) | `chat(seq, ts, user, role, data)`; `_chat_version` stays; `history(have=N)` becomes a `WHERE seq > ?` |
| `daemon/pm/plan-*.json`, `pm/activity.jsonl`, `pm/loop.json` | `pm.py:330`, `pm_comm.py:41`, `pm_state.py:17` | 992 KB, 1 file/day unbounded; loop.json hot-written (debt `pm-loopstate-races`) | `pm_plans(day PK, data)`, `pm_activity(seq, ...)`, loop state = `workspace_config` row in one transaction |
| `daemon/state/copilot_sessions.json`, `copilot_stats.json`, `copilot_models.json` | `copilot.py:10-11`, `copilot_stats.py:14` | 3 small key docs | `runtime_doc(key PK, data, updated_at)` generic table |
| `daemon/state/sessions.json`, `invites.json` | `spine/auth/auth.py:167 _save`, `invites.py:38` | small, auth state | `auth_sessions(token_hash PK, user, created, expires)`, `invites(code PK, data)` |
| `daemon/devices.json` | `spine/auth/devices.py:38 _save` | small, hashed push tokens, **not git-ignored** | `devices(id PK, data)` |
| `daemon/state/models_cache.json` | `spine/agent/turnopts.py:152` | 753 B cache | `runtime_doc` (or drop: safe to recompute) |
| `daemon/asc_review_watch.json` (+ `.log`) | `ops/tools/asc_review_watch.py:68` | last-seen review status for dedupe | `runtime_doc` key `asc_review`; transitions = `events` rows, `.log` retired |
| `daemon/backups/reset-log.jsonl` | `ops/tools/reset.py:92` | audit of resets | `audit_ops(seq, ts, actor, op, data)` - separate table so an events wipe cannot erase it (the one honest reason it was a file) |
| `daemon/restart_verify.log` (the verdict lines) | `ops/tools/verify_restart.ps1:18` | only record that a restart succeeded | `events` kind `restart` emitted by `startup.py` from the runtime's own signal (pid changed + port bound), not by the script |
| `ops/harness/.versions/**` | `spine/registry/harness.py:783 _keep_version` | 32 KB now, one full copy per brief edit, never pruned, no external reader (restore goes through Python) | `harness_versions(kind, name, stamp, actor, text)` |
| `daemon/checkpoints/<id>/settings.json` copy | `spine/ops/checkpoints.py:23` | copies a file that no longer exists as the store | checkpoint = snapshot of the db config rows (`workspace_config`/`policy_doc`) into `checkpoints(id, data)`; the `connectors/` copytree stays a dir (code) |
| `daemon/events.jsonl` + `.synced` | `spine/storage/events.py:311 emit` file-first, db best-effort | 727 KB, unbounded, dual store | **flip authority**: db first inside the transaction, file demoted to an export (`ops/tools/export_events.py`), `.synced` dies with it. Phase 6, owner decision gate (audit law). |
| `.loop/workorder.md`, `.loop/history/*.md` | `ops/tools/loop_state.py:577, 271` | per-worktree loop state; two cards can disagree about "the" workorder | `workorders(tree_key, ts, data)`; hooks keep calling `loop_state.py`, which reads the db (`cell-6-buildloop-self-governing` stays true: still no HTTP round-trip) |
| `daemon/connectors/_versions/*.py` | `connectors.py:59 _archive` | code snapshots for rollback | `connector_versions(name, stamp, source)`; live `.py` stays on disk (importlib) - low priority |
| `daemon/signkeys/<user>/pubkeys/*.asc` | `spine/auth/signkeys.py:151` | public keys (records) | `signing_keys(user, fpr, armored)`; the gpg home + agent conf stay files - low priority |

### B. SCRATCH - delete the mechanism, not just the file

| path | writer | fix |
|---|---|---|
| `daemon/board_full.txt` (and the earlier `board_full_tmp.txt`) | PM planner shell redirect | delete; Phase 0 closes the hole |
| `daemon/recordings/<run>/live_partial.txt`, `live_session.txt`, `daemon/content/copilot_runs/<user>/live_*.txt` | `drivers.py:1240,1460`, `copilot.py:1352 _cwrite` | single-writer streaming buffers read by a poller in the SAME process: in-memory dict keyed by run/user, exposed by the existing poll route. `live_session.txt` = the session pointer, which `sessions.resume_detached` already owns in the db - the file is a second owner (law: exactly ONE owner) |
| `daemon/recordings/_henry/` | `henry_broker.py:694` | a run row with kind `henry-ship`, no placeholder dir |
| `.loop/*.log`, `.loop/*.txt`, `.loop/artifacts/*.aab`, `.loop/tmp/`, `daemon/tmp/`, `.git-commit-msg.tmp` | ad-hoc agent shells | sweep; agent briefs get the rule "scratch goes to `%TEMP%`, never the tree" |
| `ops/tools/stt_bench_results.json`, `.claude/scheduled_tasks.lock` | tools / harness | gitignore + move under temp |

### C. STAYS A FILE (justified, listed so nobody re-litigates)

`daemon/daemon.pid`, `~/.helmdeck/locks/android-build/*`, `.loop/ship.lock`
(cross-process locks); `daemon/gxp.lock` (hand-editable out-of-band control -
but add it to .gitignore); `daemon/signkeys/*/gnupg/*`, `daemon/certs/*`,
`%LOCALAPPDATA%/HelmDeck/chrome-profile/`, `~/.claude/.credentials.json`,
`~/.helmdeck-opencode-home/` (foreign programs dictate the path);
`%TEMP%/helmdeck-briefs/*.md`, `--settings` json, `--mcp-config` (the claude
CLI takes file paths, swept by age); `daemon/relay_feed.json` (dependency-free
Node updater cannot read SQLite - mirror of a db row, keep); `<userData>/
daemon-dir.txt` (bootstrap pointer to the db, cannot live in it);
`daemon/board_directives.json`, `policy_seed.json`, `app.json`, generated
tokens (tracked source); `daemon/users.json` (credentials, ARCHITECTURE:294
keeps it flat - unchanged here); `*.log` (console capture, rotation is a
separate card); `.attachments/`, `*.mp4/.jpg/.mp3`, `models_stt/`, `.pending/`
staging (byte artifacts); app `helmdeck.config/profile/qcache/outbox/drafts/
demo/analytics` and glasses `localStorage` (device caches and credentials);
`daemon/*.imported` (migration markers).

Dead already: `daemon/policy_live.json` (no writer since 2026-08-18, `policy.load()`
fallback only) and `daemon/nightshift/state.json` (writer removed). Phase 1
deletes the fallbacks and archives the files.

---

## Phases

Each ships alone. Each cut-over is atomic per store: import -> archive to
`backups/*.imported` -> old writer deleted in the SAME commit. No dual-writer
period - the events dual store is the measured lesson.

### Phase 0 - close the hole the trigger came through (half day, direct card)
1. `board_state.py`: `--full` stays for humans; the planner's `EVIDENCE_TOOLS`
   only names `--find`, `--card`, `--live`; every mode caps stdout (12 hits,
   `--card` at 8k chars) so nothing a planner sees is worth dumping.
2. Planner cwd = a per-run `tempfile.mkdtemp("hd-pm-")`, tools invoked by
   absolute path; pm.json allowlist entries updated to the absolute form.
   A redirect now lands in temp and is swept. Same check for Henry's cwd.
3. Delete `daemon/board_full.txt`. Do NOT gitignore `daemon/*.txt` (it would
   hide the next symptom). Instead `loop_state.py` DEBT state flags any
   untracked, non-ignored file under `daemon/` as a state leak.
4. Test: run the planner path with a fake `claude` that emits `> leak.txt`;
   assert the repo tree is byte-identical after the turn. Prove it fails on
   the old cwd.

### Phase 1 - dead weight + gitignore gaps (half day)
`policy_live.json` fallback removed, file archived; `nightshift/` removed;
`.gitignore` gets `daemon/devices.json`, `daemon/gxp.lock`,
`ops/tools/stt_bench_results.json`, `.claude/scheduled_tasks.lock`; `.loop/`
sweep of logs and `.aab` files.

### Phase 2 - the append-only records (2 days, worktree card)
`escalations`, `actions`, `runs`, `timeline` tables. Shared shape:
`(seq INTEGER PK AUTOINCREMENT, run_id/track TEXT, ts TEXT, kind TEXT, data TEXT)`,
index on `(run_id, seq)`. Writers become `db.append(table, ...)` under the
existing per-thread `conn()`; readers become `WHERE run_id=? AND seq>?`,
which also pays item 3 of the `chat-load-latency` card (timeline full re-parse
per long-poll tick). Migration at boot: for every `recordings/<run>/*.jsonl`
present and not yet imported, stream rows in, verify counts, rename to
`.imported` (nothing-lost). Media stays where it is; `runs.list_runs` reads
the table. Append-only law: no UPDATE/DELETE path exists for these tables;
a `db_guard` test asserts it.

### Phase 3 - Henry's chat log (1 day)
`chat` table with `seq`; `_append_log` = one INSERT; `history(have=N)` = range
query; `chat_dedupe` reads the tail by seq. `bump_chat()` unchanged. Import
the existing json once, archive. Measure `/chat/history` before and after
(goal: no full-file parse per turn).

### Phase 4 - PM artifacts + the small key docs (1 day)
`pm_plans`, `pm_activity`, `runtime_doc(key, data, updated_at)`. `loop.json`
becomes a `runtime_doc` row written in one transaction - pays
`pm-loopstate-races`. `latest_plan()`/`_recent_plans()` = `ORDER BY day DESC
LIMIT n`. `copilot_sessions/stats/models`, `models_cache`, `asc_review_watch`
move to `runtime_doc`. The `.log` twins retire; state changes emit events.

### Phase 5 - auth records, harness versions, workorders, checkpoints (2 days)
`auth_sessions`, `invites`, `devices`, `harness_versions`, `workorders`,
`checkpoints` (config snapshot as a row; connectors dir copy unchanged),
`audit_ops` for the reset log. `loop_state.py` reads `workorders` keyed by
the worktree path-shape hash already used for worktree ownership (P4), so
the Stop/SessionStart hooks keep working with no HTTP round-trip.

### Phase 6 - events.jsonl authority flip (owner decision, 1 day after yes)
Today the file is the record and the db the index. Proposal: `emit()` inserts
into `events` first, in the transaction, and raises if that fails (no more
`except: pass`); the jsonl is dropped as a store and `ops/tools/export_events.py
--since` produces it on demand for auditors. Reconcile-on-boot and `.synced`
are deleted. The append-only audit law is kept by the table having no
UPDATE/DELETE path (same guard test as Phase 2). If the owner wants a
second physical copy for GxP, it is a periodic export, not a second writer.

### Phase 7 - in-memory streaming buffers (half day)
`live_*.txt` replaced by a process-local `LiveBuffer` registry keyed by
run/user; `live_session.txt` deleted because the session pointer already has
its ONE owner in the db (`sessions.resume_detached`).

## Cross-cutting rules for every phase
- One writer per store; the old file writer is deleted in the same commit
  the table lands. No shim that writes both.
- Migration = import + archive (`db._archive`, existing), never delete; counts
  verified before the rename.
- Tests run the REAL dispatch path (owner decree 2026-09-11) and sandbox by
  `db.DBPATH` + the module's own bound path constant (daemon/paths.py rule);
  the `_migrate` refusal guard (`dirname(DBPATH) != ROOT`) stays.
- Any phase that ships partially registers `state-files-<phase>` in
  `spine/registry/debt.py` in that commit; the whole card registers
  `state-into-db` (open) with Phase 0 as first payment.
- `loop_state.py` DEBT state gains: "untracked file under daemon/ not matched
  by .gitignore" - that is how the trigger class gets caught in seconds next
  time, by code, not by the owner's diff view.

## Measurements that decide "done"
- `git status` after a full PM plan turn + a Henry turn: zero untracked files.
- `/chat/history` and `/tracks/:id/transcript/live` cost per call: bounded by
  `have`, not by history length (time it on the 2.4 MB card).
- `daemon/` listing after Phase 5: db, certs, signkeys, connectors (code),
  content/ (artifacts), recordings/ (media + `.imported`), state/ (pids only),
  logs. Nothing else.

---

## Scoring log

Criteria, 1-5 each: root-cause fidelity, law compliance, migration safety,
test proof, scope discipline, measurability. Score = mean.

**v1 (3.0):** "move every daemon/ json into the db". Root cause 2 - it treated
the trigger as a storage bug when the file was planner scratch; law 3 - would
have moved checkpoints/voice which ARCHITECTURE explicitly declined, and
`relay_feed.json` which a SQLite-less Node process reads; migration 2 - no
per-store atomic cut-over, would have re-created the events dual-writer;
test 3; scope 4; measurability 4.

**v2 (4.0):** added the traced trigger + Phase 0, the classification table,
the "stays a file" list, atomic import-archive cut-overs, per-thread db
appends. Weak spots: events flip stated as a done deal (audit law needs the
owner, 3), no proof-of-failure tests (3), timeline/actions ordering not tied
to the measured pain (`chat-load-latency` item 3), `live_session.txt` missed
as a second owner of the session pointer.

**v3 (4.6, this document):** events flip gated on owner decision with the
export path; every phase names the failing-on-old-code test; Phase 2 ordered
first because it is 57 MB of the 60 MB on disk and shares the long-poll bug;
second owner removed in Phase 7; `loop_state.py` leak detector makes the
trigger class visible without a human. Remaining deduction: Phase 5's
`workorders` keying by worktree hash is designed, not measured - confirm the
SessionStart hook stays sub-second with a db read before committing to it.
