"use client";
import { useState } from "react";
import { post } from "@/lib/api";
import { useBoard } from "@/lib/store";
import { IconBug, IconSparkle, IconMonitor, IconGlobe, IconSearch, IconChevron } from "./icons";
import Composer, { SendOpts } from "./composer";

const EXAMPLES = [
  { icon: IconBug, label: "bug fix", task: "Fix: the dashboard capacity gauge shows 0% when touch budget is 0 — guard the division and show a hint instead.", driver: "claude" },
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
  const drivers = Object.keys(met?.settings?.drivers ?? { claude: {} });

  // the composer's send IS "File to Backlog" - same principle as the chats,
  // and the model + attachments chosen here ride along onto the card.
  async function file(text: string, opts: SendOpts) {
    const tv = text.trim();
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
        <Composer draftKey="swarm-draft:newreq" hideThinking sendLabel="File to Backlog"
          seed={seed} onSend={file}
          placeholder="What needs doing — that's all that's required. Attach a file, pick a model, then File." />
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
        <div className="foot">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
