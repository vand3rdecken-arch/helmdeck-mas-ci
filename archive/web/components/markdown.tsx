"use client";
import React from "react";
import CodeBlock from "./codeblock";

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

const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

// gather a contiguous list region into flat items with indent depth
function listRegion(lines: string[], start: number) {
  const items: { indent: number; ordered: boolean; text: string }[] = [];
  let i = start;
  while (i < lines.length) {
    const m = LIST_RE.exec(lines[i]);
    if (!m) {
      if (!lines[i].trim() && i + 1 < lines.length && LIST_RE.test(lines[i + 1])) { i++; continue; }
      break;
    }
    items.push({ indent: m[1].replace(/\t/g, "  ").length, ordered: /\d/.test(m[2]), text: m[3] });
    i++;
  }
  return { items, next: i };
}

// recursive nested list (arbitrary depth) with task-list checkboxes
function renderList(items: { indent: number; ordered: boolean; text: string }[],
                   pos: { i: number }, indent: number, keyGen: () => string): React.ReactNode {
  const lis: React.ReactNode[] = [];
  let ordered = false, first = true;
  while (pos.i < items.length && items[pos.i].indent >= indent) {
    const it = items[pos.i];
    if (it.indent > indent) break;                 // belongs to a shallower call
    if (first) { ordered = it.ordered; first = false; }
    pos.i++;
    let children: React.ReactNode = null;
    if (pos.i < items.length && items[pos.i].indent > indent) {
      children = renderList(items, pos, items[pos.i].indent, keyGen);
    }
    const k = keyGen();
    const task = /^\[([ xX])\]\s+(.*)$/.exec(it.text);
    if (task) {
      lis.push(
        <li key={k} className="md-task">
          <input type="checkbox" checked={task[1].toLowerCase() === "x"} readOnly />
          <span>{inline(task[2], k)}</span>{children}
        </li>);
    } else {
      lis.push(<li key={k}>{inline(it.text, k)}{children}</li>);
    }
  }
  return ordered
    ? <ol key={keyGen()} className="md-ol">{lis}</ol>
    : <ul key={keyGen()} className="md-ul">{lis}</ul>;
}

const cells = (row: string) => row.replace(/^\s*\|?|\|?\s*$/g, "").split("|").map((c) => c.trim());

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
      blocks.push(<CodeBlock key={key()} code={buf.join("\n")} lang={lang} />);
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

    // GFM table: a header row of pipes followed by a |---|---| separator
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?[\s:-]*-[-\s:|]*\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) { rows.push(cells(lines[i])); i++; }
      blocks.push(
        <table key={key()} className="md-table">
          <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, key())}</th>)}</tr></thead>
          <tbody>{rows.map((r, ri) => (
            <tr key={ri}>{head.map((_, j) => <td key={j}>{inline(r[j] ?? "", key())}</td>)}</tr>
          ))}</tbody>
        </table>);
      continue;
    }

    // list (unordered/ordered, nested, task-list) - unified recursive parser
    if (LIST_RE.test(line)) {
      const { items, next } = listRegion(lines, i);
      blocks.push(renderList(items, { i: 0 }, items[0].indent, key));
      i = next;
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
