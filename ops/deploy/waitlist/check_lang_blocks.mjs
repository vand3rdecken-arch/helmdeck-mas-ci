// Owner rule: app pages (/readproof/*, /label-doktor/*) offer language as an
// OPTION: English by default, German via the toggle. Every text block therefore
// exists twice (class "en" and class "de", see src/app_i18n.js L() and B()).
// Checks, per page:
//   - same number of .en and .de elements, and the .de ones follow their .en ones
//   - no old double-language leftovers: "A / B" label pairs, "English"/"Deutsch"
//     headings, "EN:"/"DE:" paragraphs, "English first", #de anchors
//   - title has a German counterpart, consent banner + footer link present
//   - forbidden words and dashes (owner copy rules)
// Run: node check_lang_blocks.mjs   (exit 1 on any violation)
import { APP_PAGES } from "./src/app_pages.js";
import { LABEL_DOKTOR_PAGES } from "./src/label_doktor.js";

const all = { ...APP_PAGES, ...LABEL_DOKTOR_PAGES };
const problems = [];
let n = 0;

for (const [url, html] of Object.entries(all)) {
  if (!/^\/(readproof|label-doktor)/.test(url)) continue;
  n++;
  const add = (m) => problems.push(`${url}: ${m}`);

  const tags = [...html.matchAll(/<(span|div)\s+class=(en|de)\b/g)].map((m) => m[2]);
  const en = tags.filter((t) => t === "en").length, de = tags.length - en;
  if (en !== de) add(`${en} English blocks but ${de} German blocks`);
  // pairs must alternate en, de, en, de ... (a de before its en would be a swap)
  tags.forEach((t, i) => { if (t !== (i % 2 ? "de" : "en")) add(`block ${i} is "${t}", pairs must be en then de`); });
  if (!en) add("no language blocks at all");

  if (!/<meta name=hd-title-de content="[^"]+">/.test(html)) add("no German title");
  if (!/id=cb\b/.test(html) || !/id=cs\b/.test(html)) add("consent banner or Cookie settings link missing");
  if (!/id=cy\b/.test(html) || !/id=cn\b/.test(html)) add("Accept/Decline buttons missing");

  if (/<h[12]>\s*(English|Deutsch)\b/.test(html)) add('"English"/"Deutsch" heading');
  if (/<strong>(EN|DE):/.test(html) || /<p>(EN|DE): /.test(html)) add("EN:/DE: paragraph");
  if (/English first|deutsch darunter|href="#de"|id=de\b/.test(html)) add("old two-text-on-one-page marker");

  // visible text outside the language blocks must be language-neutral: look for "A / B" label pairs
  const vis = html.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, "").replace(/<[^>]+>/g, " ").replace(/&[a-z]+;/g, " ");
  for (const m of vis.matchAll(/\b[\wÄÖÜäöüß]+ \/ [\wÄÖÜäöüß]+\b/g)) {
    if (/^(CSV|PDF|read|and|or|Read|Jira|Confluence|Contact)/.test(m[0]) || /\b(CSV|PDF)\b/.test(m[0])) continue;
    add(`possible "A / B" language pair: "${m[0]}"`);
  }

  // only a disclaimer may use these words ("does not prove compliance", "not a guaranteed ...")
  for (const m of html.replace(/<script[\s\S]*?<\/script>/g, "").matchAll(/(.{0,40})\b(compliant|compliance|certified|guarantee)/gi))
    if (!/\b(not|no|nor|nicht|kein)\b/i.test(m[1])) add(`forbidden word: "${m[0].slice(-50)}"`);
  if (/[–—]/.test(html)) add("dash character");
}

if (problems.length) {
  console.log(problems.join("\n"));
  console.log(`\n${problems.length} violation(s)`);
  process.exit(1);
}
console.log(`ok: ${n} urls, every block in both languages`);
