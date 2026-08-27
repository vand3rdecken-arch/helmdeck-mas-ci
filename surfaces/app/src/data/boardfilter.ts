import { create } from "zustand";

// Shared board filter so the desktop sidebar (clients / archive) can drive what
// the Board shows. Values: "all" | "needs_you" | "archived" | "client:<name>".
type BoardFilter = { filter: string; setFilter: (f: string) => void };

export const useBoardFilter = create<BoardFilter>((set) => ({
  filter: "all",
  setFilter: (filter) => set({ filter }),
}));
