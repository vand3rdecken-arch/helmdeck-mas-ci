"use client";
import { useCallback, useEffect, useState } from "react";
import { post, Track } from "@/lib/api";
import { BoardProvider, useBoard } from "@/lib/store";
import AuthGate from "@/components/auth";
import BoardView from "@/components/board";
import Peek from "@/components/peek";
import NewRequestModal from "@/components/modal";
import Chat from "@/components/chat";
import DashView from "@/components/dash";
import { ListView, TimelineView } from "@/components/views";
import ProcsView from "@/components/procs";
import RecsView from "@/components/recs";
import SettingsView from "@/components/settings";

type View = "board" | "list" | "timeline" | "procs" | "dash" | "recs" | "settings";
const VIEWS: View[] = ["board", "list", "timeline", "procs", "dash", "recs", "settings"];

const ICONS: Record<string, React.ReactNode> = {
  board: <svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="18" rx="1.5" /><rect x="14" y="3" width="7" height="11" rx="1.5" /></svg>,
  procs: <svg viewBox="0 0 24 24"><circle cx="5" cy="6" r="2.2" /><circle cx="12" cy="12" r="2.2" /><circle cx="19" cy="18" r="2.2" /><path d="M7 7l3 3M14 13l3 3" /></svg>,
  dash: <svg viewBox="0 0 24 24"><path d="M3 12h5l2-7 4 14 2-7h5" /></svg>,
  recs: <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="3" /></svg>,
  settings: <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z" /></svg>,
};

function App() {
  const { met, me, tracks, authNeeded, toastMsg } = useBoard();
  const [view, setView] = useState<View>("board");
  const [filter, setFilter] = useState<string>("all");
  const [peek, setPeek] = useState<Track | null>(null);
  const [modal, setModal] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  // hash routing (linkable views, glasses-friendly)
  useEffect(() => {
    const apply = () => {
      const h = location.hash.slice(1) as View;
      if (VIEWS.includes(h)) setView(h);
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);
  const nav = useCallback((v: View) => { setView(v); location.hash = v; }, []);

  // keep the peeked track fresh as polls come in
  useEffect(() => {
    if (peek) {
      const fresh = tracks.find((t) => t.id === peek.id);
      if (fresh && fresh.updated !== peek.updated) setPeek(fresh);
    }
  }, [tracks, peek]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement)?.tagName;
      if (/INPUT|TEXTAREA|SELECT/.test(tag ?? "")) {
        if (e.key === "Escape") { setPeek(null); setModal(false); }
        return;
      }
      if (e.key === "c" && view === "board") setModal(true);
      if (e.key === "k") setChatOpen((o) => !o);
      if (e.key === "Escape") { setPeek(null); setModal(false); setChatOpen(false); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [view]);

  const isClient = me?.role === "client";
  const isWork = view === "board" || view === "list" || view === "timeline";
  const clients = Object.entries(tracks.reduce<Record<string, number>>((acc, t) => {
    if (t.client) acc[t.client] = (acc[t.client] ?? 0) + 1;
    return acc;
  }, {})).sort((a, b) => b[1] - a[1]);
  useEffect(() => {
    if (isClient && (view === "dash" || view === "settings")) nav("board");
  }, [isClient, view, nav]);

  async function signOut() {
    await post("/auth/logout");
    location.reload();
  }

  if (authNeeded) return <AuthGate />;

  const c = met?.capacity;
  return (
    <div id="app">
      <nav id="side">
        <div id="logo"><span className="dot">S</span> SwarmDeck</div>
        <div className={`navitem${isWork ? " active" : ""}`} onClick={() => nav("board")}>{ICONS.board}Board</div>
        <div className={`navitem${view === "procs" ? " active" : ""}`} onClick={() => nav("procs")}>{ICONS.procs}Processes</div>
        {!isClient && <div className={`navitem${view === "dash" ? " active" : ""}`} onClick={() => nav("dash")}>{ICONS.dash}Dashboard</div>}
        <div className={`navitem${view === "recs" ? " active" : ""}`} onClick={() => nav("recs")}>{ICONS.recs}Recordings</div>
        {!isClient && <div className={`navitem${view === "settings" ? " active" : ""}`} onClick={() => nav("settings")}>{ICONS.settings}Settings</div>}
        <div className="sect">Views</div>
        {clients.length > 0 && <>
          {clients.map(([name, count]) => (
            <div key={name} className={`navitem${isWork && filter === "client:" + name ? " active" : ""}`}
              onClick={() => { nav("board"); setFilter(filter === "client:" + name ? "all" : "client:" + name); }}>
              <svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" /><path d="M3 13h18" /></svg>
              {name}<span className="lcount" style={{ marginLeft: "auto" }}>{count}</span>
            </div>
          ))}
        </>}
        <div className={`navitem${isWork && filter === "all" ? " active" : ""}`} onClick={() => { nav("board"); setFilter("all"); }}>All work</div>
        <div className={`navitem${isWork && filter === "needs_you" ? " active" : ""}`} onClick={() => { nav("board"); setFilter("needs_you"); }}>Needs you</div>
        <div className="foot">
          {me && <div style={{ marginBottom: 6 }}><b style={{ color: "var(--txt-secondary)" }}>{me.name}</b> · {me.role}</div>}
          <span style={{ cursor: "pointer" }} onClick={() => {
            const r = document.documentElement;
            r.dataset.theme = r.dataset.theme === "dark" ? "light" : "dark";
            try { localStorage.sdTheme = r.dataset.theme ?? "dark"; } catch { }
          }}>◐ theme</span>{" · "}
          <span style={{ cursor: "pointer" }} onClick={signOut}>sign out</span>
        </div>
      </nav>
      <div id="main">
        <div id="hdr">
          <span className="crumb">
            {isWork && filter.startsWith("client:") ? "Board · " + filter.slice(7) : isWork ? "Board" : view === "dash" ? "Dashboard" : view === "recs" ? "Recordings" : view === "procs" ? "Processes" : "Settings"}
          </span>
          {isWork && (
            <span id="layouts">
              {(["board", "list", "timeline"] as View[]).map((l, i) => (
                <button key={l} className={`lay${view === l ? " active" : ""}`} title={l}
                  onClick={() => nav(l)}>{["▦", "☰", "⧖"][i]}</button>
              ))}
            </span>
          )}
          {c && (
            <span id="capline">· <b>{c.wip}/{c.wip_limit}</b> WIP · {c.touches_today}/{c.touch_budget_day} touches · headroom <b>{c.headroom}</b></span>
          )}
          {!c && me && <span id="capline">{me.name} · client view</span>}
          <span className="spacer" />
          {isWork && <button className="btn primary" onClick={() => setModal(true)}>+ New request</button>}
        </div>
        <div id="content">
          {view === "board" && <BoardView filter={filter} onOpen={setPeek} />}
          {view === "list" && <ListView filter={filter} onOpen={setPeek} />}
          {view === "timeline" && <TimelineView filter={filter} onOpen={setPeek} />}
          {view === "procs" && <ProcsView onOpen={setPeek} />}
          {view === "dash" && <DashView />}
          {view === "recs" && <RecsView />}
          {view === "settings" && <SettingsView />}
        </div>
      </div>
      {peek && <Peek t={peek} onClose={() => setPeek(null)} />}
      {modal && <NewRequestModal onClose={() => setModal(false)} />}
      {!isClient && me && <Chat open={chatOpen} setOpen={setChatOpen} />}
      {toastMsg && <div id="toast">{toastMsg}</div>}
    </div>
  );
}

export default function Page() {
  useEffect(() => {
    try {
      document.documentElement.dataset.theme = localStorage.sdTheme || "dark";
    } catch { document.documentElement.dataset.theme = "dark"; }
  }, []);
  return (
    <BoardProvider>
      <App />
    </BoardProvider>
  );
}
