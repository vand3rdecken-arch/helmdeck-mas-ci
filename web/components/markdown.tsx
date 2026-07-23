"use client";
import React from "react";

// Markdown -> React for the chat, no dependency. Covers exactly what a coding
// agent emits (the same element set Paseo's markdown styles cover): fenced code
// blocks, inline code, bold, italic, strikethrough, headings, bullet & ordered
// lists, blockquotes, horizontal rules, links, paragraphs and line breaks.

// a FRESH regex per call - inline() recurses (bold/em), so a shared /g regex
// would have its lastIndex clobbered by the inner call and hang the outer loop.
const INLINE_SRC = "(`[^`]+`)|(\\*\\*[^*]+\\*\\*)|(__[^_]+__)|(\\*[^*\\n]+\\*)|((?<![A-Za-z0-9])_[^_\\n]+_(?![A-Za-z0-9]))|(~~[^~]+~~)|(\\[[^\\]]+\\]\\([^)]+\\))|(https?:\\/\\/[^\\s)]+)";

function inline(text: string, kp: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = new RegExp(INLINE_SRC, "g");
  let last = 0, i = 0, m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0], k = kp + "i" + i++;
    if (t.startsWith("`")) out.push(<code key={k} className="md-ic">{t.slice(1, -1)}</code>);
    else if (t.startsWith("**") || t.startsWith("__")) out.push(<strong key={k}>{inline(t.slice(2, -2), k)}</strong>);
    else if (t.startsWith("~~")) out.push(<s key={k}>{t.slice(2, -2)}</s>);
    else if (t.startsWith("[")) {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(t)!;
      out.push(<a key={k} href={mm[2]} target="_blank" rel="noreferrer">{mm[1]}</a>);
    } else if (t.startsWith("http")) {
      out.push(<a key={k} href={t} target="_blank" rel="noreferrer">{t}</a>);
    } else out.push(<em key={k}>{inline(t.slice(1, -1), k)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function parse(src: string): React.ReactNode[] {
  const lines = (src || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0, b = 0;
  const key = () => "b" + b++;

  while (i < lines.length) {
    const line = lines[i];

    // fenced code block
    const fence = /^\s*```(\w+)?\s*$/.exec(line);
    if (fence) {
      const lang = fence[1] || "";
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
      i++; // closing fence
      blocks.push(
        <pre key={key()} className="md-cb"><code data-lang={lang}>{buf.join("\n")}</code></pre>,
      );
      continue;
    }

    // blank line
    if (!line.trim()) { i++; continue; }

    // heading
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const lvl = Math.min(h[1].length, 6);
      const Tag = ("h" + Math.min(lvl + 1, 6)) as keyof React.JSX.IntrinsicElements; // shift so h1 isn't huge in chat
      blocks.push(<Tag key={key()}>{inline(h[2], key())}</Tag>);
      i++; continue;
    }

    // horizontal rule
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { blocks.push(<hr key={key()} className="md-hr" />); i++; continue; }

    // blockquote
    if (/^\s*>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push(<blockquote key={key()}>{inline(buf.join(" "), key())}</blockquote>);
      continue;
    }

    // unordered list
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        const item = lines[i].replace(/^\s*[-*+]\s+/, "");
        items.push(<li key={key()}>{inline(item, key())}</li>); i++;
      }
      blocks.push(<ul key={key()} className="md-ul">{items}</ul>);
      continue;
    }

    // ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: React.ReactNode[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        const item = lines[i].replace(/^\s*\d+\.\s+/, "");
        items.push(<li key={key()}>{inline(item, key())}</li>); i++;
      }
      blocks.push(<ol key={key()} className="md-ol">{items}</ol>);
      continue;
    }

    // paragraph: gather consecutive plain lines
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|>\s?|[-*+]\s|\d+\.\s|-{3,}\s*$|\*{3,}\s*$)/.test(lines[i])) {
      buf.push(lines[i++]);
    }
    const k = key();
    blocks.push(
      <p key={k}>{buf.map((ln, j) => (
        <React.Fragment key={k + "l" + j}>{j > 0 && <br />}{inline(ln, k + "l" + j)}</React.Fragment>
      ))}</p>,
    );
  }
  return blocks;
}

export default function Markdown({ children }: { children: string }) {
  return <div className="md">{parse(children)}</div>;
}
