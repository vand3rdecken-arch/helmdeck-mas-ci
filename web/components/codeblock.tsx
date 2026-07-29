"use client";
import React, { useState } from "react";
import { IconCopy, IconCheck } from "./icons";

// Dependency-free code block with a language label, a copy button, and light
// token highlighting (strings / comments / numbers / keywords). Not a full
// grammar - just enough colour to read agent code the way Paseo does, without
// pulling in a highlighter dependency.
const KEYWORDS = new Set(
  ("const let var function return if else for while do switch case break continue new class " +
   "extends implements import from export default async await yield try catch finally throw " +
   "typeof instanceof void delete this super null true false undefined def elif lambda pass with " +
   "as True False None and or not is self print del global nonlocal raise except in of fn pub use " +
   "struct enum impl match where type interface public private protected static final abstract " +
   "echo local then fi done esac unset readonly package func go defer chan map range select").split(" "),
);
// langs where `#` starts a line comment (not JS/TS/C)
const HASH_COMMENT = /^(py|python|rb|ruby|sh|bash|zsh|yaml|yml|toml|ini|conf|makefile|make|dockerfile|r|pl)$/i;

function highlight(code: string, lang: string): React.ReactNode[] {
  const hash = !lang || HASH_COMMENT.test(lang);
  const src = hash
    ? /(\/\/[^\n]*|#[^\n]*)|(\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_.eExXbBoOaAfF]*\b)|([A-Za-z_$][A-Za-z0-9_$]*)/g
    : /(\/\/[^\n]*)|(\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_.eExXbBoOaAfF]*\b)|([A-Za-z_$][A-Za-z0-9_$]*)/g;
  const out: React.ReactNode[] = [];
  let last = 0, i = 0, m: RegExpExecArray | null;
  while ((m = src.exec(code))) {
    if (m.index > last) out.push(code.slice(last, m.index));
    const t = m[0], k = "t" + i++;
    if (m[1] || m[2]) out.push(<span key={k} className="hl-c">{t}</span>);
    else if (m[3]) out.push(<span key={k} className="hl-s">{t}</span>);
    else if (m[4]) out.push(<span key={k} className="hl-n">{t}</span>);
    else if (m[5] && KEYWORDS.has(t)) out.push(<span key={k} className="hl-k">{t}</span>);
    else out.push(t);
    last = m.index + t.length;
  }
  if (last < code.length) out.push(code.slice(last));
  return out;
}

export default function CodeBlock({ code, lang = "" }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  function doCopy() {
    try {
      navigator.clipboard.writeText(code);
      setCopied(true); setTimeout(() => setCopied(false), 1400);
    } catch { /* ignore */ }
  }
  return (
    <div className="cbx">
      <div className="cbx-head">
        <span className="cbx-lang">{lang || "code"}</span>
        <button className="cbx-copy" title="Copy code" onClick={doCopy}>
          {copied ? <IconCheck size={12} /> : <IconCopy size={12} />}{copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="md-cb"><code>{highlight(code, lang)}</code></pre>
    </div>
  );
}
