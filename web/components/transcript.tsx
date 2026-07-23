"use client";
import { useState } from "react";
import Markdown from "./markdown";
import {
  IconFile, IconPen, IconSearch, IconGlobe, IconBot, IconGear, IconTerminal,
  IconChevron, IconCopy, IconCheck,
} from "./icons";

export interface Step {
  role?: string;
  kind: "text" | "thinking" | "tool" | "result" | "todos" | "plan";
  text?: string; tool?: string; result?: string; ok?: boolean; ts?: string;
  todos?: { content: string; status: string }[];
}

const TOOL_ICON: Record<string, (p: { size?: number }) => React.ReactElement> = {
  Bash: IconTerminal, Read: IconFile, Edit: IconPen, Write: IconPen, MultiEdit: IconPen,
  NotebookEdit: IconPen, Grep: IconSearch, Glob: IconSearch, WebFetch: IconGlobe,
  WebSearch: IconGlobe, Task: IconBot,
};
const toolIcon = (name: string) => TOOL_ICON[name] || (name.startsWith("mcp__") ? IconGlobe : IconGear);

function copy(text: string) { try { navigator.clipboard.writeText(text); } catch { /* ignore */ } }

// a tool call, expandable to its result - Paseo's tool-card shape
function ToolCard({ s }: { s: Step }) {
  const [open, setOpen] = useState(false);
  const Ic = toolIcon(s.tool || "");
  const hasResult = !!(s.result && s.result.trim());
  return (
    <div className="tcall">
      <button className={"tcall-head" + (hasResult ? "" : " nores")} onClick={() => hasResult && setOpen((o) => !o)}>
        <span className={"tcall-ic" + (s.ok === false ? " err" : "")}><Ic size={12} /></span>
        <b className="tcall-name">{s.tool}</b>
        <span className="tcall-sum">{s.text}</span>
        {s.ts && <span className="tcall-ts">{s.ts}</span>}
        {hasResult && <span className="tcall-chev"><IconChevron dir={open ? "down" : "right"} size={11} /></span>}
      </button>
      {open && hasResult && <pre className="tcall-out"><code>{s.result}</code></pre>}
    </div>
  );
}

function AssistantText({ s }: { s: Step }) {
  return (
    <div className="cb bot cb-md">
      <Markdown>{s.text || ""}</Markdown>
      <div className="cb-meta">
        {s.ts && <span className="cb-ts">{s.ts}</span>}
        <button className="cb-copy" title="Copy message" onClick={() => copy(s.text || "")}><IconCopy size={12} /></button>
      </div>
    </div>
  );
}

function Todos({ s }: { s: Step }) {
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
}

// one renderer for the whole conversation - used by every chat surface
export default function Transcript({ steps }: { steps: Step[] }) {
  return (
    <>
      {steps.map((s, i) => {
        if (s.kind === "tool") return <ToolCard key={i} s={s} />;
        if (s.kind === "todos") return <Todos key={i} s={s} />;
        if (s.kind === "plan") return <div key={i} className="plancard"><div className="plancard-h">Plan</div><Markdown>{s.text || ""}</Markdown></div>;
        if (s.kind === "thinking") return <div key={i} className="cb tk">{s.text}</div>;
        if (s.kind === "result") return <div key={i} className="cb res">{s.text}</div>;
        if (s.role === "user") return <div key={i} className="cb you">{s.text}</div>;
        return <AssistantText key={i} s={s} />;
      })}
    </>
  );
}
