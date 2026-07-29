"use client";
import { useEffect, useRef, useState } from "react";
import { get, post, HistoryRow, Track } from "@/lib/api";

interface Turn { ts: string; cost?: number; models?: string[]; usage?: { input_tokens?: number; output_tokens?: number; cache_read_input_tokens?: number; cache_creation_input_tokens?: number } }
import { STATUS, useBoard } from "@/lib/store";
import LiveThumb from "./live";
import { executor } from "./board";
import Composer, { SendOpts, Attach } from "./composer";
import { IconX, IconFork, IconChevron, IconExpand, IconShrink, IconPaperclip, IconFile, IconUndo } from "./icons";
import Markdown from "./markdown";
import Transcript, { Step } from "./transcript";

export default function Peek({ t, onClose }: { t: Track; onClose: () => void }) {
  const { met, me, toast, refresh } = useBoard();
  const [hist, setHist] = useState<HistoryRow[]>([]);
  const [trans, setTrans] = useState<Step[]>([]);
  // optimistic echo: your just-sent message shows instantly, before the worker
  // resumes and writes it to the session transcript. Reconciled away once the
  // real transcript (or history) contains that text - so no duplicate, no flicker.
  const [pending, setPending] = useState<Step[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [details, setDetails] = useState(false);
  const [full, setFull] = useState(false);
  const [task, setTask] = useState(t.task);
  const [desc, setDesc] = useState(t.description ?? "");
  const [atts, setAtts] = useState<{ name: string; size: number }[]>([]);
  const [val, setVal] = useState(String(t.value ?? ""));
  const [rateV, setRateV] = useState(String(t.rate ?? ""));
  const [clientV, setClientV] = useState(t.client ?? "");
  const taRef = useRef<HTMLTextAreaElement>(null);
  const descRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const [restore, setRestore] = useState<{ text: string; key: number }>({ text: "", key: 0 });
  const [atBottom, setAtBottom] = useState(true);
  const [ckpts, setCkpts] = useState<{ turn: number; commit: string; ts: string; reply: string }[]>([]);
  const e = met?.cards.find((x) => x.id === t.id);
  const cur = met?.settings?.currency === "USD" ? "$" : "€";
  const st = STATUS[t.status] ?? [t.status, "var(--txt-tertiary)"];
  const drivers = Object.keys(met?.settings?.drivers ?? { claude: {} });

  useEffect(() => { setTask(t.task); }, [t.id, t.task]);
  useEffect(() => { setDesc(t.description ?? ""); }, [t.id, t.description]);
  useEffect(() => { setPending([]); }, [t.id]);   // don't leak echoes across cards
  useEffect(() => {
    get<{ name: string; size: number }[]>(`/tracks/${t.id}/attachments`).then(setAtts).catch(() => setAtts([]));
  }, [t.id, t.updated]);
  useEffect(() => {
    if (me?.role !== "owner") return;
    get<typeof ckpts>(`/tracks/${t.id}/checkpoints`).then(setCkpts).catch(() => setCkpts([]));
  }, [t.id, t.updated, me?.role]);
  async function rewindTo(commit: string) {
    if (!confirm("Restore this card's FILES to this checkpoint?\n\nThe current files are snapshotted first (reversible), and the conversation is left untouched.")) return;
    const r = await post<{ error?: string }>(`/tracks/${t.id}/rewind`, { commit });
    if (r.error) { toast(r.error, 3600); return; }
    toast("Files restored to this checkpoint");
    refresh();
  }
  // keep value/client in sync when the card updates from polls, but only when the
  // real field changed - so live polling never wipes what you're typing.
  useEffect(() => { setVal(String(t.value ?? "")); }, [t.id, t.value]);
  useEffect(() => { setRateV(String(t.rate ?? "")); }, [t.id, t.rate]);
  useEffect(() => { setClientV(t.client ?? ""); }, [t.id, t.client]);
  // keep the feed pinned to the newest message as it grows - but only when the
  // reader is already at the bottom, so scrolling up to read isn't yanked back.
  useEffect(() => {
    const f = feedRef.current;
    if (f && atBottom) f.scrollTop = f.scrollHeight;
  }, [trans, hist, pending, atBottom]);
  const onFeedScroll = () => {
    const f = feedRef.current;
    if (f) setAtBottom(f.scrollHeight - f.scrollTop - f.clientHeight < 60);
  };
  const jumpToBottom = () => {
    const f = feedRef.current;
    if (f) { f.scrollTop = f.scrollHeight; setAtBottom(true); }
  };
  // drop an optimistic echo once the real feed (transcript or steer history)
  // carries that same text - the server copy takes over seamlessly.
  useEffect(() => {
    if (!pending.length) return;
    const seen = new Set<string>([
      ...trans.filter((s) => s.role === "user").map((s) => (s.text ?? "").trim()),
      ...hist.filter((r) => r.kind === "steer").map((r) => (r.detail ?? "").trim()),
    ]);
    setPending((p) => p.filter((e) => !seen.has((e.text ?? "").trim())));
  }, [trans, hist]);   // eslint-disable-line react-hooks/exhaustive-deps
  function saveVal() { const n = parseFloat(val); if (!isNaN(n) && n !== t.value) edit({ value: n }); }
  function saveRate() { const n = parseFloat(rateV); if (!isNaN(n) && n !== t.rate) edit({ rate: n }); }
  function saveClient() { if (clientV.trim() !== (t.client ?? "")) edit({ client: clientV.trim() }); }
  function saveDesc() { if (desc !== (t.description ?? "")) edit({ description: desc }); }
  useEffect(() => {   // grow the title box to fit the full task (no hidden scroll)
    const ta = taRef.current;
    if (ta) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 300) + "px"; }
  }, [task]);
  useEffect(() => {   // grow the description box to fit its content
    const ta = descRef.current;
    if (ta) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 420) + "px"; }
  }, [desc]);
  async function onFiles(files: FileList | null) {
    if (!files?.length) return;
    const arr = await Promise.all([...files].map((f) => new Promise<Attach>((res) => {
      const r = new FileReader();
      r.onload = () => res({ name: f.name, data: String(r.result), mime: f.type });
      r.readAsDataURL(f);
    })));
    const r = await post<{ error?: string }>(`/tracks/${t.id}/attach`, { attachments: arr });
    if (r.error) { toast(r.error, 3600); return; }
    get<{ name: string; size: number }[]>(`/tracks/${t.id}/attachments`).then(setAtts).catch(() => {});
    toast(`Attached ${arr.length} file${arr.length === 1 ? "" : "s"}`);
  }
  async function removeAtt(name: string) {
    await post(`/tracks/${t.id}/attach/remove`, { name });
    setAtts((a) => a.filter((x) => x.name !== name));
  }
  const fmtSize = (b: number) => b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1048576).toFixed(1)} MB`;
  useEffect(() => {
    get<HistoryRow[]>(`/tracks/${t.id}/history`).then(setHist).catch(() => setHist([]));
    get<Turn[]>(`/tracks/${t.id}/turns`).then(setTurns).catch(() => setTurns([]));
    get<Step[]>(`/tracks/${t.id}/transcript`).then(setTrans).catch(() => setTrans([]));
  }, [t.id, t.updated]);
  // live: while a turn runs, subscribe to the card's SSE stream so the transcript
  // grows in real time (the daemon watches the live session .jsonl and pushes) -
  // real streaming, no poll. Falls back to the on-open fetch if SSE drops.
  useEffect(() => {
    if (t.status !== "running" || !t.session_id) return;
    const es = new EventSource(`/sse/tracks/${t.id}`);
    const pull = () => get<Step[]>(`/tracks/${t.id}/transcript`).then(setTrans).catch(() => {});
    es.onmessage = pull;   // tick = the session .jsonl grew -> pull the fresh transcript
    return () => es.close();
  }, [t.id, t.status, t.session_id]);

  async function edit(patch: Record<string, unknown>) {
    const r = await post<{ error?: string }>(`/tracks/${t.id}/update`, patch);
    if (r.error) { toast(r.error, 3600); return; }
    toast("Saved");
    refresh();
  }

  async function sendSteer(v: string, opts: SendOpts) {
    if (!v && !opts.attachments.length) return;
    const echo = v || (opts.attachments.length ? "(see attachment)" : "");
    // show it instantly - don't wait for the round-trip
    const hhmm = new Date().toTimeString().slice(0, 5);
    setPending((p) => [...p, { kind: "text", role: "user", text: echo, ts: hhmm }]);
    try {
      await post(`/tracks/${t.id}/steer`, {
        text: v || "(see attachment)", model: opts.model, thinking: opts.thinking,
        attachments: opts.attachments, mode: opts.mode,
      });
      toast("Steer sent - session resuming");
    } catch {
      setPending((p) => p.filter((e) => e.text !== echo));   // send failed - retract the echo
      toast("Send failed", 3600);
      return;
    }
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
        {/* description - the long-form body (Jira/Plane). saves on blur. */}
        <textarea
          ref={descRef}
          className="pdesc"
          value={desc}
          onChange={(ev) => setDesc(ev.target.value)}
          onBlur={saveDesc}
          placeholder="Add a description… (context, acceptance criteria, links). The worker reads it."
          style={{ margin: "0 16px 8px", fontSize: 13, lineHeight: 1.55, minHeight: 40, maxHeight: 420, resize: "vertical", overflowY: "auto" }}
        />
        {/* attachments - PDFs, specs, screenshots the worker should read */}
        <div className="patt">
          {atts.map((a) => (
            <span key={a.name} className="patt-chip">
              <a href={`/backend/tracks/${t.id}/attachment/${encodeURIComponent(a.name)}`}
                target="_blank" rel="noreferrer" title={`${a.name} · ${fmtSize(a.size)}`}>
                <IconFile size={12} /> <span className="patt-name">{a.name.replace(/^\d+_/, "")}</span>
                <span className="patt-size">{fmtSize(a.size)}</span>
              </a>
              <button className="patt-x" title="Detach" onClick={() => removeAtt(a.name)}><IconX size={11} /></button>
            </span>
          ))}
          <button className="patt-add" onClick={() => fileRef.current?.click()}>
            <IconPaperclip size={12} /> Attach
          </button>
          <input ref={fileRef} type="file" multiple hidden
            accept="image/*,.pdf,.txt,.md,.csv,.json,.log,.doc,.docx,.xls,.xlsx,.py,.ts,.tsx,.js"
            onChange={(ev) => { onFiles(ev.target.files); ev.target.value = ""; }} />
        </div>
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
          <span className="k">Billing</span>
          <span>
            <select style={sel} value={t.billing ?? "fixed"} onChange={(ev) => edit({ billing: ev.target.value })}
              title="fixed = agreed price, recognized on delivery · time & material = worked hours × rate · internal = unbilled">
              <option value="fixed">Fixed price</option>
              <option value="tm">Time &amp; material</option>
              <option value="none">Internal</option>
            </select>
          </span>
          {(t.billing ?? "fixed") === "fixed" && <>
            <span className="k">Price</span>
            <span>
              <input type="number" style={{ ...sel, width: 90 }} value={val} title="agreed fixed price"
                onChange={(ev) => setVal(ev.target.value)} onBlur={saveVal}
                onKeyDown={(ev) => { if (ev.key === "Enter") ev.currentTarget.blur(); }} />
            </span>
          </>}
          {t.billing === "tm" && <>
            <span className="k">Rate {cur}/h</span>
            <span>
              <input type="number" style={{ ...sel, width: 90 }} value={rateV} placeholder="0" title="hourly rate; billed on worked hours"
                onChange={(ev) => setRateV(ev.target.value)} onBlur={saveRate}
                onKeyDown={(ev) => { if (ev.key === "Enter") ev.currentTarget.blur(); }} />
            </span>
          </>}
          <span className="k">Client</span>
          <span>
            <input style={{ ...sel, width: 140 }} value={clientV} placeholder="-"
              onChange={(ev) => setClientV(ev.target.value)} onBlur={saveClient}
              onKeyDown={(ev) => { if (ev.key === "Enter") ev.currentTarget.blur(); }} />
          </span>
        </div>
        <div style={{ padding: "8px 16px 0" }}>
          <button className="btn ghost" style={{ fontSize: 11 }} onClick={() => setDetails(!details)}>
            <IconChevron dir={details ? "down" : "right"} size={11} /> technical details
          </button>
          {details && (
            <div id="props" style={{ marginTop: 8, paddingBottom: 4 }}>
              {e && me?.role === "owner" && <>
                <span className="k">Economics</span>
                <span style={{ fontSize: 12 }}>
                  <span title={e.billing === "tm" ? "time & material (hours × rate)" : e.billing === "none" ? "internal / unbilled" : "fixed price (on delivery)"}>
                    €{(e.billed ?? e.value).toFixed(2)}{e.billing === "tm" ? " ~" : ""}</span>
                  {" · "}<span style={{ color: "var(--ai)" }}>AI ${e.ai_cost.toFixed(2)}</span>
                  {" · "}<b>margin €{(e.margin ?? (e.value - e.ai_cost)).toFixed(2)}</b>
                  {" · "}<span style={{ color: "var(--human)" }}>{e.touches} touch{e.touches === 1 ? "" : "es"}</span>
                  {e.mode && ` · ${e.mode === "auto" ? "auto" : "assisted"}`}
                </span>
              </>}
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
              {ckpts.length > 0 && <>
                <span className="k">Rewind</span>
                <span>
                  {ckpts.slice().reverse().map((c, i) => (
                    <div key={i} className="ckpt-row">
                      <span className="ckpt-meta">turn {c.turn} · {c.ts.slice(11, 16)}</span>
                      <span className="ckpt-reply" title={c.reply}>{c.reply}</span>
                      <button className="ckpt-btn" title="Restore the worktree files to this point (reversible)"
                        onClick={() => rewindTo(c.commit)}><IconUndo size={11} /> restore files</button>
                    </div>
                  ))}
                  <div style={{ fontSize: 11, color: "var(--txt-tertiary)", marginTop: 4 }}>
                    Files only, reversible. For a fresh line from a point, use fork.
                  </div>
                </span>
              </>}
            </div>
          )}
        </div>
        {t.status === "running" && met?.settings?.drivers?.[t.driver]?.record && (
          <div style={{ padding: "10px 16px 0" }}><LiveThumb trackId={t.id} big /></div>
        )}
        <div id="feed" ref={feedRef} onScroll={onFeedScroll}>
          {/* Paseo-style: every turn - the agent's text, thinking and each tool
              call/result, straight from the session transcript. Falls back to the
              steer/reply log until the session has run. */}
          {trans.length ? <Transcript steps={trans} onRewind={(txt) => setRestore({ text: txt, key: restore.key + 1 })} /> : hist.map((r, i) =>
            r.kind === "steer" ? <div key={i} className="cb you">{r.detail}</div> :
            r.kind === "reply" ? <div key={i} className="cb bot"><Markdown>{r.detail}</Markdown></div> :
            <div key={i} className="cb sys">{r.detail}</div>
          )}
          {pending.map((s, i) => (
            <div key={"pend" + i} className="cb you pending">{s.text}
              {s.ts && <span className="cb-ts">{s.ts} · sending…</span>}</div>
          ))}
        </div>
        {!atBottom && (
          <button className="feed-jump" title="Scroll to bottom" onClick={jumpToBottom}>
            <IconChevron dir="down" size={16} />
          </button>
        )}
        <div style={{ padding: "10px 16px 0", fontSize: 11, color: "var(--txt-tertiary)" }}>
          Talk to this card&apos;s <b style={{ color: "var(--txt-secondary)" }}>worker</b>
          {t.session_id ? ` · session ${t.session_id.slice(0, 8)}…` : " · not started yet"}
        </div>
        <Composer onSend={sendSteer} onStop={stopTurn} busy={t.status === "running"}
          draftKey={`swarm-draft:card:${t.id}`} modeOptions={modeOpts} seed={restore}
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
