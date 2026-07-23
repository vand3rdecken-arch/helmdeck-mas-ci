"use client";
import { useEffect, useRef, useState } from "react";
import { get, post, HistoryRow, Track } from "@/lib/api";

interface Turn { ts: string; cost?: number; models?: string[]; usage?: { input_tokens?: number; output_tokens?: number; cache_read_input_tokens?: number; cache_creation_input_tokens?: number } }
import { STATUS, useBoard } from "@/lib/store";
import LiveThumb from "./live";
import { executor } from "./board";
import Composer, { SendOpts } from "./composer";
import { IconX, IconFork, IconChevron, IconExpand, IconShrink } from "./icons";
import Markdown from "./markdown";
import Transcript, { Step } from "./transcript";

export default function Peek({ t, onClose }: { t: Track; onClose: () => void }) {
  const { met, me, toast, refresh } = useBoard();
  const [hist, setHist] = useState<HistoryRow[]>([]);
  const [trans, setTrans] = useState<Step[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [details, setDetails] = useState(false);
  const [full, setFull] = useState(false);
  const [task, setTask] = useState(t.task);
  const [val, setVal] = useState(String(t.value ?? ""));
  const [clientV, setClientV] = useState(t.client ?? "");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const e = met?.cards.find((x) => x.id === t.id);
  const st = STATUS[t.status] ?? [t.status, "var(--txt-tertiary)"];
  const drivers = Object.keys(met?.settings?.drivers ?? { claude: {} });

  useEffect(() => { setTask(t.task); }, [t.id, t.task]);
  // keep value/client in sync when the card updates from polls, but only when the
  // real field changed - so live polling never wipes what you're typing.
  useEffect(() => { setVal(String(t.value ?? "")); }, [t.id, t.value]);
  useEffect(() => { setClientV(t.client ?? ""); }, [t.id, t.client]);
  // keep the feed pinned to the newest message (like a chat), as transcript/
  // history loads and grows.
  useEffect(() => {
    const f = feedRef.current;
    if (f) f.scrollTop = f.scrollHeight;
  }, [trans, hist]);
  function saveVal() { const n = parseFloat(val); if (!isNaN(n) && n !== t.value) edit({ value: n }); }
  function saveClient() { if (clientV.trim() !== (t.client ?? "")) edit({ client: clientV.trim() }); }
  useEffect(() => {   // grow the title box to fit the full task (no hidden scroll)
    const ta = taRef.current;
    if (ta) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 300) + "px"; }
  }, [task]);
  useEffect(() => {
    get<HistoryRow[]>(`/tracks/${t.id}/history`).then(setHist).catch(() => setHist([]));
    get<Turn[]>(`/tracks/${t.id}/turns`).then(setTurns).catch(() => setTurns([]));
    get<Step[]>(`/tracks/${t.id}/transcript`).then(setTrans).catch(() => setTrans([]));
  }, [t.id, t.updated]);
  // live: while a turn runs, poll the transcript so it grows in real time
  // (a streaming approximation - new tool calls / text appear as they land)
  useEffect(() => {
    if (t.status !== "running") return;
    const iv = setInterval(() => {
      get<Step[]>(`/tracks/${t.id}/transcript`).then(setTrans).catch(() => {});
    }, 1500);
    return () => clearInterval(iv);
  }, [t.id, t.status]);

  async function edit(patch: Record<string, unknown>) {
    const r = await post<{ error?: string }>(`/tracks/${t.id}/update`, patch);
    if (r.error) { toast(r.error, 3600); return; }
    toast("Saved");
    refresh();
  }

  async function sendSteer(v: string, opts: SendOpts) {
    if (!v && !opts.attachments.length) return;
    await post(`/tracks/${t.id}/steer`, {
      text: v || "(see attachment)", model: opts.model, thinking: opts.thinking,
      attachments: opts.attachments, mode: opts.mode,
    });
    toast("Steer sent - session resuming");
    setTimeout(refresh, 1500);
  }
  async function stopTurn() {
    await post(`/tracks/${t.id}/cancel`, {});
    toast("Stopping the turn…");
    setTimeout(refresh, 800);
  }

  // context-window meter: how full the session is, from the last turn's input tokens
  const lastIn = turns.length ? (() => {
    const u = turns[turns.length - 1].usage ?? {};
    return (u.input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0);
  })() : 0;
  // Full = bypassPermissions: the agent may run anything (Bash, windows-mcp,
  // Chrome, git) with no prompts - owner only; the worktree is the blast radius.
  const modeBase = [{ id: "acceptEdits", label: "Edit" }, { id: "plan", label: "Plan" },
    ...(me?.role === "owner" ? [{ id: "bypassPermissions", label: "Full" }] : [])];
  const modeOpts = [...modeBase.filter((m) => m.id === t.perm), ...modeBase.filter((m) => m.id !== t.perm)];

  const sel = { width: "auto", fontSize: 12 } as const;
  return (
    <>
      <div id="backdrop" onClick={onClose} />
      <div id="peek" className={full ? "full" : ""}>
        <div className="ph">
          <span className="pid">{t.branch}</span>
          {me?.role !== "client" && (
            <button className="btn ghost" style={{ fontSize: 11, marginLeft: "auto" }}
              onClick={async () => {
                await post(`/tracks/${t.id}/archive`, { on: !t.archived });
                toast(t.archived ? "Unarchived" : "Archived - find it under Views › Archive");
                refresh(); if (!t.archived) onClose();
              }}>{t.archived ? "unarchive" : "archive"}</button>
          )}
          {me?.role !== "client" && (
            <button className="btn ghost" style={{ fontSize: 11 }} title="start a new card from this card's current state - the source is never touched"
              onClick={async () => {
                const r = await post<{ id?: string; error?: string }>(`/tracks/${t.id}/fork`, {});
                toast(r.error ?? "Forked - a new card starts from this state (source untouched)", 4500);
                refresh();
              }}><IconFork size={11} /> fork</button>
          )}
          {me?.role === "owner" && (
            <button className="btn ghost" style={{ fontSize: 11, color: "var(--danger)", borderColor: "var(--danger)" }}
              onClick={async () => {
                if (!confirm("Delete this card, its worktree and branch? The audit trail (events, recording) stays. This cannot be undone.")) return;
                const r = await post<{ error?: string }>(`/tracks/${t.id}/delete`, {});
                toast(r.error ?? "Deleted - audit trail kept", 4500);
                refresh(); onClose();
              }}>delete</button>
          )}
          <button className="x" style={{ marginLeft: me?.role === "client" ? "auto" : 0 }}
            title={full ? "Exit fullscreen" : "Fullscreen"} onClick={() => setFull((v) => !v)}>
            {full ? <IconShrink size={14} /> : <IconExpand size={14} />}</button>
          <button className="x" onClick={onClose}><IconX size={14} /></button>
        </div>
        <textarea
          ref={taRef}
          value={task}
          onChange={(ev) => setTask(ev.target.value)}
          onBlur={() => task.trim() && task !== t.task && edit({ task: task.trim() })}
          style={{
            margin: "12px 16px 4px", fontSize: 15, fontWeight: 600, lineHeight: 1.45,
            minHeight: 52, maxHeight: 300, resize: "vertical", overflowY: "auto",
          }}
          title="the request - editable, saves on blur"
        />
        {/* primary properties - what a PM scans, Jira-style. diagnostics live
            under 'technical details' below (progressive disclosure). */}
        <div id="props">
          <span className="k">State</span>
          <span><span className="chip"><span className="sdot" style={{ background: st[1] }} />{st[0]}</span></span>
          <span className="k">Work by</span>
          <span>
            <span className={`exectag et-${executor(t)}`}><span className="edot" />
              {executor(t) === "ai" ? "AI" : executor(t) === "human" ? "You" : "AI + You"}</span>
          </span>
          <span className="k">Priority</span>
          <span>
            <select style={sel} value={t.priority ?? "medium"} onChange={(ev) => edit({ priority: ev.target.value })}>
              {["urgent", "high", "medium", "low"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </span>
          <span className="k">Due</span>
          <span><input type="date" style={sel} value={t.due ?? ""} onChange={(ev) => edit({ due: ev.target.value })} /></span>
          <span className="k">Value</span>
          <span>
            <input type="number" style={{ ...sel, width: 90 }} value={val}
              onChange={(ev) => setVal(ev.target.value)} onBlur={saveVal}
              onKeyDown={(ev) => { if (ev.key === "Enter") ev.currentTarget.blur(); }} />
          </span>
          <span className="k">Client</span>
          <span>
            <input style={{ ...sel, width: 140 }} value={clientV} placeholder="-"
              onChange={(ev) => setClientV(ev.target.value)} onBlur={saveClient}
              onKeyDown={(ev) => { if (ev.key === "Enter") ev.currentTarget.blur(); }} />
          </span>
        </div>
        {e && (
          <div style={{ padding: "0 16px 12px", fontSize: 12.5, display: "flex", gap: 8, flexWrap: "wrap",
            alignItems: "center", borderBottom: "1px solid var(--glass-border)" }}>
            <span title="deliverable value">€{e.value}</span>
            <span style={{ color: "var(--txt-tertiary)" }}>·</span>
            <span title="AI cost" style={{ color: "var(--ai)" }}>AI ${e.ai_cost.toFixed(2)}</span>
            <span style={{ color: "var(--txt-tertiary)" }}>·</span>
            <span title="margin = value − AI cost"><b>margin €{(e.value - e.ai_cost).toFixed(2)}</b></span>
            <span style={{ color: "var(--txt-tertiary)" }}>·</span>
            <span title="your touch units" style={{ color: "var(--human)" }}>{e.touches} touch{e.touches === 1 ? "" : "es"}</span>
            {e.mode && <><span style={{ color: "var(--txt-tertiary)" }}>·</span>
              <span>{e.mode === "auto" ? "auto · AI" : "assisted"}</span></>}
          </div>
        )}
        <div style={{ padding: "8px 16px 0" }}>
          <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => setDetails(!details)}>
            <IconChevron dir={details ? "down" : "right"} size={11} /> technical details
          </button>
          {details && (
            <div id="props" style={{ marginTop: 8, paddingBottom: 4 }}>
              <span className="k">Driver</span>
              <span>
                <select style={sel} value={t.driver ?? "claude"} onChange={(ev) => edit({ driver: ev.target.value })}>
                  {drivers.map((d) => <option key={d}>{d}</option>)}
                </select>
              </span>
              <span className="k">Repo</span><span style={{ fontSize: 12, wordBreak: "break-all" }}>{t.repo}</span>
              <span className="k">Session</span>
              <span style={{ fontSize: 12, wordBreak: "break-all", color: "var(--txt-tertiary)" }}>{t.session_id ?? "not started"}</span>
              {e && <><span className="k">Tokens</span>
                <span style={{ fontSize: 12 }}>{e.tokens_in.toLocaleString()} in / {e.tokens_out.toLocaleString()} out{e.models.length ? ` · ${e.models.join(", ")}` : ""}</span></>}
              {turns.length > 0 && (
                <>
                  <span className="k">AI turns</span>
                  <span>
                    {turns.map((tu, i) => {
                      const u = tu.usage ?? {};
                      const tin = (u.input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0);
                      return (
                        <div key={i} style={{ display: "flex", gap: 10, fontSize: 11.5, color: "var(--txt-secondary)", padding: "1.5px 0" }}>
                          <span style={{ color: "var(--txt-tertiary)", width: 84, flexShrink: 0 }}>{tu.ts?.slice(5, 16)}</span>
                          <span style={{ width: 96, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{(tu.models?.[0] ?? "-").replace("claude-", "")}</span>
                          <span style={{ fontVariantNumeric: "tabular-nums" }}>{tin.toLocaleString()}/{(u.output_tokens ?? 0).toLocaleString()} · ${(tu.cost ?? 0).toFixed(3)}</span>
                        </div>
                      );
                    })}
                  </span>
                </>
              )}
            </div>
          )}
        </div>
        {t.status === "running" && met?.settings?.drivers?.[t.driver]?.record && (
          <div style={{ padding: "10px 16px 0" }}><LiveThumb trackId={t.id} big /></div>
        )}
        <div id="feed" ref={feedRef}>
          {/* Paseo-style: every turn - the agent's text, thinking and each tool
              call/result, straight from the session transcript. Falls back to the
              steer/reply log until the session has run. */}
          {trans.length ? <Transcript steps={trans} /> : hist.map((r, i) =>
            r.kind === "steer" ? <div key={i} className="cb you">{r.detail}</div> :
            r.kind === "reply" ? <div key={i} className="cb bot"><Markdown>{r.detail}</Markdown></div> :
            <div key={i} className="cb sys">{r.detail}</div>
          )}
        </div>
        <div style={{ padding: "10px 16px 0", fontSize: 11, color: "var(--txt-tertiary)" }}>
          Talk to this card&apos;s <b style={{ color: "var(--txt-secondary)" }}>worker</b>
          {t.session_id ? ` · session ${t.session_id.slice(0, 8)}…` : " · not started yet"}
        </div>
        <Composer onSend={sendSteer} onStop={stopTurn} busy={t.status === "running"}
          draftKey={`swarm-draft:card:${t.id}`} modeOptions={modeOpts}
          context={lastIn ? { used: lastIn, total: 200000 } : undefined}
          placeholder="Tell this worker what to do - its context continues, no rebuild"
          slashCommands={[
            { name: "plan", hint: "plan before acting", insert: "Make a plan for: " },
            { name: "test", hint: "run tests, report failures", insert: "Run the tests and report any failures." },
            { name: "diff", hint: "summarize current changes", insert: "Summarize the current diff on this branch." },
            { name: "commit", hint: "commit the work", insert: "Commit the current work with a clear message." },
          ]} />
      </div>
    </>
  );
}
