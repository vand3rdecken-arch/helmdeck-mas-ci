// X post scanner: find recent posts on x.com worth a HelmDeck-relevant reply.
// Uses jev-browser (headed, persistent profile - x.com serves headless Chromium a blank page)
// to search + scroll, then scores each collected post with one Jev yes/no call against fixed
// criteria. Never posts anything. Reply drafts are written by hand afterwards, not by this script
// (Jev never generates text - see jev-browser/README.md).
//
//   node ops/tools/x_scan_jev.mjs [--queries "a,b,c"] [--hours 24] [--threshold 0.7]
//                                 [--per-query 40] [--max-scrolls 20] [--out FILE]
//
// First run needs a human login in the persistent profile (JEV_BROWSER_PROFILE, default
// %LOCALAPPDATA%/HelmDeck/jev-x-profile) - the script detects a login wall and stops rather than
// guessing around it.
import { writeFileSync, mkdirSync, existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../..");
const TYPESAFE_RATE_PER_MTOK = 0.042; // ops/docs/marketing/jev-hands-benchmark-2026-09.md

// The npx-installed jev-browser location isn't a repo dependency; JEV_PKG lets a caller point at
// a different install, same convention as ops/docs/marketing/jev-bench/bench4.mjs.
const JEV_PKG = process.env.JEV_PKG ||
  resolve(process.env.LOCALAPPDATA || "", "npm-cache/_npx/d8a6e8a3d42c3aa7/node_modules/jev-browser");

let JevBrowser, jev;
try {
  ({ JevBrowser, jev } = await import("jev-browser"));
} catch {
  ({ JevBrowser, jev } = await import(pathToFileURL(resolve(JEV_PKG, "src/index.mjs")).href));
}

const DEFAULT_QUERIES = [
  "Claude Code team",
  "agent orchestration",
  "parallel coding agents",
  "agents kanban",
  "approve agent from phone",
  "multiple Claude Code sessions",
  "agent harness",
];

const argv = process.argv.slice(2);
const opt = (k, d) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : d);
const has = k => argv.includes(k);
const queries = (opt("--queries", "") || "").split(",").map(s => s.trim()).filter(Boolean);
const QUERIES = queries.length ? queries : DEFAULT_QUERIES;
const HOURS = +opt("--hours", 24);
const THRESHOLD = +opt("--threshold", 0.7);
const PER_QUERY = +opt("--per-query", 40);
const MAX_SCROLLS = +opt("--max-scrolls", 20);
const MIN_LIKES = +opt("--min-likes", 5);
const MIN_REPLIES = +opt("--min-replies", 2);
const OUT = resolve(REPO, opt("--out", "ops/docs/marketing/jev-bench/x-scan-2026-09-19-raw.json"));
const PROFILE = process.env.JEV_BROWSER_PROFILE ||
  resolve(process.env.LOCALAPPDATA || REPO, "HelmDeck/jev-x-profile");
const HEADED = !has("--headless"); // x.com blanks out under headless Chromium; headed is the default and the point

const sleep = ms => new Promise(r => setTimeout(r, ms));

const CRITERIA = [
  "(a) it describes the problem of coordinating, reviewing, approving or budgeting several coding agents / AI coding agents at once, or running more than one coding-agent session in parallel",
  "(b) it asks for tools, workflow ideas or recommendations for that problem",
  "(c) it is not itself an advertisement, product-launch/promo post, or bot-looking spam post",
].join("; ");

async function scorePost(post) {
  const state = { post: { text: post.text, author: post.author, likes: post.likes, replies: post.replies } };
  const { answers, tokens } = await jev(state, {
    q: {
      type: "noul",
      instructions: `Look at \`post.text\` (an X/Twitter post). Score how well it matches ALL of: ${CRITERIA}. ` +
        "Answer yes only if it genuinely describes or asks about coordinating/reviewing/approving/budgeting multiple coding agents, and is not an ad or bot post.",
    },
  });
  return { score: answers.q.noul, tokens };
}

function searchUrl(query) {
  return `https://x.com/search?q=${encodeURIComponent(query)}&src=typed_query&f=live`;
}

async function extractPosts(page) {
  return page.evaluate(() => {
    const num = label => {
      const m = String(label || "").match(/([\d.,]+)\s*([KkMm]?)/);
      if (!m) return 0;
      let n = parseFloat(m[1].replace(/,/g, ""));
      if (/k/i.test(m[2])) n *= 1000;
      if (/m/i.test(m[2])) n *= 1_000_000;
      return Math.round(n) || 0;
    };
    const count = (art, testid) => {
      const el = art.querySelector(`[data-testid="${testid}"]`);
      return el ? num(el.getAttribute("aria-label") || el.textContent) : 0;
    };
    return [...document.querySelectorAll('article[data-testid="tweet"]')].map(art => {
      const textEl = art.querySelector('[data-testid="tweetText"]');
      const timeEl = art.querySelector("time");
      const link = timeEl ? timeEl.closest("a") : null;
      const nameBlock = art.querySelector('[data-testid="User-Name"]');
      const spans = nameBlock ? [...nameBlock.querySelectorAll("span")] : [];
      const handleSpan = spans.find(s => /^@/.test((s.textContent || "").trim()));
      return {
        text: textEl ? textEl.innerText : "",
        url: link ? new URL(link.getAttribute("href"), location.origin).href : null,
        datetime: timeEl ? timeEl.getAttribute("datetime") : null,
        author: handleSpan ? handleSpan.textContent.trim() : null,
        displayName: spans[0] ? spans[0].textContent.trim() : null,
        replies: count(art, "reply"),
        likes: count(art, "like"),
        isAd: !!art.querySelector('[data-testid="promotedIndicator"]'),
      };
    }).filter(p => p.url && p.text);
  });
}

async function isBlockedOrLoggedOut(b) {
  const p_login = await b.check("Is this page an X/Twitter login wall, 'sign in to see more' prompt, CAPTCHA, rate-limit notice, or an error page instead of real search results?");
  return p_login;
}

async function main() {
  mkdirSync(dirname(OUT), { recursive: true });
  mkdirSync(PROFILE, { recursive: true });
  console.log(`profile: ${PROFILE}`);
  console.log(`queries: ${JSON.stringify(QUERIES)}`);

  const b = await JevBrowser.launch({ headed: HEADED, userDataDir: PROFILE, slowMo: 60, viewport: { width: 1280, height: 900 } });
  let jevCalls = 0, jevTokens = 0;
  const scoreWrap = async post => {
    const r = await scorePost(post);
    jevCalls++; jevTokens += r.tokens || 0;
    return r.score;
  };

  const cutoff = Date.now() - HOURS * 3600_000;
  const seen = new Map(); // url -> post record (dedup across queries)
  let blockedReport = null;

  try {
    // Gate: confirm the profile is actually logged in before spending any query on it.
    await b.open("https://x.com/home");
    const homeBlocked = await isBlockedOrLoggedOut(b);
    if (homeBlocked > 0.5) {
      const keepOpen = +opt("--keep-open-minutes", 0);
      if (keepOpen <= 0) {
        blockedReport = { stage: "login-check", p_blocked: homeBlocked, url: b.page.url() };
        console.log("LOGIN WALL DETECTED - profile is not logged in. Stopping, not guessing a workaround.");
        return;
      }
      console.log(`LOGIN WALL DETECTED - polling for up to ${keepOpen} min while the owner logs in by hand (window stays open, do not close it).`);
      await b.page.goto("https://x.com/login", { waitUntil: "commit" }).catch(() => {});
      const deadline = Date.now() + keepOpen * 60_000;
      let loggedIn = false;
      while (Date.now() < deadline) {
        await sleep(15_000);
        const stillBlocked = await isBlockedOrLoggedOut(b);
        if (stillBlocked <= 0.5) { loggedIn = true; break; }
      }
      if (!loggedIn) {
        blockedReport = { stage: "login-check", p_blocked: 1, url: b.page.url(), note: `still not logged in after ${keepOpen} min` };
        console.log("still not logged in after the wait - stopping, not guessing a workaround.");
        return;
      }
      console.log("login detected, proceeding to search.");
    } else {
      console.log("login check passed, proceeding to search.");
    }
    if (has("--login-check-only")) { console.log("--login-check-only: stopping here as requested."); return; }

    for (const query of QUERIES) {
      console.log(`\n=== query: ${query} ===`);
      await b.open(searchUrl(query));
      await sleep(800);
      const blocked = await isBlockedOrLoggedOut(b);
      if (blocked > 0.5) {
        blockedReport = { stage: "search", query, p_blocked: blocked, url: b.page.url() };
        console.log(`BLOCKED on query "${query}" - stopping.`);
        break;
      }

      let collectedForQuery = 0, stagnant = 0, lastCount = 0;
      for (let s = 0; s < MAX_SCROLLS && collectedForQuery < PER_QUERY; s++) {
        const posts = await extractPosts(b.page);
        for (const post of posts) {
          if (seen.has(post.url)) continue;
          const ageMs = post.datetime ? Date.now() - new Date(post.datetime).getTime() : null;
          if (ageMs === null || ageMs > HOURS * 3600_000) continue; // outside the recency window
          if (post.isAd) continue;
          seen.set(post.url, { ...post, query, ageMs });
          collectedForQuery++;
        }
        if (seen.size === lastCount) stagnant++; else stagnant = 0;
        lastCount = seen.size;
        if (stagnant >= 3) { console.log("  no new posts after 3 scrolls, moving on"); break; }
        await b.actOn({ action: "scroll" });
        await sleep(500);
      }
      console.log(`  collected ${collectedForQuery} new posts (window <= ${HOURS}h)`);
    }
  } finally {
    await b.close().catch(() => {});
  }

  if (blockedReport) {
    writeFileSync(OUT, JSON.stringify({ blocked: blockedReport, jev_calls: jevCalls, jev_cost_usd: 0 }, null, 2));
    console.log(`\nBLOCKED: ${JSON.stringify(blockedReport)}`);
    console.log(`raw report written to ${OUT}`);
    process.exitCode = 2;
    return;
  }

  const candidates = [...seen.values()];
  console.log(`\ntotal unique candidates in window: ${candidates.length}`);
  console.log("scoring with Jev...");
  const scored = [];
  for (const post of candidates) {
    const score = await scoreWrap(post);
    scored.push({ ...post, score });
  }

  const hits = scored
    .filter(p => p.score >= THRESHOLD && (p.likes >= MIN_LIKES || p.replies >= MIN_REPLIES))
    .sort((a, b2) => b2.score - a.score || (b2.likes + b2.replies) - (a.likes + a.replies));

  const jevCostUsd = +(jevTokens / 1e6 * TYPESAFE_RATE_PER_MTOK).toFixed(6);
  const result = {
    ran_at: new Date().toISOString(),
    queries: QUERIES,
    hours: HOURS,
    threshold: THRESHOLD,
    min_likes: MIN_LIKES,
    min_replies: MIN_REPLIES,
    candidates_scanned: candidates.length,
    hits_count: hits.length,
    jev_calls: jevCalls,
    jev_tokens: jevTokens,
    jev_cost_usd: jevCostUsd,
    hits,
    all_scored: scored,
  };
  writeFileSync(OUT, JSON.stringify(result, null, 2));
  console.log(`\n${hits.length} hits (score >= ${THRESHOLD}, likes >= ${MIN_LIKES} or replies >= ${MIN_REPLIES}) out of ${candidates.length} scanned`);
  console.log(`Jev: ${jevCalls} calls, ${jevTokens} tokens, $${jevCostUsd}`);
  console.log(`raw data written to ${OUT}`);
}

await main();
