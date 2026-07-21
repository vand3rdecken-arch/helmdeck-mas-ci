"use client";
// Processes: propose -> adjust -> accept -> the chain runs. Pipeline nodes on
// top are the n8n-style read: green done, blue working, pulsing amber = the
// chain is here waiting for a human, gray waiting, dashed proposed.
import { useCallback, useEffect, useRef, useState } from "react";
import { get, post, Process, Track } from "@/lib/api";
import { useBoard } from "@/lib/store";
import { IconCheck, ModeIcon, MODE_LABEL, MODE_ICONS } from "./icons";

const STATE_STYLE: Record<string, [string, string, string]> = {
  done: ["var(--ok)", "color-mix(in oklch,var(--ok) 18%,transparent)", "done"],
  working: ["var(--ai)", "color-mix(in oklch,var(--ai) 18%,transparent)", "agent working"],
  ready: ["var(--warn)", "color-mix(in oklch,var(--warn) 20%,transparent)", "▶ up next"],
  waiting: ["var(--border-strong)", "transparent", "waiting"],
  proposed: ["var(--border-subtle)", "transparent", "proposed"],
};

function Pipeline({ p, onOpen }: { p: Process; onOpen: (t: Track) => void }) {
  const { tracks, toast } = useBoard();
  if (!p.steps?.length) return null;
  return (
    <div style={{ display: "flex", alignItems: "flex-start", overflowX: "auto", padding: "10px 2px 6px" }}>
      {p.steps.map((s, i) => {
        const st = STATE_STYLE[s.state ?? "proposed"] ?? STATE_STYLE.proposed;
        const review = s.lane === "review";
        return (
          <span key={i} style={{ display: "contents" }}>
            <div style={{ width: 96, flexShrink: 0, textAlign: "center", cursor: "pointer" }}
              onClick={() => {
                const t = s.track ? tracks.find((x) => x.id === s.track) : null;
                if (t) onOpen(t); else toast(s.desc || s.title);
              }}>
              <div style={{
                width: 42, height: 42, borderRadius: "50%", margin: "0 auto", display: "grid",
                placeItems: "center", fontSize: 17,
                border: `2.5px ${s.state === "proposed" ? "dashed" : "solid"} ${st[0]}`,
                background: st[1],
                animation: s.state === "ready" ? "pulse 1.6s infinite" : undefined,
              }}>
                {s.done ? <IconCheck size={17} /> : <ModeIcon mode={s.mode} size={17} />}
              </div>
              <div style={{
                fontSize: 10.5, lineHeight: 1.25, marginTop: 4, color: "var(--txt-secondary)",
                display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
              }}>{s.title}</div>
              <div style={{ fontSize: 9.5, fontWeight: 600, color: st[0] }}>{review ? "in review" : st[2]}</div>
            </div>
            {i < p.steps.length - 1 && (
              <div style={{
                flex: "0 0 22px", height: 42, display: "flex", alignItems: "center",
                justifyContent: "center", color: s.done ? "var(--ok)" : "var(--border-strong)", fontSize: 15,
              }}>→</div>
            )}
          </span>
        );
      })}
    </div>
  );
}

export default function ProcsView({ onOpen }: { onOpen: (t: Track) => void }) {
  const { toast } = useBoard();
  const [procs, setProcs] = useState<Process[] | null>(null);
  const [req, setReq] = useState("");
  const [client, setClient] = useState("");
  const [due, setDue] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const loadProcs = useCallback(() => {
    get<Process[]>("/processes").then(setProcs).catch(() => {});
  }, []);
  useEffect(() => {
    loadProcs();
    const iv = setInterval(loadProcs, 8000);
    return () => { clearInterval(iv); clearInterval(pollRef.current); };
  }, [loadProcs]);

  async function newProc() {
    const v = req.trim();
    if (!v) { toast("Describe the request"); return; }
    const r = await post<{ error?: string }>("/processes/new", { request: v, client: client.trim(), due });
    if (r.error) { toast(r.error, 3600); return; }
    setReq("");
    toast("Filed — agent is proposing steps");
    setTimeout(loadProcs, 1500);
  }

  async function stepAct(pid: string, idx: number, action: string, patch?: Record<string, unknown>, title?: string) {
    const r = await post<{ error?: string }>(`/processes/${pid}/step`, { action, idx, patch, title });
    if (r.error) { toast(r.error, 3600); return; }
    if (action === "accept" || action === "accept_all") toast(`Card${action === "accept_all" ? "s" : ""} created on the board`);
    loadProcs();
  }

  return (
    <>
      <div className="panel" style={{ maxWidth: 760 }}>
        <h3>New process</h3>
        <div style={{ fontSize: 12, color: "var(--txt-tertiary)", marginBottom: 8 }}>
          Describe the client request in plain words — an agent proposes the step sequence, you adjust,
          each accepted step becomes a card and the chain runs them in order.
        </div>
        <textarea style={{ width: "100%", height: 64 }} value={req} onChange={(e) => setReq(e.target.value)}
          placeholder="e.g. Client Meier needs the Q3 contract document approved: draft it from the template, get legal wording checked, send to the client for signature, archive the signed copy." />
        <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
          <input placeholder="client (optional)" style={{ width: 150 }} value={client} onChange={(e) => setClient(e.target.value)} />
          <input type="date" style={{ width: 150 }} title="process due date" value={due} onChange={(e) => setDue(e.target.value)} />
          <button className="btn primary" onClick={newProc}>Propose steps</button>
        </div>
      </div>
      {procs === null && <div style={{ color: "var(--txt-tertiary)", fontSize: 12.5 }}>loading…</div>}
      {procs?.length === 0 && <div className="panel" style={{ maxWidth: 760, color: "var(--txt-tertiary)" }}>No processes yet.</div>}
      {procs?.map((p) => (
        <div key={p.id} className="panel" style={{ maxWidth: 920 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <b style={{ fontSize: 13.5, color: "var(--txt-primary)" }}>{p.request.slice(0, 90)}</b>
            <span className="chip">{p.status}</span>
            {p.client && <span className="chip">client: {p.client}</span>}
            {p.due && <span className="chip">📅 {p.due}</span>}
            {p.cost > 0 && <span className="chip">proposal AI ${p.cost.toFixed(2)}</span>}
          </div>
          <Pipeline p={p} onOpen={onOpen} />
          {p.status === "proposing" && <div style={{ marginTop: 8, color: "var(--txt-tertiary)" }}>agent is proposing steps…</div>}
          {p.status === "failed" && <div style={{ marginTop: 8, color: "var(--danger)" }}>{p.error ?? "proposal failed"}</div>}
          {p.steps.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 7, flexWrap: "wrap" }}>
              <span style={{ color: "var(--txt-tertiary)", width: 18, textAlign: "right" }}>{i + 1}.</span>
              <input defaultValue={s.title} style={{ flex: 1, minWidth: 200, fontSize: 12.5 }}
                onBlur={(e) => e.target.value !== s.title && stepAct(p.id, i, "update", { title: e.target.value })} />
              <select style={{ width: 118 }} value={s.mode}
                onChange={(e) => stepAct(p.id, i, "update", { mode: e.target.value })}>
                {Object.keys(MODE_ICONS).map((m) => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}
              </select>
              <input type="date" value={s.due ?? ""} style={{ width: 135 }}
                onChange={(e) => stepAct(p.id, i, "update", { due: e.target.value })} />
              {s.track ? (
                <span className="chip" style={{ color: "var(--ok)" }}>✔ card</span>
              ) : (
                <>
                  <button className="btn ghost" style={{ fontSize: 11, padding: "2px 9px" }}
                    onClick={() => stepAct(p.id, i, "accept")}>Accept → card</button>
                  <button className="btn ghost" style={{ fontSize: 11, padding: "2px 7px" }}
                    onClick={() => stepAct(p.id, i, "remove")}>✕</button>
                </>
              )}
              {s.desc && (
                <div style={{ flexBasis: "100%", paddingLeft: 26, fontSize: 11.5, color: "var(--txt-tertiary)" }}>{s.desc}</div>
              )}
            </div>
          ))}
          {p.steps.length > 0 && (
            <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
              <button className="btn primary" style={{ fontSize: 12 }}
                onClick={() => stepAct(p.id, 0, "accept_all")}>Accept all → cards</button>
              <button className="btn ghost" style={{ fontSize: 12 }}
                onClick={() => { const t = prompt("Step title:"); if (t) stepAct(p.id, 0, "add", undefined, t); }}>+ add step</button>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
