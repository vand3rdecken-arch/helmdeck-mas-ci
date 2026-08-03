"use client";
import { useState, useRef, useEffect, memo } from "react";
import Markdown from "./markdown";
import {
  IconFile, IconPen, IconSearch, IconGlobe, IconBot, IconGear, IconTerminal,
  IconChevron, IconCopy, IconCheck, IconUndo,
} from "./icons";

export interface ToolDetail {
  type: "edit" | "multiedit" | "write";
  file?: string; old?: string; new?: string; content?: string;
  edits?: { old: string; new: string }[];
}
export interface Step {
  role?: string;
  kind: "text" | "thinking" | "tool" | "result" | "todos" | "plan" | "compaction" | "system";
  text?: string; tool?: string; result?: string; ok?: boolean; running?: boolean; ts?: string;
  streaming?: boolean;
  todos?: { content: string; status: string }[];
  detail?: ToolDetail;
}

// minimal line-level diff hunk: common prefix/suffix trimmed to a little context,
// the changed middle shown as -removed / +added (Paseo renders edits as diffs).
function DiffHunk({ oldText, newText }: { oldText: string; newText: string }) {
  const a = (oldText || "").split("\n");
  const b = (newText || "").split("\n");
  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  let sa = a.length, sb = b.length;
  while (sa > p && sb > p && a[sa - 1] === b[sb - 1]) { sa--; sb--; }
  const ctx = 2;
  const before = a.slice(Math.max(p - ctx, 0), p);
  const removed = a.slice(p, sa);
  const added = b.slice(p, sb);
  const after = a.slice(sa, Math.min(sa + ctx, a.length));
  const row = (t: string, cls: string, mark: string, k: string) => (
    <div key={k} className={"diff-line " + cls}><span className="diff-mark">{mark}</span>{t || " "}</div>
  );
  return (
    <div className="diff">
      {before.map((l, i) => row(l, "ctx", " ", "b" + i))}
      {removed.map((l, i) => row(l, "del", "−", "d" + i))}
      {added.map((l, i) => row(l, "add", "+", "a" + i))}
      {after.map((l, i) => row(l, "ctx", " ", "f" + i))}
    </div>
  );
}

function ToolDetailView({ d }: { d: ToolDetail }) {
  return (
    <div className="tdetail">
      {d.file && <div className="tdetail-file">{d.file}</div>}
      {d.type === "edit" && <DiffHunk oldText={d.old || ""} newText={d.new || ""} />}
      {d.type === "multiedit" && (d.edits || []).map((e, i) => <DiffHunk key={i} oldText={e.old} newText={e.new} />)}
      {d.type === "write" && <DiffHunk oldText="" newText={d.content || ""} />}
    </div>
  );
}

const TOOL_ICON: Record<string, (p: { size?: number }) => React.ReactElement> = {
  Bash: IconTerminal, Read: IconFile, Edit: IconPen, Write: IconPen, MultiEdit: IconPen,
  NotebookEdit: IconPen, Grep: IconSearch, Glob: IconSearch, WebFetch: IconGlobe,
  WebSearch: IconGlobe, Task: IconBot,
};
const toolIcon = (name: string) => TOOL_ICON[name] || (name.startsWith("mcp__") ? IconGlobe : IconGear);

function copy(text: string, done?: () => void) {
  try { navigator.clipboard.writeText(text); done?.(); } catch { /* ignore */ }
}

// Step content is append-only (immutable once written), but each live refetch
// creates new objects. Compare by value so memoized rows don't re-render (and
// re-parse markdown / rebuild diffs) every tick - only the growing last step does.
const detailSig = (d?: ToolDetail) =>
  d ? `${d.type}|${d.file || ""}|${(d.old || "").length}|${(d.new || "").length}|${(d.content || "").length}|${d.edits?.length || 0}` : "";
const todosSig = (t?: { content: string; status: string }[]) =>
  (t || []).map((x) => x.status + x.content).join("~");
function sameStep(a: { s: Step }, b: { s: Step }) {
  const x = a.s, y = b.s;
  return x.text === y.text && x.result === y.result && x.running === y.running
    && x.ok === y.ok && x.ts === y.ts && x.tool === y.tool && x.role === y.role
    && x.streaming === y.streaming
    && detailSig(x.detail) === detailSig(y.detail) && todosSig(x.todos) === todosSig(y.todos);
}

// clamps long content and reveals a Show more / Show less toggle only when it
// actually overflows (Paseo's showMore / showLess).
function Collapsible({ children, max = 340 }: { children: React.ReactNode; max?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [overflow, setOverflow] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (el) setOverflow(el.scrollHeight > max + 28);
  });
  const clamp = !open && overflow;
  return (
    <div className="collap">
      <div ref={ref} className={"collap-body" + (clamp ? " clamped" : "")}
        style={clamp ? { maxHeight: max } : undefined}>{children}</div>
      {overflow && (
        <button className="collap-toggle" onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

// a tool call, expandable to its result; shimmers while still running
const ToolCard = memo(function ToolCard({ s }: { s: Step }) {
  const [open, setOpen] = useState(false);
  const Ic = toolIcon(s.tool || "");
  const hasResult = !!(s.result && s.result.trim());
  const expandable = hasResult || !!s.detail;
  return (
    <div className="tcall">
      <button className={"tcall-head" + (expandable ? "" : " nores") + (s.running ? " running" : "")}
        onClick={() => expandable && setOpen((o) => !o)}>
        <span className={"tcall-ic" + (s.ok === false ? " err" : "")}><Ic size={12} /></span>
        <b className="tcall-name">{s.tool}</b>
        <span className="tcall-sum">{s.text}</span>
        {s.running && <span className="tcall-run" />}
        {s.ts && <span className="tcall-ts">{s.ts}</span>}
        {expandable && <span className="tcall-chev"><IconChevron dir={open ? "down" : "right"} size={11} /></span>}
      </button>
      {open && (
        <Collapsible max={340}>
          {s.detail && <ToolDetailView d={s.detail} />}
          {hasResult && <pre className="tcall-out"><code>{s.result}</code></pre>}
        </Collapsible>
      )}
    </div>
  );
}, sameStep);

const AssistantText = memo(function AssistantText({ s }: { s: Step }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className={"cb bot cb-md" + (s.streaming ? " streaming" : "")}>
      <Collapsible><Markdown>{s.text || ""}</Markdown></Collapsible>
      {s.streaming && <span className="stream-cursor" />}
      {!s.streaming && <div className="cb-meta">
        {s.ts && <span className="cb-ts">{s.ts}</span>}
        <button className="cb-copy" title="Copy message"
          onClick={() => copy(s.text || "", () => { setCopied(true); setTimeout(() => setCopied(false), 1400); })}>
          {copied ? <IconCheck size={12} /> : <IconCopy size={12} />}</button>
      </div>}
    </div>
  );
}, sameStep);

function UserText({ s, onRewind }: { s: Step; onRewind?: (text: string) => void }) {
  return (
    <div className="cb you cb-user">
      <Collapsible max={260}><div className="cb-usertext">{s.text}</div></Collapsible>
      <div className="cb-meta on-accent">
        {s.ts && <span className="cb-ts">{s.ts}</span>}
        <button className="cb-copy" title="Copy message" onClick={() => copy(s.text || "")}><IconCopy size={12} /></button>
        {onRewind && (
          <button className="cb-copy" title="Edit from here (put this back in the composer)"
            onClick={() => onRewind(s.text || "")}><IconUndo size={12} /></button>
        )}
      </div>
    </div>
  );
}

// agent reasoning - collapsed by default (Paseo shows thinking behind a toggle)
const Thought = memo(function Thought({ s }: { s: Step }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="thought">
      <button className="thought-h" onClick={() => setOpen((o) => !o)}>
        <IconChevron dir={open ? "down" : "right"} size={11} /> Thinking
      </button>
      {open && <Collapsible max={260}><div className="thought-body">{s.text}</div></Collapsible>}
    </div>
  );
}, sameStep);

const Todos = memo(function Todos({ s }: { s: Step }) {
  return (
    <div className="todos">
      <div className="todos-h">Plan / to-dos</div>
      {s.todos?.map((td, i) => (
        <div key={i} className={"todo st-" + td.status}>
          <span className="todo-box">{td.status === "completed" ? <IconCheck size={10} /> : td.status === "in_progress" ? "…" : ""}</span>
          <span className={td.status === "completed" ? "todo-done" : ""}>{td.content}</span>
        </div>
      ))}
    </div>
  );
}, sameStep);

// one renderer for the whole conversation - used by every chat surface.
// onRewind (optional): put a past user message back in the composer to edit & resend.
export default function Transcript({ steps, onRewind }: { steps: Step[]; onRewind?: (text: string) => void }) {
  return (
    <>
      {steps.map((s, i) => {
        if (s.kind === "compaction") return (
          <div key={i} className="compact-mark"><span>⟳ Context compacted{s.ts ? ` · ${s.ts}` : ""}</span></div>
        );
        if (s.kind === "system") {
          // lifecycle event from the actionlog (dispatched, gate, merge, deploy,
          // accepted, bounced) woven into the same feed as the agent's turns.
          const good = /\b(MERGED|ACCEPTED|GATE PASSED|DEPLOY HOOK OK|DISPATCHED|CONNECTOR INSTALLED)\b/.test(s.text || "");
          const bad = /\b(FAILED|BOUNCED|conflict)\b/i.test(s.text || "");
          return (
            <div key={i} className={"tl-event" + (bad ? " bad" : good ? " good" : "")}>
              <span className="tl-dot" /><span className="tl-text">{s.text}</span>
              {s.ts && <span className="tl-ts">{s.ts}</span>}
            </div>
          );
        }
        if (s.kind === "tool") return <ToolCard key={i} s={s} />;
        if (s.kind === "todos") return <Todos key={i} s={s} />;
        if (s.kind === "plan") return <div key={i} className="plancard"><div className="plancard-h">Plan</div><Collapsible><Markdown>{s.text || ""}</Markdown></Collapsible></div>;
        if (s.kind === "thinking") return <Thought key={i} s={s} />;
        if (s.kind === "result") return <div key={i} className="cb res">{s.text}</div>;
        if (s.role === "user") return <UserText key={i} s={s} onRewind={onRewind} />;
        return <AssistantText key={i} s={s} />;
      })}
    </>
  );
}
