"use client";
// Your existing Claude Code sessions (from ~/.claude) - the Paseo "session
// import". Continue one in place (--resume), or branch a fresh session from its
// repo with the original request as context. No git commit is made to adopt a
// session; a card's audit trail is the tracking, a branch is just a pointer.
import { useEffect, useState } from "react";
import { get, post, Track } from "@/lib/api";
import { useBoard } from "@/lib/store";
import { IconChevron, IconFork, IconPlay } from "./icons";

interface ClaudeSession {
  id: string; cwd: string; project: string; first: string; last_active: string;
}

export default function SessionsView({ onOpen }: { onOpen: (t: Track) => void }) {
  const { toast, refresh } = useBoard();
  const [sessions, setSessions] = useState<ClaudeSession[] | null>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => { get<ClaudeSession[]>("/sessions/claude").then(setSessions).catch(() => setSessions([])); }, []);

  async function adopt(s: ClaudeSession, mode: "continue" | "fork") {
    setBusy(s.id + mode);
    const r = await post<Track & { error?: string }>("/sessions/claude/adopt",
      { session_id: s.id, cwd: s.cwd, first: s.first, mode });
    setBusy("");
    if (r.error) { toast(r.error, 4000); return; }
    toast(mode === "continue" ? "Session as a card - open it to continue" : "Forked - a new card branches from it", 4500);
    refresh();
    if (mode === "continue") onOpen(r);
  }

  return (
    <div className="panel" style={{ maxWidth: 900 }}>
      <h3>Continue a Claude Code session</h3>
      <div style={{ fontSize: 12, color: "var(--txt-secondary)", margin: "-4px 0 12px", lineHeight: 1.6 }}>
        Your existing sessions from <code>~/.claude</code>. <b>Continue</b> resumes one exactly where it
        left off (in its own folder). <b>Branch</b> opens a fresh session in a new git branch/worktree,
        seeded with the original request - the source is untouched. Adopting makes no commit; the card&apos;s
        audit trail tracks it.
      </div>
      {sessions === null && <div style={{ fontSize: 12.5, color: "var(--txt-tertiary)" }}>reading ~/.claude…</div>}
      {sessions?.length === 0 && <div style={{ fontSize: 12.5, color: "var(--txt-tertiary)" }}>no Claude Code sessions found.</div>}
      {sessions?.map((s) => (
        <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 0", borderBottom: "1px solid var(--glass-border)" }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <b style={{ fontSize: 13 }}>{s.project || "session"}</b>
              <span style={{ fontSize: 11, color: "var(--txt-tertiary)" }}>{s.last_active}</span>
              <span style={{ fontSize: 11, color: "var(--txt-tertiary)", fontFamily: "var(--mono, monospace)" }}>{s.id.slice(0, 8)}</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--txt-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.first}>{s.first || "(no text)"}</div>
            <div style={{ fontSize: 10.5, color: "var(--txt-tertiary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={s.cwd}>{s.cwd}</div>
          </div>
          <button className="btn primary" style={{ fontSize: 11.5, flexShrink: 0 }} disabled={!!busy}
            onClick={() => adopt(s, "continue")}>
            <IconPlay size={12} /> {busy === s.id + "continue" ? "…" : "Continue"}
          </button>
          <button className="btn ghost" style={{ fontSize: 11.5, flexShrink: 0 }} disabled={!!busy}
            onClick={() => adopt(s, "fork")} title="new branch + worktree, fresh session seeded with this one's request">
            <IconFork size={11} /> {busy === s.id + "fork" ? "…" : "Branch"}
          </button>
        </div>
      ))}
      <div style={{ fontSize: 11, color: "var(--txt-tertiary)", marginTop: 12, display: "flex", alignItems: "center", gap: 4 }}>
        <IconChevron dir="right" size={11} /> want a clean start instead? Use <b style={{ margin: "0 3px" }}>+ New request</b> - that files a brand-new card &amp; session.
      </div>
    </div>
  );
}
