"use client";
// The safe form of "chat builds UI": a connector built via chat auto-appears
// as its own tab, rendered by THIS fixed template from the connector's data.
// Agents author data flows; the app authors pixels.
import { useState } from "react";
import { post, Track } from "@/lib/api";
import { IconPlay, IconUndo } from "./icons";
import { useBoard } from "@/lib/store";
import { Card } from "./board";

export interface ConnectorInfo { name: string; description: string; last_run: string | null; versions?: number }

export default function ConnectorView({ conn, onOpen }: { conn: ConnectorInfo; onOpen: (t: Track) => void }) {
  const { tracks, met, toast, refresh } = useBoard();
  const [busy, setBusy] = useState(false);
  const sched = (met?.settings as { connectors?: Record<string, { every_minutes?: number }> } | undefined)
    ?.connectors?.[conn.name]?.every_minutes ?? 0;
  const [mins, setMins] = useState(String(sched || ""));
  const produced = tracks.filter((t) => t.branch.startsWith("conn-" + conn.name.slice(0, 14)));

  async function runNow() {
    setBusy(true);
    const r = await post<{ cards?: number; error?: string }>(`/connectors/${conn.name}/run`, {});
    setBusy(false);
    toast(r.error ?? `Ran — ${r.cards} new backlog cards`, 4500);
    refresh();
  }
  async function saveSchedule() {
    const m = parseInt(mins) || 0;
    const cur = (met?.settings as { connectors?: Record<string, { every_minutes?: number }> } | undefined)?.connectors ?? {};
    const next = { ...cur } as Record<string, { every_minutes: number }>;
    if (m > 0) next[conn.name] = { every_minutes: m };
    else delete next[conn.name];
    await post("/settings", { connectors: next });
    toast(m > 0 ? `Scheduled every ${m} min` : "Schedule removed");
    refresh();
  }

  return (
    <>
      <div className="panel" style={{ maxWidth: 760 }}>
        <h3>Connector · {conn.name}</h3>
        <div style={{ fontSize: 13, color: "var(--txt-secondary)", marginBottom: 10 }}>{conn.description}</div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn primary" disabled={busy} onClick={runNow}>{busy ? "running…" : <><IconPlay size={12} /> Run now</>}</button>
          <span style={{ fontSize: 12, color: "var(--txt-tertiary)" }}>every</span>
          <input type="number" style={{ width: 70 }} placeholder="—" value={mins} onChange={(e) => setMins(e.target.value)} />
          <span style={{ fontSize: 12, color: "var(--txt-tertiary)" }}>minutes</span>
          <button className="btn ghost" onClick={saveSchedule}>Save schedule</button>
          {(conn.versions ?? 0) > 0 && (
            <button className="btn ghost" onClick={async () => {
              if (!confirm(`Roll ${conn.name} back to its previous version? (reversible - the current one gets archived too)`)) return;
              const r = await post<{ restored?: string; error?: string }>(`/connectors/${conn.name}/rollback`, {});
              toast(r.error ?? `Restored ${r.restored}`, 4500);
              refresh();
            }}><IconUndo size={12} /> rollback ({conn.versions})</button>
          )}
          <span style={{ fontSize: 11.5, color: "var(--txt-tertiary)", marginLeft: "auto" }}>
            last run: {conn.last_run ?? "never"}
          </span>
        </div>
        <div style={{ fontSize: 11.5, color: "var(--txt-tertiary)", marginTop: 10 }}>
          Built by an agent from a chat request, installed after gate + accept. Ask the copilot to change it:
          &quot;update the {conn.name} connector to …&quot; files a new build card.
        </div>
      </div>
      <div className="panel" style={{ maxWidth: 760 }}>
        <h3>Cards produced ({produced.length})</h3>
        {!produced.length && <div style={{ fontSize: 12.5, color: "var(--txt-tertiary)" }}>none yet — run it</div>}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: 10 }}>
          {produced.slice(0, 12).map((t) => <Card key={t.id} t={t} onOpen={onOpen} />)}
        </div>
      </div>
    </>
  );
}
