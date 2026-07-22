"use client";
import { useEffect, useRef, useState } from "react";
import { get } from "@/lib/api";
import {
  IconPaperclip, IconBrain, IconArrowUp, IconStop, IconSliders, IconFile, IconX,
} from "./icons";

export interface Attach { name: string; data: string; mime: string }
export interface SendOpts { model: string; thinking: string; attachments: Attach[]; mode?: string }
export interface SlashCommand { name: string; hint: string; insert: string }
export interface ModeOption { id: string; label: string }
interface ModelDef { id: string; label: string; desc?: string }

// the model list is served by the daemon (curated Claude manifest + your
// ~/.claude/settings.json) - fetched once and cached across composers.
let MODEL_CACHE: ModelDef[] | null = null;
// thinking levels — each maps to a real Claude Code budget keyword server-side
const THINK: { id: string; short: string }[] = [
  { id: "", short: "" }, { id: "think", short: "think" },
  { id: "think-hard", short: "hard" }, { id: "ultrathink", short: "ultra" },
];

// The shared chat composer — ported from Paseo (getpaseo/paseo), rebuilt for our
// stack. Both the board copilot and the card steer render this ONE component, so
// they can't drift. Functions: auto-grow input + draft, send / stop-while-running,
// queue-while-busy (edit / send-now), image+file attach (pick·paste·drop) with
// thumbnails·lightbox·remove, thinking levels, mode control, model+Auto, context
// meter, and a slash-command popover.
export default function Composer({
  onSend, onStop, busy, placeholder, draftKey, slashCommands, modeOptions, context,
  hideThinking, sendLabel, seed,
}: {
  onSend: (text: string, opts: SendOpts) => void | Promise<void>;
  onStop?: () => void;
  busy?: boolean;
  placeholder?: string;
  draftKey: string;
  slashCommands?: SlashCommand[];
  modeOptions?: ModeOption[];
  context?: { used: number; total: number };
  hideThinking?: boolean;              // filing a request has no live turn to think in
  sendLabel?: string;                  // text send button instead of the arrow (e.g. "File to Backlog")
  seed?: { text: string; key: number };  // inject text from outside (example chips)
}) {
  const [text, setText] = useState("");
  const [model, setModel] = useState("auto");
  const [thinking, setThinking] = useState("");
  const [mode, setMode] = useState(modeOptions?.[0]?.id ?? "");
  const [atts, setAtts] = useState<Attach[]>([]);
  const [queued, setQueued] = useState<{ text: string; opts: SendOpts } | null>(null);
  const [lightbox, setLightbox] = useState<Attach | null>(null);
  const [slashIdx, setSlashIdx] = useState(0);
  const [slashHide, setSlashHide] = useState(false);
  const [drag, setDrag] = useState(false);
  const [models, setModels] = useState<ModelDef[]>(MODEL_CACHE ?? []);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const flushing = useRef(false);

  // draft persistence, per surface (board / each card)
  useEffect(() => {
    try { const d = localStorage.getItem(draftKey); if (d) setText(d); } catch { /* ignore */ }
  }, [draftKey]);
  function write(v: string) {
    setText(v); setSlashHide(false);
    try { v ? localStorage.setItem(draftKey, v) : localStorage.removeItem(draftKey); } catch { /* ignore */ }
  }
  // external injection (e.g. New Request example chips) - overrides the draft
  useEffect(() => { if (seed) write(seed.text); /* eslint-disable-next-line */ }, [seed?.key]);
  // model list from the daemon (manifest + ~/.claude/settings.json), cached
  useEffect(() => {
    if (MODEL_CACHE) return;
    get<ModelDef[]>("/models").then((m) => { MODEL_CACHE = m; setModels(m); }).catch(() => {});
  }, []);
  useEffect(() => {
    const ta = taRef.current;
    if (ta) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px"; }
  }, [text]);

  // queue: when the agent frees up, send the held message
  useEffect(() => {
    if (!busy && queued && !flushing.current) {
      flushing.current = true;
      Promise.resolve(onSend(queued.text, queued.opts)).finally(() => { flushing.current = false; });
      setQueued(null);
    }
  }, [busy, queued, onSend]);

  const matches = (() => {
    if (slashHide || !slashCommands) return [];
    const m = text.match(/^\/(\S*)$/);
    return m ? slashCommands.filter((c) => c.name.startsWith(m[1].toLowerCase())) : [];
  })();
  const slashOpen = matches.length > 0;

  function buildOpts(): SendOpts {
    return { model, thinking, attachments: atts, ...(modeOptions ? { mode } : {}) };
  }
  function clearInput() {
    setText(""); setAtts([]);
    try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
    if (taRef.current) taRef.current.style.height = "auto";
  }
  function fire() {
    const v = text.trim();
    if (!v && !atts.length) return;
    const opts = buildOpts();
    if (busy) setQueued({ text: v, opts });   // hold until the agent is free
    else onSend(v, opts);
    clearInput();
  }
  function acceptSlash(c: SlashCommand) { write(c.insert); setSlashHide(true); taRef.current?.focus(); }

  async function addFiles(list: FileList | null) {
    if (!list) return;
    const next: Attach[] = [];
    for (const f of Array.from(list).slice(0, 6)) {
      if (f.size > 5 * 1024 * 1024) continue;                 // 5MB cap, matches backend
      const data = await new Promise<string>((res) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result || ""));
        r.readAsDataURL(f);
      });
      next.push({ name: f.name, data, mime: f.type });
    }
    setAtts((a) => [...a, ...next].slice(0, 6));
    if (fileRef.current) fileRef.current.value = "";
  }
  function onPaste(e: React.ClipboardEvent) {
    const imgs = Array.from(e.clipboardData.items).filter((i) => i.type.startsWith("image/"));
    if (imgs.length) {
      e.preventDefault();
      const dt = new DataTransfer();
      imgs.forEach((i) => { const f = i.getAsFile(); if (f) dt.items.add(f); });
      addFiles(dt.files);
    }
  }
  function onKey(e: React.KeyboardEvent) {
    if (slashOpen) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSlashIdx((i) => (i + 1) % matches.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setSlashIdx((i) => (i - 1 + matches.length) % matches.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); acceptSlash(matches[Math.min(slashIdx, matches.length - 1)]); return; }
      if (e.key === "Escape") { e.preventDefault(); setSlashHide(true); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); fire(); }
  }

  const thinkOn = thinking !== "";
  const thinkShort = THINK.find((x) => x.id === thinking)?.short ?? "";
  const pct = context && context.total > 0 ? Math.min(100, Math.round((context.used / context.total) * 100)) : 0;

  return (
    <div className={"composer" + (drag ? " drag" : "")}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}>

      {queued && (
        <div className="cmp-queued" title="queued — will send when the agent is free">
          <span className="cmp-qlabel">Queued</span>
          <span className="cmp-qtext" onClick={() => { write(queued.text); setQueued(null); }}>{queued.text || "(attachment)"}</span>
          <button className="cmp-qbtn" onClick={() => { const q = queued; setQueued(null); onSend(q.text, q.opts); }}>Send now</button>
          <button className="cmp-chipx" onClick={() => setQueued(null)} aria-label="drop queued"><IconX size={12} /></button>
        </div>
      )}

      {atts.length > 0 && (
        <div className="cmp-atts">
          {atts.map((a, i) => (
            <span className="cmp-chip" key={i} title={a.name}>
              {a.mime.startsWith("image/")
                ? <img className="cmp-thumb" src={a.data} alt={a.name} onClick={() => setLightbox(a)} />
                : <IconFile size={13} />}
              <span className="cmp-chipname">{a.name}</span>
              <button className="cmp-chipx" onClick={() => setAtts((x) => x.filter((_, j) => j !== i))}
                aria-label="remove attachment"><IconX size={12} /></button>
            </span>
          ))}
        </div>
      )}

      <div className="cmp-inputwrap">
        {slashOpen && (
          <div className="cmp-slash">
            {matches.map((c, i) => (
              <button key={c.name} className={"cmp-slashitem" + (i === Math.min(slashIdx, matches.length - 1) ? " on" : "")}
                onMouseEnter={() => setSlashIdx(i)} onClick={() => acceptSlash(c)}>
                <b>/{c.name}</b><span>{c.hint}</span>
              </button>
            ))}
          </div>
        )}
        <textarea ref={taRef} className="cmp-ta" placeholder={placeholder ?? "Message…"} value={text}
          onChange={(e) => write(e.target.value)} onKeyDown={onKey} onPaste={onPaste} />
      </div>

      <div className="cmp-bar">
        <input ref={fileRef} type="file" multiple
          accept="image/*,.pdf,.txt,.md,.csv,.json,.log,.py,.ts,.tsx,.js" style={{ display: "none" }}
          onChange={(e) => addFiles(e.target.files)} />
        <button className="cmp-tool" title="Attach image or file" onClick={() => fileRef.current?.click()}>
          <IconPaperclip size={15} />
        </button>
        {!hideThinking && (
          <button className={"cmp-tool" + (thinkOn ? " on" : "")} onClick={() => {
            const i = THINK.findIndex((x) => x.id === thinking); setThinking(THINK[(i + 1) % THINK.length].id);
          }} title="Thinking level — off · think · hard · ultra">
            <IconBrain size={15} />{thinkOn && <span className="cmp-toollabel">{thinkShort}</span>}
          </button>
        )}
        {modeOptions && modeOptions.length > 1 && (
          <button className="cmp-tool" onClick={() => {
            const i = modeOptions.findIndex((m) => m.id === mode);
            setMode(modeOptions[(i + 1) % modeOptions.length].id);
          }} title="Agent mode — cycles the permission mode">
            <IconSliders size={15} /><span className="cmp-toollabel">{modeOptions.find((m) => m.id === mode)?.label}</span>
          </button>
        )}
        <select className="cmp-model" value={model} onChange={(e) => setModel(e.target.value)}
          title="Model — Auto routes by task; the rest come from the Claude manifest + your ~/.claude/settings.json">
          <option value="auto">Auto</option>
          {models.map((m) => <option key={m.id} value={m.id} title={m.desc}>{m.label}</option>)}
        </select>

        {context && context.total > 0 && (
          <span className="cmp-meter" title={`context ~${context.used.toLocaleString()} / ${context.total.toLocaleString()} tokens`}>
            <span className="cmp-meterbar"><span className="cmp-meterfill" style={{ width: pct + "%" }} /></span>
            <span className="cmp-meterpct">{pct}%</span>
          </span>
        )}

        {busy && onStop ? (
          <button className="btn cmp-send cmp-stop" onClick={onStop} title="Stop the running turn"><IconStop size={15} /></button>
        ) : (
          <button className={"btn primary cmp-send" + (sendLabel ? " cmp-send-text" : "")}
            disabled={busy} onClick={fire} title={sendLabel ?? "Send (Enter)"}>
            {busy ? <span className="cmp-spin" /> : sendLabel ? sendLabel : <IconArrowUp size={16} />}
          </button>
        )}
      </div>

      {lightbox && (
        <div className="cmp-lightbox" onClick={() => setLightbox(null)}>
          <img src={lightbox.data} alt={lightbox.name} onClick={(e) => e.stopPropagation()} />
          <button className="cmp-lbx" onClick={() => setLightbox(null)} aria-label="close"><IconX size={20} /></button>
        </div>
      )}
    </div>
  );
}
