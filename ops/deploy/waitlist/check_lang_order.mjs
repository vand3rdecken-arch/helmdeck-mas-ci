// Owner rule: on helmdeck.de app pages ENGLISH comes first, GERMAN second.
// Renders every /readproof and /label-doktor page and reports violations:
//   - a German block (h1/h2 "Deutsch", <div lang=de>, "DE:") before the English one
//   - "DE / EN" pairs in titles, nav, headings, list items, cells ("Doku / Docs")
//   - "Stand / Version" style label pairs
// Run: node check_lang_order.mjs   (exit 1 on any violation)
import { APP_PAGES } from "./src/app_pages.js";
import { LABEL_DOKTOR_PAGES } from "./src/label_doktor.js";

const DE_WORDS = /\b(und|der|die|das|nicht|für|mit|ist|sind|wer|bis|je|zu|zur|von|nach|auf|im|ein|eine|ohne|oder|wie|dein|deine|diese|dieser|Nutzer|Seite|Seiten|Zurück|Preis|Preisvergleich|Doku|Dokumentation|Datenschutz|Nutzungsbedingungen|Sicherheit|Stand|Übersicht|Kostenlose|Gratis|Danach|Monatliche|Zuweisung)\b|[äöüß]/i;
const EN_WORDS = /\b(and|the|not|for|with|is|are|who|until|per|to|of|from|after|on|in|an|a|without|or|how|your|this|users|page|pages|back|price|docs|documentation|privacy|terms|security|version|free|then|monthly|app)\b/i;
const isDe = (s) => DE_WORDS.test(s) && !EN_WORDS.test(s);
const isEn = (s) => EN_WORDS.test(s) && !DE_WORDS.test(s);

const text = (h) => h.replace(/<[^>]+>/g, " ").replace(/&[a-z]+;/g, " ").replace(/\s+/g, " ").trim();
const all = { ...APP_PAGES, ...LABEL_DOKTOR_PAGES };
const problems = [];

for (const [url, html] of Object.entries(all)) {
  if (!/^\/(readproof|label-doktor)/.test(url)) continue;
  const add = (m) => problems.push(`${url}: ${m}`);

  // block order
  const de = [html.search(/<h[12]>\s*Deutsch\b/), html.search(/<div lang=de>/), html.search(/<p><strong>DE:/)].filter((i) => i >= 0);
  const en = [html.search(/<h[12]>\s*English\b/), html.search(/<div lang=en>/), html.search(/<p><strong>EN:/)].filter((i) => i >= 0);
  if (de.length && en.length && Math.min(...de) < Math.min(...en)) add("German block before English block");

  // "A / B" pairs in the visible chunks (title, headings, li, cells, links, paragraphs)
  const chunks = [...html.matchAll(/<(title|h[1-6]|li|td|th|a|p|summary)\b[^>]*>([\s\S]*?)<\/\1>/g)].map((m) => text(m[2]));
  for (const c of chunks) {
    if (c.length > 220) continue; // long prose paragraphs hold "/" legitimately (CSV/PDF); pairs are short labels
    const parts = c.split(" / ");
    if (parts.length === 2 && isDe(parts[0]) && isEn(parts[1])) add(`DE / EN pair: "${c.slice(0, 90)}"`);
  }
  // "Stand / Version" label pair (neutral words, so listed explicitly)
  if (/Stand \/ Version/.test(html)) add('"Stand / Version" (use "Version / Stand")');
}

if (problems.length) {
  console.log(problems.join("\n"));
  console.log(`\n${problems.length} violation(s)`);
  process.exit(1);
}
console.log(`ok: ${Object.keys(all).filter((u) => /^\/(readproof|label-doktor)/.test(u)).length} urls, English first everywhere`);
