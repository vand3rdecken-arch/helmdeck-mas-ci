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

## Before the proposal may replace the live brief

1. `board-copilot.d/actions.md`: add the WHEN/HOW for `hands` (HelmDeck
   Chrome, tab dies with the process, owner-only secrets = failed report,
   serialized, TOO_BIG split), `direct_task` (when file_card instead, queue
   per tree, fast_track ships every turn), `follow_up`. Text = the paragraphs
   removed from lines 178/179/185 of the current brief.
2. New on-demand section `charter` (current lines 206-233) + register the
   name in `ops/tools/henry_brief_get.py`.
3. Tools carry the state the prose compensated for:
   - DONE a9656624: snapshot line states `BACKGROUND-RUNNING=n (titles)`.
   - one busy derivation (driver pids + chat turns + running bg_tasks) read
     by snapshot, `restart_daemon.busy()` and the app - today three readers,
     three sources.
   - `file_card`/`machine_task` answer with the matching ACTIVE card instead
     of relying on Henry to look first (the dup rule then shrinks to a clause).
4. Write through `write_agent()` (HARNESS.md: schema check + .versions
   archive), never a raw file copy.
5. Judge on real turns, not on reading: replay "Was läuft gerade?", a QUICK
   fix ask, a BIG fuzzy ask, a permission-file ask, a "Danke". Tone must not
   move; first-word latency must not move.

Risk: the incident stories may be what makes some rules stick. If a rule
regresses in step 5, restore ITS one story, not the whole block.
