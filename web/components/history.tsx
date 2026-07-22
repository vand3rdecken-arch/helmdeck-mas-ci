"use client";
// The git audit trail, drawn: main line on top, every card branch as a lane
// forking below it, commits as dots on a shared time axis. Click a branch ->
// its card; hover a dot -> the commit. What happened, who did it, when -
// straight from the repository, unfakeable.
import { useEffect, useState } from "react";
import { get, post, Track } from "@/lib/api";
import { laneColor, useBoard } from "@/lib/store";

interface Commit { h: string; msg: string; author: string; date: string }
interface Branch { name: string; commits: Commit[]; track: string | null; task: string; lane: string | null; client: string }
interface Hist { head: string; main: Commit[]; branches: Branch[] }
interface Checkpoint { id: string; actor: string; reason: string; ts: string }

const DAY = 86400e3;

export default function HistoryView({ onOpen }: { onOpen: (t: Track) => void }) {
  const { tracks, me, toast, refresh } = useBoard();
  const [h, setH] = useState<Hist | null>(null);
  const [cps, setCps] = useState<Checkpoint[]>([]);
  const loadCps = () => get<Checkpoint[]>("/checkpoints").then(setCps).catch(() => {});
  useEffect(() => { get<Hist>("/history").then(setH).catch(() => {}); loadCps(); }, []);
  if (!h) return <div style={{ color: "var(--txt-tertiary)", fontSize: 12.5 }}>reading the repository…</div>;

  const all = [...h.main, ...h.branches.flatMap((b) => b.commits)];
  if (!all.length) return <div className="panel">no commits yet</div>;
  const ts = (c: Commit) => new Date(c.date).getTime();
  let min = Math.min(...all.map(ts));
  const max = Math.max(...all.map(ts)) + DAY;
  min -= DAY / 2;
  const days = Math.max(1, Math.ceil((max - min) / DAY));
  const pxday = Math.max(56, Math.floor(950 / days));
  const W = days * pxday;
  const x = (t: number) => Math.round((t - min) / DAY * pxday + pxday / 2);

  const Row = ({ label, sub, color, commits, onClick }: {
    label: string; sub?: string; color: string; commits: Commit[]; onClick?: () => void;
  }) => (
    <div className="g-row" style={{ cursor: onClick ? "pointer" : "default" }} onClick={onClick}>
      <div className="g-side" title={sub ?? label}>
        <span className="ldot" style={{ background: color, marginRight: 7 }} />
        {label}
        {sub && <div style={{ fontSize: 10.5, color: "var(--txt-tertiary)", fontWeight: 400, overflow: "hidden", textOverflow: "ellipsis" }}>{sub}</div>}
      </div>
      <div className="g-track" style={{ width: W, height: 40 }}>
        {commits.length > 1 && (
          <div style={{
            position: "absolute", top: 19, height: 2, background: `color-mix(in oklch, ${color} 45%, transparent)`,
            left: x(Math.min(...commits.map(ts))), width: Math.max(2, x(Math.max(...commits.map(ts))) - x(Math.min(...commits.map(ts)))),
          }} />
        )}
        {commits.map((c, i) => (
          <div key={c.h + i} title={`${c.h} · ${c.msg}\n${c.author} · ${c.date}`} style={{
            position: "absolute", left: x(ts(c)) - 5, top: 15, width: 10, height: 10,
            borderRadius: "50%", background: color, border: "2px solid var(--bg-surface-1)",
          }} />
        ))}
      </div>
    </div>
  );

  return (
    <>
      <div id="gantt">
        <div className="g-head">
          <div className="g-side">branch</div>
          <div className="g-days" style={{ width: W }}>
            {Array.from({ length: days }, (_, i) => {
              const d = new Date(min + i * DAY + DAY / 2);
              return <div key={i} className="g-day" style={{ width: pxday }}>{d.getMonth() + 1}/{d.getDate()}</div>;
            })}
          </div>
        </div>
        <Row label={h.head} sub="the accepted truth" color="var(--accent)" commits={h.main} />
        {h.branches.filter((b) => b.commits.length).map((b) => {
          const t = b.track ? tracks.find((x) => x.id === b.track) : undefined;
          return (
            <Row key={b.name} label={b.name} color={laneColor(b.lane ?? undefined)}
              sub={b.task || undefined}
              commits={b.commits}
              onClick={t ? () => onOpen(t) : undefined} />
          );
        })}
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--txt-tertiary)" }}>
        every dot = a commit (hover it) · every row = a card&apos;s branch (click → the card) ·{" "}
        row color = the card&apos;s lane · this comes straight from git — the audit trail nobody can redraw
      </div>
      <div className="panel" style={{ marginTop: 16, maxWidth: 860 }}>
        <h3>System checkpoints — every change to the software itself</h3>
        {!cps.length && <div style={{ fontSize: 12.5, color: "var(--txt-tertiary)" }}>
          none yet — the next settings change, connector install or template addition creates one</div>}
        <table>
          <tbody>
            {cps.slice(0, 20).map((c) => (
              <tr key={c.id}>
                <td style={{ width: 150, fontSize: 12, color: "var(--txt-tertiary)" }}>{c.ts}</td>
                <td style={{ width: 90 }}><b style={{ fontWeight: 600 }}>{c.actor}</b></td>
                <td style={{ fontSize: 12.5 }}>{c.reason}</td>
                <td style={{ textAlign: "right", width: 100 }}>
                  {me?.role === "owner" && (
                    <button className="btn ghost" style={{ fontSize: 11 }} onClick={async () => {
                      if (!confirm(`Restore the workspace config to before "${c.reason}"?
(Reversible — the current state is checkpointed first. Work data is untouched.)`)) return;
                      const r = await post<{ error?: string }>(`/checkpoints/${c.id}/restore`, {});
                      toast(r.error ?? "Restored — current state was checkpointed first", 5000);
                      loadCps(); refresh();
                    }}>↩ restore</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
