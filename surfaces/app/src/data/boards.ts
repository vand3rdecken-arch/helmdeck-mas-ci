import { useQuery } from "@tanstack/react-query";
import { create } from "zustand";

import { api } from "./client";
import type { Board, BoardColumn, Me, Track } from "./types";

/** BOARDS on the client (accounts-boards-prd phase 2).
 *
 *  The daemon serves the board LIST on /me; everything here is the derivation
 *  the renderer needs on top of it. Deliberately not a second store of board
 *  data: /me is the one source, the global version long-poll invalidates it,
 *  and a board write on another device therefore re-renders this one with no
 *  board-specific plumbing at all.
 *
 *  The one piece of state that IS local is WHICH board is open - see
 *  useActiveBoard. */

/** The stations a card can be in, in workflow order. Mirrors
 *  cells/engineer/sessions.py LANES, which is the law; the app only needs it
 *  to (a) fall back to the pre-boards layout and (b) order the overflow
 *  columns. It is NOT the list a column may name - the daemon decides that
 *  (spine/storage/boards.stations) and refuses anything else at the door. */
export const STATIONS = ["backlog", "working", "review", "done"] as const;

/** Where a card actually IS. The daemon has always defaulted a lane-less card
 *  to "working", and every consumer must agree on that or a card lands in one
 *  column and drags out of another. */
export const cardStation = (k: Track) => k.lane || "working";

/** The board to draw when /me carries none: a daemon older than this bundle,
 *  the demo fixture, or a store that would not open. It is EXACTLY the layout
 *  the app drew before boards existed - one column per station, every label
 *  empty so the app translates it - so degrading is invisible rather than
 *  broken. `owner: ""` because it stands in for the workspace's board; it has
 *  no id a write could ever address, which is what stops a client from trying
 *  to save edits to a board the daemon does not have. */
export function fallbackBoard(): Board {
  return {
    id: "", name: "", owner: "",
    columns: STATIONS.map((s) => ({ id: "c-" + s, label: "", station: s })),
  };
}

/** WHICH board is open, per device. Deliberately device-local in v1 and not a
 *  profile row: switching boards is a navigation gesture, and routing it
 *  through PUT /me/config would write an audit line every time somebody
 *  glanced at another board. The PRD's "last-open board" belongs with the rest
 *  of the profile work; until then a device simply opens the default board,
 *  which is where a fresh login lands anyway. */
type ActiveBoard = { boardId: string; setBoardId: (id: string) => void };
export const useActiveBoard = create<ActiveBoard>((set) => ({
  boardId: "",
  setBoardId: (boardId) => set({ boardId }),
}));

/** Every board this account may render, and the one that is open.
 *
 *  `active` resolves by id and falls back to the first board (the default one,
 *  which the daemon always lists first) rather than to nothing: a board that
 *  was deleted on another device must not leave this one on a blank screen. */
export function useBoards() {
  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const boardId = useActiveBoard((s) => s.boardId);
  const setBoardId = useActiveBoard((s) => s.setBoardId);
  const boards = me?.boards?.length ? me.boards : [];
  const active = boards.find((b) => b.id === boardId) ?? boards[0] ?? fallbackBoard();
  return { boards, active, boardId, setBoardId, role: me?.role ?? "" };
}

/** May this account edit that board? The daemon enforces it (boards.may_edit
 *  is the authority and refuses regardless of what the UI offers); this only
 *  decides whether to show the affordance, because a button that always errors
 *  is worse than no button. */
export const mayEditBoard = (b: Board | undefined, role: string) =>
  !!b?.id && (b.owner !== "" || role === "owner");

/** A column as actually drawn. `overflow` marks one the BOARD does not
 *  declare - see renderColumns. */
export type RenderColumn = BoardColumn & { overflow?: boolean };

/** THE OVERFLOW INVARIANT, derived (PRD section 3: "a card can never become
 *  invisible on a board that claims to show it").
 *
 *  A board is free to omit a station - that is the whole point of a personal
 *  view. But omitting a station that currently HOLDS cards would silently
 *  swallow them, and a card you cannot see is a card you cannot unblock. So
 *  the columns actually drawn are the board's, plus one appended column for
 *  every station that has cards and no column of its own.
 *
 *  Three properties this shape buys, all of which the alternatives lose:
 *   - it is DERIVED from the two live sets (the layout and the cards) at
 *     render time. Nothing is stored, no flag is kept, and the extra column
 *     disappears by itself when the last card leaves - the no-monkey-patches
 *     law applied to a view.
 *   - it never edits the user's layout. Auto-adding a real column to the saved
 *     board would mean a board silently growing behind its owner's back.
 *   - it is ONE COLUMN PER HIDDEN STATION, not one merged "everything else"
 *     bucket. A merged column has no single station, so a card dropped into it
 *     would have no defined destination; per-station columns keep every drag
 *     target meaningful and let a card be dragged straight back out.
 *
 *  Stations the app does not know (a lane added daemon-side before the bundle
 *  catches up) are folded in from the cards themselves, so the invariant holds
 *  even against a station this file has never heard of. */
export function renderColumns(board: Board, cards: Track[]): RenderColumn[] {
  const columns: RenderColumn[] = board.columns ?? [];
  const covered = new Set(columns.map((c) => c.station));
  const withCards = new Set(cards.map(cardStation));
  const order = [...STATIONS.filter((s) => withCards.has(s)),
    ...[...withCards].filter((s) => !(STATIONS as readonly string[]).includes(s))];
  return [
    ...columns,
    ...order.filter((s) => !covered.has(s))
      .map((s) => ({ id: "overflow:" + s, label: "", station: s, overflow: true })),
  ];
}

/** Cards per column, by column id. A card goes to the FIRST column showing its
 *  station - two columns may share a station (the PRD allows it; a drag
 *  between them is a re-sort, not a move), and duplicating the card into both
 *  would let one board show the same work twice.
 *
 *  Total by construction: renderColumns guarantees a column for every station
 *  that has cards, so no card can fall out of this grouping. Feed it those
 *  columns, never `board.columns` raw. */
export function groupByColumn(columns: RenderColumn[], cards: Track[]) {
  const out: Record<string, Track[]> = {};
  for (const c of columns) out[c.id] = [];
  for (const k of cards) {
    const col = columns.find((c) => c.station === cardStation(k));
    if (col) out[col.id].push(k);
  }
  return out;
}

/** A column's visible name. Empty `label` means "this station's own name" -
 *  which is what keeps a board translatable and what makes the seeded default
 *  board render in the reader's language rather than its creator's. An
 *  overflow column always shows the station name; it has no label to carry. */
export const columnLabel = (c: RenderColumn, stationLabel: (s: string) => string) =>
  (c.overflow ? "" : c.label) || stationLabel(c.station);
