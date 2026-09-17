# henry-brief-thinning

Owner ask 2026-09-17: "das Henry system hat zwar mehr definiert aber falsch,
muss man das nicht dünner machen". Trigger incident: Henry told the owner the
27-run Jev benchmark was aborted while it was running (10:24). He had followed
the brief ("answer a status question by calling board_state.py"); the tool
omitted background work, and he filled the gap with a broken process scan.

Line: STATE belongs in tools (code), JUDGEMENT belongs in the brief (prose).
Prose that explains how the system works goes stale in silence.

## Measured (board-copilot.md, 27.8 KB body)

| share | what | verdict |
|---|---|---|
| 16 % | character, voice, never-dead-end | stays verbatim |
| 22 % | judgement wrapped in incident history (dates, measurements, quotes) | keep the rule + one clause of why, drop the story (git holds it) |
| 25 % | wire format: reply shape, action shapes, memory syntax | stays, exact |
| 10 % | system behaviour inside action lines (hands, follow_up, direct_task) | one clause inline, the rest -> `board-copilot.d/actions.md` |
| 6 % | compensation for tool gaps (dup check, stale check, status rule) | two sentences stay; the real fix is in the tool (below) |
| 10 % | tools intro + on-demand index | stays, tightened |
| 11 % | second statement of what the on-demand index already says | merged into the index entry |

Result: `board-copilot.proposed.md`, 13.2 KB (-54 %). Checked mechanically:
all 17 `{{rule:...}}` placeholders and all 34 action verbs are still present.

New: the EVIDENCE paragraph (board tools answer "what runs", an empty result
is not a finding, name disagreeing signals).

## Status 2026-09-17: LIVE

1. DONE 0ef4a913 - brief written through `write_agent()`; `actions.md` carries
   the hands details, `charter` is its own on-demand section; pinned hash and
   the six-section / 15k-cap test moved in the same commit. Henry's process
   respawns on its own (`_brief_fp` is part of the persist key).
2. DONE - ONE reading of "does this card still work": `sessions_bg.running_bg`,
   read by the board snapshot, `daemonctl.background_work` (status + the
   restart refusal `background_active`) and `restart_daemon.py`. Found on the
   way: the in-app restart verb checked live TURNS only and would have killed
   the benchmark; test_daemonctl 6b pins it and fails on the old code.
   Daemon-side half needs a restart to load.
3. DROPPED - "file_card answers with the matching active card". Whether two
   cards cover the same work is a similarity JUDGEMENT; code holds hard
   invariants only (dual-architecture decree), and a fuzzy matcher would be a
   registered shortcut from day one. The one sentence in the brief stays.
4. OPEN - judge on real turns: "Was laeuft gerade?", a QUICK fix ask, a BIG
   fuzzy ask, a permission-file ask, a "Danke". Tone and first-word latency
   must not move.

Risk: the incident stories may be what makes some rules stick. If a rule
regresses in step 4, restore ITS one story, not the whole block. The old brief
is in `ops/harness/.versions/` (2026-09-17_11-07-03) and in git before 0ef4a913.
