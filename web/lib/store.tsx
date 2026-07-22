"use client";
// One store for the whole app: polls the daemon, React's diffing does the
// rest (no blink, no wiped inputs - the reason this port exists).
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AuthRequired, get, Me, Metrics, Track } from "./api";
import type { ConnectorInfo } from "@/components/connector";

export interface Spot { type: "client" | "process"; value: string }
interface BoardState {
  tracks: Track[];
  met: Metrics | null;
  me: Me | null;
  authNeeded: boolean;
  setAuthed: (me: Me | null) => void;
  refresh: () => void;
  toast: (msg: string, ms?: number) => void;
  toastMsg: string | null;
  spot: Spot | null;
  setSpot: (s: Spot | null) => void;
  conns: ConnectorInfo[];
}

const Ctx = createContext<BoardState>(null as unknown as BoardState);
export const useBoard = () => useContext(Ctx);

export function BoardProvider({ children }: { children: React.ReactNode }) {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [met, setMet] = useState<Metrics | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [authNeeded, setAuthNeeded] = useState(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [spot, setSpot] = useState<Spot | null>(null);
  const [conns, setConns] = useState<ConnectorInfo[]>([]);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const ts = await get<Track[]>("/tracks");
      setTracks(ts);
      setAuthNeeded(false);
      try { setMet(await get<Metrics>("/dashboard/data")); } catch { setMet(null); }
      try { setConns(await get<ConnectorInfo[]>("/connectors")); } catch { /* client role */ }
      if (!me) { try { setMe(await get<Me>("/me")); } catch { /* client-only */ } }
    } catch (e) {
      if (e instanceof AuthRequired) setAuthNeeded(true);
    }
  }, [me]);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 5000);
    return () => clearInterval(iv);
  }, [refresh]);

  const toast = useCallback((msg: string, ms = 2600) => {
    setToastMsg(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastMsg(null), ms);
  }, []);

  const setAuthed = useCallback((m: Me | null) => {
    setMe(m);
    setAuthNeeded(false);
    refresh();
  }, [refresh]);

  return (
    <Ctx.Provider value={{ tracks, met, me, authNeeded, setAuthed, refresh, toast, toastMsg, spot, setSpot, conns }}>
      {children}
    </Ctx.Provider>
  );
}

/* shared UI constants */
export const LANES: [string, string, string][] = [
  ["backlog", "Backlog", "var(--txt-tertiary)"],
  ["working", "Working", "var(--ai)"],
  ["review", "Review", "var(--human)"],
  ["done", "Done", "var(--ok)"],
];
export const STATUS: Record<string, [string, string]> = {
  queued: ["Queued", "var(--txt-tertiary)"], running: ["Running", "var(--ai)"],
  needs_you: ["Needs you", "var(--warn)"], submitted: ["Submitted", "var(--human)"],
  accepted: ["Accepted", "var(--ok)"], bounced: ["Bounced", "var(--danger)"],
};
export const PRIO_ORD: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 };
export const MODE_ICON: Record<string, string> = {
  do: "🤖 do", prepare: "✍ prepare", cowork: "🤝 cowork", teach: "🎓 teach", human: "👤 human",
};
export const MODE_EMOJI: Record<string, string> = {
  do: "🤖", prepare: "✍", cowork: "🤝", teach: "🎓", human: "👤",
};
export function laneColor(l?: string) {
  return { backlog: "var(--txt-tertiary)", working: "var(--ai)", review: "var(--human)", done: "var(--ok)" }[l ?? ""] ?? "var(--txt-tertiary)";
}
