"use client";
// The git audit trail, drawn: main line on top, every card branch as a lane
// forking below it, commits as dots on a shared time axis. Click a branch ->
// its card; hover a dot -> the commit. What happened, who did it, when -
// straight from the repository, unfakeable.
import { Fragment, useEffect, useState } from "react";
import { get, post, Track } from "@/lib/api";
import { laneColor, useBoard } from "@/lib/store";

interface Commit { h: string; msg: string; author: string; date: string }
interface Branch { name: string; commits: Commit[]; track: string | null; task: string; lane: string | null; client: string }
interface Hist { head: string; main: Commit[]; branches: Branch[] }
interface Checkpoint { id: string; actor: string; reason: string; ts: string }
interface CpField { key: string; before: unknown; after: unknown }
interface CpDiff { id: string; settings: CpField[]; connectors: { added: string[]; removed: string[] } }
interface Debt { id: string; title: string; status: string; what: string; why_it_bites: string; trigger: string; fix: string }

// render a settings value for the diff, compactly and readably
function val(v: unknown): string {
  if (v === null || v === undefined) return "(unset)";
  if (typeof v === "string") return v === "" ? '""' : v;
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const DAY = 86400e3;

export default function HistoryView({ onOpen }: { onOpen: (t: Track) => void }) {
  const { tracks, me, toast, refresh } = useBoard();  // fork uses toast/refresh
  const [h, setH] = useState<Hist | null>(null);
  const [cps, setCps] = useState<Checkpoint[]>([]);
  const [debt, setDebt] = useState<Debt[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [diffs, setDiffs] = useState<Record<string, CpDiff>>({});
  const loadCps = () => get<Checkpoint[]>("/checkpoints").then(setCps).catch(() => {});
  function toggleDiff(id: string) {
    if (open === id) { setOpen(null); return; }
    setOpen(id);
    if (!diffs[id]) get<CpDiff>(`/checkpoints/${id}/diff`).then((d) => setDiffs((m) => ({ ...m, [id]: d }))).catch(() => {});
  }
  useEffect(() => {
    get<Hist>("/history").then(setH).catch(() => {});
    loadCps();
    get<Debt[]>("/debt").then(setDebt).catch(() => {});
  }, []);
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

  const Row = ({ label, sub, color, commits, onClick, onFork }: {
    label: string; sub?: string; color: string; commits: Commit[]; onClick?: () => void; onFork?: () => void;
  }) => (
    <div className="g-row" style={{ cursor: onClick ? "pointer" : "default" }} onClick={onClick}>
      <div className="g-side" title={sub ?? label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span className="ldot" style={{ background: color }} />
        <div style={{ flex: 1, minWidth: 0, overflow: "hidden" }}>
          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</div>
          {sub && <div style={{ fontSize: 10.5, color: "var(--txt-tertiary)", fontWeight: 400, overflow: "hidden", textOverflow: "ellipsis" }}>{sub}</div>}
        </div>
        {onFork && (
          <button className="btn ghost" style={{ fontSize: 10, padding: "1px 6px", flexShrink: 0 }}
            title="start a new card from this branch's state (append-only, source untouched)"
            onClick={(ev) => { ev.stopPropagation(); onFork(); }}>⑂ fork</button>
        )}
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
      <div className="panel" style={{ marginBottom: 12, maxWidth: 900, fontSize: 12.5, lineHeight: 1.7 }}>
        <h3>How work is stored</h3>
        <div style={{ color: "var(--txt-secondary)" }}>
          <b>Board copilot</b> = talk <i>about</i> work (the manager). ·{" "}
          <b>Card chat</b> = talk <i>to</i> a worker (does the work). ·{" "}
          <b>Branch</b> = that worker&apos;s memory. · <b>Commits</b> = its saved states (the dots below). ·{" "}
          <b>Fork</b> = start a new card from any state — nothing is ever overwritten.
        </div>
      </div>
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
              onClick={t ? () => onOpen(t) : undefined}
              onFork={b.track ? async () => {
                const r = await post<{ id?: string; error?: string }>(`/tracks/${b.track}/fork`, {});
                toast(r.error ?? "Forked - new card from this branch (source untouched)", 4500);
                refresh();
              } : undefined} />
          );
        })}
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--txt-tertiary)" }}>
        every dot = a commit (hover it) · every row = a card&apos;s branch (click → the card) ·{" "}
        row color = the card&apos;s lane · this comes straight from git — the audit trail nobody can redraw
      </div>
      <div className="panel" style={{ marginTop: 16, maxWidth: 860 }}>
        <h3>Config checkpoints — every change to the software&apos;s settings &amp; connectors</h3>
        <div style={{ fontSize: 11.5, color: "var(--txt-tertiary)", margin: "-4px 0 10px" }}>
          policy/settings and connector edits (not code — that&apos;s the git graph above).
          Click a row to see exactly what changed.
        </div>
        {!cps.length && <div style={{ fontSize: 12.5, color: "var(--txt-tertiary)" }}>
          none yet — the next settings change, connector install or template addition creates one</div>}
        <table>
          <tbody>
            {cps.slice(0, 20).map((c) => {
              const d = diffs[c.id];
              const isOpen = open === c.id;
              return (
              <Fragment key={c.id}>
              <tr style={{ cursor: "pointer" }} onClick={() => toggleDiff(c.id)}>
                <td style={{ width: 150, fontSize: 12, color: "var(--txt-tertiary)" }}>{c.ts}</td>
                <td style={{ width: 90 }}><b style={{ fontWeight: 600 }}>{c.actor}</b></td>
                <td style={{ fontSize: 12.5 }}>
                  <span style={{ color: "var(--txt-tertiary)", marginRight: 6 }}>{isOpen ? "▾" : "▸"}</span>
                  {c.reason}
                </td>
                <td style={{ textAlign: "right", width: 100 }}>
                  {me?.role === "owner" && (
                    <button className="btn ghost" style={{ fontSize: 11 }} onClick={async (ev) => {
                      ev.stopPropagation();
                      if (!confirm(`Restore the workspace config to before "${c.reason}"?
(Reversible — the current state is checkpointed first. Work data is untouched.)`)) return;
                      const r = await post<{ error?: string }>(`/checkpoints/${c.id}/restore`, {});
                      toast(r.error ?? "Restored — current state was checkpointed first", 5000);
                      loadCps(); refresh();
                    }}>↩ restore</button>
                  )}
                </td>
              </tr>
              {isOpen && (
                <tr>
                  <td colSpan={4} style={{ padding: "2px 0 12px 20px" }}>
                    {!d ? <span style={{ fontSize: 12, color: "var(--txt-tertiary)" }}>reading diff…</span>
                     : (d.settings.length === 0 && !d.connectors.added.length && !d.connectors.removed.length)
                       ? <span style={{ fontSize: 12, color: "var(--txt-tertiary)" }}>no field-level change recorded (or it was the very first snapshot)</span>
                       : (
                      <div style={{ fontSize: 12, fontFamily: "var(--mono, ui-monospace, monospace)", lineHeight: 1.7 }}>
                        {d.settings.map((f) => (
                          <div key={f.key}>
                            <span style={{ color: "var(--txt-secondary)" }}>{f.key}</span>{": "}
                            <span style={{ color: "var(--danger)" }}>{val(f.before)}</span>
                            <span style={{ color: "var(--txt-tertiary)" }}>{" → "}</span>
                            <span style={{ color: "var(--ok)" }}>{val(f.after)}</span>
                          </div>
                        ))}
                        {d.connectors.added.map((n) => <div key={"a" + n}><span style={{ color: "var(--ok)" }}>+ connector {n}</span></div>)}
                        {d.connectors.removed.map((n) => <div key={"r" + n}><span style={{ color: "var(--danger)" }}>− connector {n}</span></div>)}
                      </div>
                    )}
                  </td>
                </tr>
              )}
              </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="panel" style={{ marginTop: 16, maxWidth: 860 }}>
        <h3>Structural debt — load-bearing shortcuts the program knows about</h3>
        {debt.map((d) => (
          <div key={d.id} style={{ padding: "9px 0", borderBottom: "1px solid var(--glass-border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="chip" style={{
                color: d.status === "paid" ? "var(--ok)" : d.status === "in_progress" ? "var(--ai)" : "var(--warn)" }}>
                {d.status}
              </span>
              <b style={{ fontSize: 13 }}>{d.title}</b>
              <span style={{ fontSize: 11.5, color: "var(--txt-tertiary)" }}>bites when: {d.trigger}</span>
              {me?.role !== "client" && d.status === "open" && (
                <button className="btn ghost" style={{ fontSize: 11, marginLeft: "auto" }} onClick={async () => {
                  const r = await post<{ error?: string; id?: string }>(`/debt/${d.id}/fix`, {});
                  toast(r.error ?? "Fix card filed to Backlog (high priority)", 4500);
                  refresh();
                }}>file fix card</button>
              )}
            </div>
            <div style={{ fontSize: 12, color: "var(--txt-secondary)", marginTop: 3 }}>{d.why_it_bites}</div>
            <div style={{ fontSize: 11.5, color: "var(--txt-tertiary)", marginTop: 2 }}>fix: {d.fix}</div>
          </div>
        ))}
      </div>
    </>
  );
}
