"use client";
import { useState } from "react";
import { get, post, Track } from "@/lib/api";
import { useBoard } from "@/lib/store";
import { IconBug, IconSparkle, IconMonitor, IconGlobe, IconSearch, IconChevron, IconX, IconPlay } from "./icons";
import Composer, { SendOpts } from "./composer";

interface ClaudeSession { id: string; cwd: string; project: string; first: string; last_active: string }

const EXAMPLES = [
  { icon: IconBug, label: "bug fix", task: "Fix: the dashboard capacity gauge shows 0% when touch budget is 0 - guard the division and show a hint instead.", driver: "claude" },
  { icon: IconSparkle, label: "feature", task: "Add a CSV export button to the dashboard work table (all columns, current filters applied).", driver: "claude" },
  { icon: IconMonitor, label: "desktop task", task: "Open the invoice tool, export June as PDF into Downloads, and verify the file exists.", driver: "claude-desktop" },
  { icon: IconGlobe, label: "browser task", task: "Go to the supplier portal, download the latest price list, and summarize what changed vs the file in data/prices.csv.", driver: "claude-desktop" },
  { icon: IconSearch, label: "research", task: "Read the three competitor changelogs linked in docs/watchlist.md and write a one-page summary of what shipped this month.", driver: "claude" },
];

export default function NewRequestModal({ onClose }: { onClose: () => void }) {
  const { met, toast, refresh } = useBoard();
  const [priority, setPriority] = useState("medium");
  const [due, setDue] = useState("");
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("");
  const [value, setValue] = useState("");
  const [client, setClient] = useState("");
  const [driver, setDriver] = useState("claude");
  const [adv, setAdv] = useState(false);
  const [seed, setSeed] = useState<{ text: string; key: number } | undefined>();
  const [showSess, setShowSess] = useState(false);
  const [sessions, setSessions] = useState<ClaudeSession[] | null>(null);
  const [sessSel, setSessSel] = useState<ClaudeSession | null>(null);
  const drivers = Object.keys(met?.settings?.drivers ?? { claude: {} });

  function openSessions() {
    setShowSess((v) => !v);
    if (sessions === null) get<ClaudeSession[]>("/sessions/claude").then(setSessions).catch(() => setSessions([]));
  }

  // the composer's send is the primary action. Fresh card -> /tracks/new.
  // A picked session -> adopt it as a card (continue), with any typed text sent
  // as the first steer. Same one button either way.
  async function file(text: string, opts: SendOpts) {
    const tv = text.trim();
    if (sessSel) {
      const r = await post<Track & { error?: string }>("/sessions/claude/adopt",
        { session_id: sessSel.id, cwd: sessSel.cwd, first: sessSel.first, mode: "continue" });
      if (r.error) { toast(r.error, 4000); return; }
      if (tv) await post(`/tracks/${r.id}/steer`, { text: tv, model: opts.model, attachments: opts.attachments });
      toast("Session continued as a card", 4000);
      refresh();
      onClose();
      return;
    }
    if (!tv) { toast("Describe the task"); return; }
    const body: Record<string, unknown> = {
      task: tv, lane: "backlog", priority, due, driver,
      model: opts.model, attachments: opts.attachments,
    };
    if (repo.trim()) body.repo = repo.trim();
    if (branch.trim()) body.branch = branch.trim();
    if (value.trim()) body.value = parseFloat(value);
    if (client.trim()) body.client = client.trim();
    const r = await post<{ error?: string }>("/tracks/new", body);
    if (r.error) { toast(r.error, 4000); return; }
    toast("Filed to Backlog");
    refresh();
    onClose();
  }

  return (
    <div id="modal" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div id="mcard">
        <h3>New request</h3>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          {EXAMPLES.map((ex) => {
            const Ic = ex.icon;
            return (
              <button key={ex.label} className="btn ghost" style={{ fontSize: 11, padding: "2px 9px" }}
                title={ex.task} onClick={() => { setSeed({ text: ex.task, key: (seed?.key ?? 0) + 1 }); setDriver(ex.driver); }}>
                <Ic size={12} />{ex.label}
              </button>
            );
          })}
        </div>

        {/* continue an existing Claude Code session, right from card creation */}
        <div className="adv" onClick={openSessions} style={{ display: "inline-flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
          <IconChevron dir={showSess ? "down" : "right"} size={11} /> continue an existing Claude session
        </div>
        {showSess && !sessSel && (
          <div style={{ maxHeight: 170, overflowY: "auto", border: "1px solid var(--border-subtle)", borderRadius: 10, marginBottom: 8 }}>
            {sessions === null && <div style={{ fontSize: 12, color: "var(--txt-tertiary)", padding: 10 }}>reading ~/.claude…</div>}
            {sessions?.length === 0 && <div style={{ fontSize: 12, color: "var(--txt-tertiary)", padding: 10 }}>no sessions found.</div>}
            {sessions?.map((s) => (
              <div key={s.id} onClick={() => { setSessSel(s); setShowSess(false); }}
                style={{ padding: "7px 10px", cursor: "pointer", borderBottom: "1px solid var(--glass-border)" }}
                className="sess-pick">
                <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                  <b style={{ fontSize: 12.5 }}>{s.project || "session"}</b>
                  <span style={{ fontSize: 10.5, color: "var(--txt-tertiary)" }}>{s.last_active}</span>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--txt-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.first || "(no text)"}</div>
              </div>
            ))}
          </div>
        )}
        {sessSel && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--bg-layer-1)", border: "1px solid var(--border-subtle)",
            borderLeft: "2px solid var(--accent)", borderRadius: 8, padding: "7px 10px", marginBottom: 8 }}>
            <IconPlay size={13} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>Continuing: {sessSel.project}</div>
              <div style={{ fontSize: 11, color: "var(--txt-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sessSel.first}</div>
            </div>
            <button className="btn ghost" style={{ fontSize: 11, padding: "2px 7px" }} onClick={() => setSessSel(null)}><IconX size={12} /></button>
          </div>
        )}

        <Composer draftKey="swarm-draft:newreq" hideThinking
          sendLabel={sessSel ? "Continue session" : "File to Backlog"} allowEmpty={!!sessSel}
          seed={seed} onSend={file}
          placeholder={sessSel ? "Optional: a first instruction for this session…"
            : "What needs doing - that's all that's required. Attach a file, pick a model, then File."} />
        {!sessSel && <>
        <div className="row" style={{ alignItems: "center", marginTop: 10 }}>
          <select value={priority} onChange={(e) => setPriority(e.target.value)} style={{ width: 130 }}>
            <option value="urgent">urgent</option><option value="high">high</option>
            <option value="medium">medium</option><option value="low">low</option>
          </select>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} style={{ width: 150 }} title="due date" />
          <span style={{ fontSize: 11, color: "var(--txt-tertiary)" }}>priority · due date</span>
        </div>
        {(!due || !value.trim()) && (
          <div style={{ fontSize: 11, color: "var(--txt-tertiary)", marginTop: 6 }}>
            tip: {[!due && "add a due date (shows risk on the timeline)",
              !value.trim() && `set a value in advanced (else €${met?.settings?.value_per_card ?? 50} default)`]
              .filter(Boolean).join(" · ")}
          </div>
        )}
        <div className="adv" onClick={() => setAdv(!adv)} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <IconChevron dir={adv ? "down" : "right"} size={11} /> advanced (repo / branch / value / client / driver)</div>
        {adv && <>
          <div className="row"><input style={{ flex: 1 }} placeholder="repo path (default preset used if empty)" value={repo} onChange={(e) => setRepo(e.target.value)} /></div>
          <div className="row">
            <input style={{ flex: 1 }} placeholder="branch (auto from task if empty)" value={branch} onChange={(e) => setBranch(e.target.value)} />
            <input style={{ width: 110 }} placeholder="value €" value={value} onChange={(e) => setValue(e.target.value)} />
            <input style={{ width: 130 }} placeholder="client" value={client} onChange={(e) => setClient(e.target.value)} />
          </div>
          <div className="row">
            <select style={{ flex: 1 }} value={driver} onChange={(e) => setDriver(e.target.value)}>
              {drivers.map((d) => (
                <option key={d} value={d}>
                  driver: {d}{met?.settings?.drivers?.[d]?.record ? " (screen-recorded)" : ""}
                </option>
              ))}
            </select>
          </div>
        </>}
        </>}
        <div className="foot">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
