# Board-Move UX on device (archived card, not merged)

Original card: `pm-board-move-ux-on-device-` (filed 2026-08-03, went stale at
573 commits behind expo-migration by 2026-08-20 - predates the spine
+ cells reorg, never got merged, worktree never reclaimed).

Feature: on-device drag-and-drop for the phone board - long-press lifts a
card, a full-screen overlay shows four lane bands (from
settings.policy.lane_labels), a ghost chip follows the finger, dropping over
a band moves the card (with a WIP-guard + optimistic rollback), releasing
without dragging falls back to the existing move sheet. Plus haptics.

STILL NOT implemented on current `app/src/ui/board.tsx` as of 2026-08-20 -
`WideKanban` still calls `api.moveLane` directly with a plain toast, no
on-device drag overlay, no shared move-with-WIP-guard-and-rollback helper.
Not superseded, just went stale before landing.

Contents:
- `board.diff` - the uncommitted diff against board.tsx/mock_board.py at the
  time the worktree went stale. NOT directly mergeable (board.tsx has moved
  on: WideKanban's onInfo/onMove props differ from what this diff expects) -
  use as a spec/reference for a fresh implementation, not a patch to apply.
- `judge_board_move.py` - the verification harness used to test the feature
  against a mock board.
- `shots/` - screenshots from that verification run (drag overlay, WIP-full
  refusal toast, optimistic move + rollback, long-press sheet fallback).
