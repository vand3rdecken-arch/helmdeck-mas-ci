/**
 * HelmDeck landing worker (M4 public-launch).
 *
 * Routes
 *   GET  /            landing page: hero, downloads (live GitHub release assets),
 *                      Watch/Glasses waitlist (DE default, EN toggle; no-JS fallback via query params)
 *   POST /api/join    store an address in KV (idempotent per email)
 *   GET  /export.csv  owner-only CSV export (?token=... or Bearer, secret EXPORT_TOKEN)
 *   GET  /icon.svg    brand mark (also used as favicon)
 *   GET  /health      liveness probe
 *
 * Storage: Workers KV, key `email:<lowercased>`, value JSON {email, ts, lang, product},
 * same {ts, lang, product} duplicated into KV metadata so the CSV export needs only
 * list() calls (no N single reads). First signup wins; re-joining never
 * overwrites the original timestamp. No IP / UA stored (data minimization).
 * `product` is "wearables" for every signup collected through this page - the
 * app itself is downloadable directly now (see the downloads section), so the
 * waitlist's only remaining purpose is the not-yet-shipped Watch/Glasses line.
 * Addresses can later be pushed into a Loops segment once that integration
 * exists; the CSV is the neutral interchange format until then.
 *
 * The download buttons read the latest GitHub release live (cached in the same
 * KV namespace for an hour) instead of hardcoding filenames, so this page never
 * goes stale when a new version ships. If the GitHub fetch fails, every button
 * falls back to the releases page itself rather than a dead link.
 *
 * iOS is the one platform with no downloadable artifact: it ships as an internal
 * TestFlight group, which Apple distributes by invitation only (no public join
 * URL exists to link). Its card therefore offers a mailto that asks for the
 * tester's Apple ID - see TESTFLIGHT_REQUEST_URL.
 */

import { ICON_SVG } from "./logo.js";

const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@.]{2,24}$/;

// Owner-picked Userjot board (matches surfaces/app/src/data/feedback.ts) - update both
// in lockstep if the board URL ever changes.
//
// Was "" (footer link hidden) from 2026-08-15 20:00-20:47: every path on
// helmdeck.userjot.com answered HTTP 500, verified in real Chromium, not just
// curl. Root cause found by grepping every card's session log for "userjot":
// the board was never actually created. A prior card GUESSED this subdomain,
// couldn't verify it (mis-read UserJot's 500-for-non-browser-clients as normal
// behavior, when it was 500-for-everyone), and the owner's "yes, correct" only
// confirmed the guessed spelling, not that the board existed. Restored 20:47
// after the owner created the workspace at this exact subdomain - confirmed
// both by UserJot's own "Your HelmDeck board is live" and by loading the page
// itself (real content, not the JSON error).
const FEEDBACK_URL = "https://helmdeck.userjot.com";
// The PUBLIC binaries repo. The 2026-08-26 repo split made Tienduyvo/helmdeck
// private; this worker calls the GitHub API unauthenticated, so pointing here at
// the private repo 404s -> fetchLatestRelease throws -> every download button
// silently falls back to RELEASES_URL (itself a 404 for visitors) and every
// version label renders empty. Measured live 2026-09-02, not reasoned.
const REPO = "Tienduyvo/helmdeck-release";
const RELEASES_URL = `https://github.com/${REPO}/releases/latest`;
// Android is PUBLIC on Google Play since the 31.08.2026 release, so the button
// must point at the live store listing, not at the closed-test opt-in page
// (/apps/testing/... only ever worked for members of the helmdeck-testers group
// and is a dead end for everyone else). Measured live 2026-09-02: the details
// page returns 200 with a real "Installieren" button, developer projectkaiser,
// no early-access badge - i.e. production, not a track.
const PLAY_URL = "https://play.google.com/store/apps/details?id=app.helmdeck";
const OWNER_EMAIL = "tienduyvo@googlemail.com";
// iOS: moving from INTERNAL to EXTERNAL TestFlight (owner decision 2026-09-02),
// which is what finally produces a public join URL - external group "Public Beta"
// (ASC app 6801637667) exists, the build still has to clear Apple Beta App Review.
// Until that link is live this card is INTERIM.
//
// What it is fixing, measured in real Chromium on 2026-09-02, not reasoned:
// the primary button used to be a bare mailto: and clicking it produced
// `navigated away? False | new tabs opened: 0` - i.e. literally nothing for any
// visitor without an OS-registered mail handler, which includes every webmail
// user. A working address you can COPY beats a prettier link that no-ops, so the
// address is now visible text plus a clipboard button; the mailto survives only
// as an enhancement for people who do have a handler.
const TESTFLIGHT_REQUEST_URL =
  "mailto:" + OWNER_EMAIL +
  "?subject=" + encodeURIComponent("HelmDeck iOS – TestFlight-Zugang") +
  "&body=" + encodeURIComponent(
    "Hi, ich möchte die HelmDeck-Beta auf dem iPhone testen.\n\n" +
    "Apple-ID (E-Mail) für die TestFlight-Einladung: \n"
  );
// Storefront segment is deliberate: without "/de/" Apple redirects a German
// visitor through the US storefront, and one of those redirects served a blank
// "An Error Occurred" page in a real browser on 2026-09-02 (title "App Store",
// 401 chars, no app content). The error itself is intermittent Apple-side, but
// the extra hop is not - naming the storefront removes it.
const TESTFLIGHT_APP_URL = "https://apps.apple.com/de/app/testflight/id899247664";
const RELEASE_CACHE_KEY = "_cache:latest-release";
const RELEASE_CACHE_TTL = 3600;

// The brand mark is NOT written here. It is generated from the same mask every
// other surface's icon comes from (ops/tools/assets/logo_h_mask.png) by
// `py -3.12 ops/tools/make_icon.py`. The previous hand-written copy of the mark
// silently survived the 2026-08-26 logo redesign and helmdeck.de served the
// superseded design until 2026-09-02. Do not inline a mark here again.

// --- live release lookup -----------------------------------------------

function matchVersion(asset, re) {
  if (!asset) return "";
  const m = (asset.name && asset.name.match(re)) || (asset.label && asset.label.match(re));
  return m ? m[1] : "";
}

function entryFrom(asset, re) {
  if (!asset) return null;
  return {
    url: asset.browser_download_url,
    version: matchVersion(asset, re),
    sizeMb: Math.round(asset.size / 1e6),
  };
}

async function fetchLatestRelease() {
  const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
    headers: { "user-agent": "helmdeck-landing-worker", accept: "application/vnd.github+json" },
  });
  if (!r.ok) throw new Error("github " + r.status);
  const data = await r.json();
  const assets = data.assets || [];
  const byNewest = (a, b) => new Date(b.created_at) - new Date(a.created_at);
  const pick = (test) => assets.filter(test).sort(byNewest)[0] || null;
  const win = pick((a) => a.content_type === "application/x-msdownload" && /\.exe$/i.test(a.name));
  const macArm = pick((a) => a.content_type === "application/x-apple-diskimage" && /arm64/i.test(a.name));
  const macX64 = pick((a) => a.content_type === "application/x-apple-diskimage" && /x64/i.test(a.name));
  const apk = pick((a) => a.content_type === "application/vnd.android.package-archive");
  return {
    ok: true,
    windows: entryFrom(win, /HelmDeck-Setup-(.+)-x64\.exe$/),
    macArm: entryFrom(macArm, /HelmDeck-(.+)-arm64\.dmg$/),
    macX64: entryFrom(macX64, /HelmDeck-(.+)-x64\.dmg$/),
    android: entryFrom(apk, /HelmDeck-(.+)\.apk$/),
  };
}

async function getReleaseAssets(env) {
  try {
    const cached = await env.WAITLIST.get(RELEASE_CACHE_KEY, "json");
    if (cached) return cached;
  } catch (e) {
    // KV read failure -> fall through to a live fetch
  }
  try {
    const result = await fetchLatestRelease();
    try {
      await env.WAITLIST.put(RELEASE_CACHE_KEY, JSON.stringify(result), {
        expirationTtl: RELEASE_CACHE_TTL,
      });
    } catch (e) {
      // best-effort cache; a write failure just means we fetch again next time
    }
    return result;
  } catch (e) {
    return { ok: false };
  }
}

function dlHref(entry) {
  return entry ? entry.url : RELEASES_URL;
}
function dlMeta(entry) {
  return entry ? `v${entry.version} · ${entry.sizeMb} MB` : "";
}

// --- page -----------------------------------------------------------------

function page({ rel, joined, already, err, email }) {
  const showSuccess = joined || already;
  const safeEmail = escapeHtml(email || "");
  const win = rel.ok ? rel.windows : null;
  const macArm = rel.ok ? rel.macArm : null;
  const macX64 = rel.ok ? rel.macX64 : null;
  const android = rel.ok ? rel.android : null;
  return `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HelmDeck – Downloads für Windows, macOS, iOS & Android</title>
<meta name="description" content="HelmDeck orchestriert Coding-Agenten auf deinem eigenen Rechner. Jetzt verfügbar für Windows, macOS (signiert &amp; notarisiert), iPhone (TestFlight) und Android – plus die Warteliste für HelmDeck Watch &amp; Glasses.">
<meta property="og:title" content="HelmDeck – jetzt verfügbar">
<meta property="og:description" content="Übernimm das Steuer deiner Agenten. Downloads für Windows, macOS, iPhone (TestFlight) und Android.">
<meta name="theme-color" content="#0E0F10">
<link rel="icon" type="image/svg+xml" href="/icon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:ital,wght@0,400..900;1,400..900&display=swap" rel="stylesheet">
<style>
:root{
  --canvas:#0E0F10; --surface:#141515; --layer:#1D1F20;
  --border:#222425; --border-strong:#36393A;
  --ink:#E4E6E6; --ink-2:#CACDCE; --ink-3:#AFB3B6; --ph:#959A9D;
  --accent:#2396E5; --accent-hi:#6CB2EC; --violet:#967AF0;
  --ok:#5CB572; --danger:#EA6A66;
}
*{box-sizing:border-box}
[hidden]{display:none !important}
html,body{margin:0}
body{
  min-height:100svh; display:flex; flex-direction:column;
  background:var(--canvas); color:var(--ink);
  font:16px/1.6 "Schibsted Grotesk",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;
}
/* the app's own aurora backdrop: teal top-left, violet top-right */
body::before{
  content:""; position:fixed; inset:0; z-index:-1; pointer-events:none;
  background:
    radial-gradient(46rem 30rem at 12% -8%, rgba(40,147,204,.16), transparent 70%),
    radial-gradient(40rem 26rem at 92% -6%, rgba(150,122,240,.13), transparent 70%);
}
a{color:inherit}
.topbar-fixed{
  position:sticky; top:0; z-index:3; background:rgba(14,15,16,.86);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--border);
}
.topbar{
  display:flex; align-items:center;
  justify-content:space-between; gap:1rem; width:100%; max-width:64rem;
  margin:0 auto; padding:1.1rem 1.25rem;
}
.lockup{display:flex; align-items:center; gap:.6rem}
.lockup svg{width:2rem; height:2rem; display:block}
.lockup b{font-size:1rem; font-weight:700; letter-spacing:.01em}
.topnav{display:flex; align-items:center; gap:1.6rem}
.topnav a{font-size:.88rem; font-weight:600; color:var(--ink-3); text-decoration:none}
.topnav a:hover{color:var(--ink)}
.lang{
  height:2rem; padding:0 .7rem; border-radius:999px; flex:none;
  background:transparent; border:1px solid var(--border-strong);
  color:var(--ink-3); font:inherit; font-size:.78rem; font-weight:600; cursor:pointer;
}
.lang:hover{background:var(--layer); color:var(--ink-2)}
main{width:100%; max-width:64rem; margin:0 auto; padding:0 1.25rem 3rem; flex:1}
h1{
  margin:0 0 .9rem; font-size:clamp(2rem,5.5vw,3.1rem); line-height:1.12;
  font-weight:800; letter-spacing:-.02em; text-wrap:balance; max-width:36rem;
}
h2{margin:0; font-size:1.55rem; font-weight:800; letter-spacing:-.01em}
h3{margin:0; font-size:1.08rem; font-weight:700}
.hero{padding:2.6rem 0 2.4rem}
.hero .sub{margin:0 0 1.8rem; font-size:1.04rem; color:var(--ink-2); max-width:40rem; text-wrap:pretty}
.hero-actions{display:flex; gap:.8rem; flex-wrap:wrap}
.btn{
  display:inline-flex; align-items:center; justify-content:center; height:3rem;
  padding:0 1.35rem; border-radius:10px; font-weight:700; font-size:.94rem;
  /* <button> does not inherit the page font by default - without this the iOS
     copy button and the waitlist submit render in the UA's system font while the
     <a class="btn"> next to them render in Schibsted Grotesk. */
  font-family:inherit;
  text-decoration:none; border:0; cursor:pointer; transition:background .15s, border-color .15s, transform .1s;
}
.btn:active{transform:translateY(1px)}
.btn-primary{background:var(--accent); color:#0A1620}
.btn-primary:hover{background:var(--accent-hi)}
.btn-ghost{background:transparent; border:1px solid var(--border-strong); color:var(--ink-2)}
.btn-ghost:hover{border-color:var(--accent); color:var(--ink)}
.btn-block{width:100%}
.btn-sm{height:2.5rem; padding:0 1.05rem; font-size:.87rem}
section{padding:2.6rem 0; border-top:1px solid var(--border)}
.section-sub{margin:.4rem 0 1.8rem; color:var(--ink-3); max-width:44rem}
.features{display:grid; grid-template-columns:repeat(auto-fit,minmax(15rem,1fr)); gap:1.1rem}
.features p{margin:0; color:var(--ink-2); font-size:.95rem; line-height:1.55}
/* four platforms: an auto-fit track would fit 3 across in the 64rem shell and
   leave the fourth card orphaned on its own row, so pin it to an even 2x2. */
.dl-grid{display:grid; grid-template-columns:1fr; gap:1rem}
@media (min-width:46rem){.dl-grid{grid-template-columns:repeat(2,1fr)}}
.dl-card{
  background:var(--surface); border:1px solid var(--border); border-radius:14px;
  padding:1.4rem; display:flex; flex-direction:column; gap:.7rem;
}
.dl-meta{margin:0; font-size:.8rem; color:var(--ink-3)}
.dl-note{margin:0; font-size:.79rem; color:var(--ink-3); line-height:1.5}
/* The iOS note carries the contact address people are meant to READ OFF and
   retype, so it gets more contrast than the surrounding note text and keeps its
   underline (a{color:inherit} would otherwise sink it into the paragraph). */
.dl-note a{color:var(--ink-2); text-decoration:underline; text-underline-offset:2px}
.dl-note a:hover{color:var(--accent)}
.dl-actions{display:flex; flex-direction:column; gap:.5rem; margin-top:auto}
.dl-all{margin:1.6rem 0 0; text-align:center; font-size:.88rem}
.dl-all a{color:var(--accent-hi); text-decoration:none}
.dl-all a:hover{text-decoration:underline}
.waitlist .wl-inner{max-width:31rem}
form{display:flex; gap:.6rem; flex-wrap:wrap}
.field{flex:1 1 14rem; position:relative}
input[type=email]{
  width:100%; height:3rem; padding:0 .95rem; border-radius:10px;
  background:var(--layer); border:1px solid var(--border-strong);
  color:var(--ink); font:inherit; font-size:.95rem; outline:none;
  transition:border-color .15s, box-shadow .15s;
}
input[type=email]::placeholder{color:var(--ph)}
input[type=email]:focus{border-color:var(--accent); box-shadow:0 0 0 3px rgba(35,150,229,.28)}
form.invalid input[type=email]{border-color:var(--danger)}
form.invalid input[type=email]:focus{box-shadow:0 0 0 3px rgba(234,106,102,.25)}
button:disabled{opacity:.6; cursor:default; transform:none}
.err{min-height:1.4rem; margin:.45rem 0 0; font-size:.83rem; color:var(--danger)}
.consent{margin:1.1rem 0 0; font-size:.82rem; line-height:1.55; color:var(--ink-3); max-width:56ch}
.hp{position:absolute; left:-5000px; top:0; width:1px; height:1px; opacity:0}
.success{
  background:var(--surface); border:1px solid var(--border); border-radius:12px;
  padding:1.35rem 1.4rem; display:flex; gap:.9rem; align-items:flex-start;
}
.success svg{flex:none; width:1.7rem; height:1.7rem; margin-top:.1rem}
.success h2{margin:0 0 .25rem; font-size:1.05rem; font-weight:700}
.success p{margin:0; font-size:.9rem; color:var(--ink-2); overflow-wrap:anywhere}
details{margin-top:1.6rem; border-top:1px solid var(--border); padding-top:1rem}
summary{
  cursor:pointer; font-size:.85rem; color:var(--ink-3); list-style:none;
  display:flex; align-items:center; gap:.45rem;
}
summary::-webkit-details-marker{display:none}
summary::before{content:"+"; color:var(--accent-hi); font-weight:700; width:.9rem}
details[open] summary::before{content:"–"}
details div{font-size:.83rem; line-height:1.6; color:var(--ink-3); padding:.6rem 0 0 1.35rem; max-width:58ch}
details a, .consent a{color:var(--accent-hi); text-decoration:none}
details a:hover{text-decoration:underline}
footer{
  padding:1.4rem 1.25rem 1.6rem; text-align:center;
  font-size:.8rem; color:var(--ph);
}
footer a{color:var(--ink-3); text-decoration:none}
footer a:hover{color:var(--ink-2)}
@keyframes rise{from{opacity:0; transform:translateY(10px)}}
.hero h1,.hero .sub,.hero-actions{animation:rise .5s cubic-bezier(.22,1,.36,1) both}
.hero .sub{animation-delay:.06s}.hero-actions{animation-delay:.12s}
@media (prefers-reduced-motion:reduce){.hero h1,.hero .sub,.hero-actions{animation:none}}
@media (max-width:640px){.topbar{flex-wrap:wrap}.topnav{order:3; width:100%; justify-content:center}}
@media (max-width:480px){form button,form .btn{flex:1 1 100%}}
</style>
</head>
<body>
<div class="topbar-fixed">
  <div class="topbar">
    <div class="lockup">${ICON_SVG}<b>HelmDeck</b></div>
    <div class="topnav">
      <a href="#downloads" data-i="navDownloads">Downloads</a>
      <a href="#waitlist" data-i="navWaitlist">Watch &amp; Glasses</a>
    </div>
    <button class="lang" id="lang" type="button" aria-label="Switch language">EN</button>
  </div>
</div>
<main>
  <section class="hero" style="border-top:0; padding-top:1rem">
    <h1 data-i="h1">Übernimm das Steuer deiner Agenten.</h1>
    <p class="sub" data-i="sub">HelmDeck orchestriert Coding-Agenten auf deinem eigenen Rechner – Karten aufs Board, Arbeit in isolierten Worktrees, Freigabe vom Handy.</p>
    <div class="hero-actions">
      <a class="btn btn-primary" href="#downloads" data-i="heroCtaPrimary">Jetzt herunterladen</a>
      <a class="btn btn-ghost" href="https://github.com/${REPO}" target="_blank" rel="noopener noreferrer" data-i="heroCtaSecondary">Quellcode auf GitHub</a>
    </div>
  </section>

  <section class="features" style="border-top:0; padding-top:0">
    <div class="feature"><p data-i="feat1">Karten aufs Board, Agenten übernehmen sie – ohne dass du daneben sitzt.</p></div>
    <div class="feature"><p data-i="feat2">Jede Karte läuft isoliert: eigener Worktree, eigener Branch, nichts kollidiert.</p></div>
    <div class="feature"><p data-i="feat3">Freigabe vom Handy: live zusehen, im Chat antworten, Ergebnisse annehmen oder ablehnen.</p></div>
  </section>

  <section id="downloads">
    <h2 data-i="dlTitle">Jetzt verfügbar</h2>
    <p class="section-sub" data-i="dlSub">Desktop für Windows und macOS, dazu die App fürs iPhone und für Android. Läuft komplett auf deinem eigenen Rechner – keine Cloud, kein Account, keine Wartezeit.</p>
    <div class="dl-grid">
      <div class="dl-card">
        <h3>Windows</h3>
        <p class="dl-meta">${dlMeta(win)}</p>
        <p class="dl-note" data-i="dlWinNote">Nicht code-signiert – Windows warnt beim ersten Start. „Weitere Informationen“ → „Trotzdem ausführen“.</p>
        <div class="dl-actions">
          <a class="btn btn-primary btn-sm btn-block" href="${dlHref(win)}" data-i="dlBtn">Herunterladen</a>
        </div>
      </div>
      <div class="dl-card">
        <h3>macOS</h3>
        <p class="dl-meta">${dlMeta(macArm)}${macArm && macX64 ? " · " : ""}${macX64 ? "Intel " + dlMeta(macX64) : ""}</p>
        <p class="dl-note" data-i="dlMacNote">Signiert &amp; von Apple notarisiert – öffnet ohne Gatekeeper-Warnung.</p>
        <div class="dl-actions">
          <a class="btn btn-primary btn-sm btn-block" href="${dlHref(macArm)}" data-i="dlMacArmBtn">Apple Silicon herunterladen</a>
          <a class="btn btn-ghost btn-sm btn-block" href="${dlHref(macX64)}" data-i="dlMacIntelBtn">Intel herunterladen</a>
        </div>
      </div>
      <div class="dl-card">
        <h3>iPhone &amp; iPad</h3>
        <p class="dl-meta" data-i="dlIosMeta">TestFlight-Beta · öffentlicher Link in Vorbereitung</p>
        <p class="dl-note" data-i-html="dlIosNote">Der öffentliche TestFlight-Link liegt gerade bei Apple in Prüfung. Bis dahin geht es per Einladung: schick uns die Apple-ID deines Geräts an <a href="${TESTFLIGHT_REQUEST_URL}">${OWNER_EMAIL}</a> – du bekommst die Einladung per Mail.</p>
        <div class="dl-actions">
          <button type="button" class="btn btn-primary btn-sm btn-block" id="ios-copy" data-copy="${OWNER_EMAIL}" data-i="dlIosCopyBtn">E-Mail-Adresse kopieren</button>
          <a class="btn btn-ghost btn-sm btn-block" href="${TESTFLIGHT_APP_URL}" target="_blank" rel="noopener noreferrer" data-i="dlIosAppBtn">TestFlight-App laden</a>
        </div>
      </div>
      <div class="dl-card">
        <h3>Android</h3>
        <p class="dl-meta">${dlMeta(android)}</p>
        <p class="dl-note" data-i="dlAndroidNote">Direkt aus dem Google Play Store – öffentlich verfügbar. Die APK hier ist zum Sideload, falls du lieber direkt installierst.</p>
        <div class="dl-actions">
          <a class="btn btn-primary btn-sm btn-block" href="${PLAY_URL}" target="_blank" rel="noopener noreferrer" data-i="dlAndroidPlayBtn">Bei Google Play laden</a>
          <a class="btn btn-ghost btn-sm btn-block" href="${dlHref(android)}" data-i="dlAndroidApkBtn">APK herunterladen</a>
        </div>
      </div>
    </div>
    <p class="dl-all"><a href="${RELEASES_URL}" target="_blank" rel="noopener noreferrer" data-i="dlAll">Alle Downloads &amp; Prüfsummen auf GitHub</a></p>
  </section>

  <section class="waitlist" id="waitlist">
    <h2 data-i="waitlistTitle">HelmDeck Watch &amp; Glasses</h2>
    <p class="section-sub" data-i="waitlistSub">Das Steuer aufs Handgelenk und auf die Nase: HelmDeck für Wearables ist als Nächstes dran.</p>
    <div class="wl-inner">
      <div id="joinbox" ${showSuccess ? "hidden" : ""}>
        <p class="lead" data-i="lead" style="margin:0 0 .8rem; font-size:.92rem; color:var(--ink-3)">Trag dich ein – wir melden uns, sobald es losgeht.</p>
        <form id="f" action="/api/join" method="post" novalidate>
          <div class="field">
            <label class="hp" for="email" data-i="label">E-Mail-Adresse</label>
            <input id="email" name="email" type="email" required maxlength="254"
                   placeholder="du@example.com" autocomplete="email" spellcheck="false" data-i-ph="ph">
            <input class="hp" type="text" name="company" tabindex="-1" autocomplete="off" aria-hidden="true">
          </div>
          <button class="btn btn-primary" id="go" type="submit" data-i="cta">Auf die Liste</button>
          <p class="err" id="err" role="status" aria-live="polite">${err ? "Das sieht nicht nach einer gültigen E-Mail-Adresse aus." : ""}</p>
        </form>
        <p class="consent" data-i="consent">Ein Eintrag, eine Mail: Wir speichern deine Adresse nur, um dich einmalig zu benachrichtigen, sobald HelmDeck für Watch/Glasses startet. Kein Newsletter, keine Weitergabe.</p>
      </div>

      <div class="success" id="done" ${showSuccess ? "" : "hidden"}>
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="11" stroke="#5CB572" stroke-width="1.6"/>
          <path d="M7.4 12.4l3 3 6-6.4" stroke="#5CB572" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div>
          <h2 id="done-h" tabindex="-1" data-i="${already ? "doneAlreadyH" : "doneH"}" style="font-size:1.05rem">${already ? "Schon eingetragen." : "Du stehst auf der Liste."}</h2>
          <p><span data-i="${already ? "doneAlreadyP" : "doneP"}">${already ? "Diese Adresse steht bereits auf der Liste – alles gut." : "Wir melden uns einmalig, sobald es losgeht:"}</span> <b id="done-mail">${safeEmail}</b></p>
        </div>
      </div>

      <details>
        <summary data-i="privacyQ">Was passiert mit deiner E-Mail?</summary>
        <div data-i-html="privacyA">Deine Adresse wird bei Cloudflare (Workers KV) gespeichert und
        ausschließlich verwendet, um dich einmalig über den Start von HelmDeck für Watch/Glasses zu
        informieren. Danach wird die Liste gelöscht. Keine Weitergabe an Dritte, kein Tracking auf
        dieser Seite. Löschung jederzeit auf Zuruf: <a href="mailto:tienduyvo@googlemail.com">tienduyvo@googlemail.com</a>
        (Verantwortlicher: Tien Duy Vo).</div>
      </details>
    </div>
  </section>
</main>
<footer>HelmDeck · <a href="mailto:tienduyvo@googlemail.com" data-i="contact">Kontakt</a>${FEEDBACK_URL ? ` · <a href="${FEEDBACK_URL}" target="_blank" rel="noopener noreferrer">Feedback</a>` : ""}</footer>
<script>
(function(){
  var I18N = {
    de:{
      title:"HelmDeck – Downloads für Windows, macOS, iOS & Android",
      navDownloads:"Downloads", navWaitlist:"Watch & Glasses",
      h1:"Übernimm das Steuer deiner Agenten.",
      sub:"HelmDeck orchestriert Coding-Agenten auf deinem eigenen Rechner – Karten aufs Board, Arbeit in isolierten Worktrees, Freigabe vom Handy.",
      heroCtaPrimary:"Jetzt herunterladen", heroCtaSecondary:"Quellcode auf GitHub",
      feat1:"Karten aufs Board, Agenten übernehmen sie – ohne dass du daneben sitzt.",
      feat2:"Jede Karte läuft isoliert: eigener Worktree, eigener Branch, nichts kollidiert.",
      feat3:"Freigabe vom Handy: live zusehen, im Chat antworten, Ergebnisse annehmen oder ablehnen.",
      dlTitle:"Jetzt verfügbar", dlSub:"Desktop für Windows und macOS, dazu die App fürs iPhone und für Android. Läuft komplett auf deinem eigenen Rechner – keine Cloud, kein Account, keine Wartezeit.",
      dlBtn:"Herunterladen",
      dlWinNote:"Nicht code-signiert – Windows warnt beim ersten Start. „Weitere Informationen“ → „Trotzdem ausführen“.",
      dlMacNote:"Signiert & von Apple notarisiert – öffnet ohne Gatekeeper-Warnung.",
      dlMacArmBtn:"Apple Silicon herunterladen", dlMacIntelBtn:"Intel herunterladen",
      dlIosMeta:"TestFlight-Beta · öffentlicher Link in Vorbereitung",
      dlIosNote:"Der öffentliche TestFlight-Link liegt gerade bei Apple in Prüfung. Bis dahin geht es per Einladung: schick uns die Apple-ID deines Geräts an <a href=\\"${TESTFLIGHT_REQUEST_URL}\\">${OWNER_EMAIL}</a> – du bekommst die Einladung per Mail.",
      dlIosCopyBtn:"E-Mail-Adresse kopieren", dlIosCopied:"Adresse kopiert ✓", dlIosAppBtn:"TestFlight-App laden",
      dlAndroidNote:"Direkt aus dem Google Play Store – öffentlich verfügbar. Die APK hier ist zum Sideload, falls du lieber direkt installierst.",
      dlAndroidPlayBtn:"Bei Google Play laden", dlAndroidApkBtn:"APK herunterladen",
      dlAll:"Alle Downloads & Prüfsummen auf GitHub",
      waitlistTitle:"HelmDeck Watch & Glasses",
      waitlistSub:"Das Steuer aufs Handgelenk und auf die Nase: HelmDeck für Wearables ist als Nächstes dran.",
      lead:"Trag dich ein – wir melden uns, sobald es losgeht.",
      label:"E-Mail-Adresse", ph:"du@example.com", cta:"Auf die Liste",
      consent:"Ein Eintrag, eine Mail: Wir speichern deine Adresse nur, um dich einmalig zu benachrichtigen, sobald HelmDeck für Watch/Glasses startet. Kein Newsletter, keine Weitergabe.",
      doneH:"Du stehst auf der Liste.", doneP:"Wir melden uns einmalig, sobald es losgeht:",
      doneAlreadyH:"Schon eingetragen.", doneAlreadyP:"Diese Adresse steht bereits auf der Liste – alles gut.",
      errInvalid:"Das sieht nicht nach einer gültigen E-Mail-Adresse aus.",
      errNet:"Gerade nicht erreichbar – bitte versuch es gleich nochmal.",
      privacyQ:"Was passiert mit deiner E-Mail?",
      privacyA:'Deine Adresse wird bei Cloudflare (Workers KV) gespeichert und ausschließlich verwendet, um dich einmalig über den Start von HelmDeck für Watch/Glasses zu informieren. Danach wird die Liste gelöscht. Keine Weitergabe an Dritte, kein Tracking auf dieser Seite. Löschung jederzeit auf Zuruf: <a href="mailto:tienduyvo@googlemail.com">tienduyvo@googlemail.com</a> (Verantwortlicher: Tien Duy Vo).',
      contact:"Kontakt", sending:"…", toggle:"EN" },
    en:{
      title:"HelmDeck – Downloads for Windows, macOS, iOS & Android",
      navDownloads:"Downloads", navWaitlist:"Watch & Glasses",
      h1:"Take the helm of your agents.",
      sub:"HelmDeck orchestrates coding agents on your own machine – cards onto the board, work in isolated worktrees, approve from your phone.",
      heroCtaPrimary:"Download now", heroCtaSecondary:"Source on GitHub",
      feat1:"Cards go on the board, agents pick them up – no need to sit and watch.",
      feat2:"Every card runs isolated: its own worktree, its own branch, nothing collides.",
      feat3:"Approve from your phone: watch live, answer in chat, accept or reject results.",
      dlTitle:"Available now", dlSub:"Desktop for Windows and macOS, plus the app for iPhone and Android. Runs entirely on your own machine – no cloud, no account, no waiting.",
      dlBtn:"Download",
      dlWinNote:"Not code-signed yet, so Windows will warn you. Click \\u201cMore info\\u201d → \\u201cRun anyway\\u201d.",
      dlMacNote:"Signed & notarized by Apple – opens with no Gatekeeper warning.",
      dlMacArmBtn:"Download for Apple Silicon", dlMacIntelBtn:"Download for Intel",
      dlIosMeta:"TestFlight beta · public link in review",
      dlIosNote:"The public TestFlight link is currently under review at Apple. Until then it's invite-based: send your device's Apple ID to <a href=\\"${TESTFLIGHT_REQUEST_URL}\\">${OWNER_EMAIL}</a> and you'll get the invite by mail.",
      dlIosCopyBtn:"Copy email address", dlIosCopied:"Address copied ✓", dlIosAppBtn:"Get the TestFlight app",
      dlAndroidNote:"Straight from the Google Play Store – publicly available. The APK here is for sideloading if you'd rather install directly.",
      dlAndroidPlayBtn:"Get it on Google Play", dlAndroidApkBtn:"Download APK",
      dlAll:"All downloads & checksums on GitHub",
      waitlistTitle:"HelmDeck Watch & Glasses",
      waitlistSub:"The helm on your wrist and on your face: HelmDeck for wearables is next.",
      lead:"Join the list – we'll reach out once it ships.",
      label:"Email address", ph:"you@example.com", cta:"Join the list",
      consent:"One entry, one email: we store your address only to notify you once when HelmDeck for Watch/Glasses launches. No newsletter, no sharing.",
      doneH:"You're on the list.", doneP:"We'll reach out once when it ships:",
      doneAlreadyH:"Already signed up.", doneAlreadyP:"This address is already on the list – you're all set.",
      errInvalid:"That doesn't look like a valid email address.",
      errNet:"Can't reach the server right now – please try again shortly.",
      privacyQ:"What happens to your email?",
      privacyA:'Your address is stored with Cloudflare (Workers KV) and used solely to notify you once about HelmDeck for Watch/Glasses launching. The list is deleted afterwards. No third-party sharing, no tracking on this page. Deletion any time on request: <a href="mailto:tienduyvo@googlemail.com">tienduyvo@googlemail.com</a> (controller: Tien Duy Vo).',
      contact:"Contact", sending:"…", toggle:"DE" }
  };
  var lang = "de";
  try { lang = localStorage.getItem("hd_lang") || ((navigator.language||"de").slice(0,2)==="de" ? "de" : "en"); } catch(e){}
  if (lang !== "de" && lang !== "en") lang = "de";

  var langBtn = document.getElementById("lang");
  function apply(){
    var t = I18N[lang];
    document.documentElement.lang = lang;
    document.title = t.title;
    var els = document.querySelectorAll("[data-i]");
    for (var i=0;i<els.length;i++){ var k = els[i].getAttribute("data-i"); if (t[k]) els[i].textContent = t[k]; }
    var htmls = document.querySelectorAll("[data-i-html]");
    for (var j=0;j<htmls.length;j++){ var hk = htmls[j].getAttribute("data-i-html"); if (t[hk]) htmls[j].innerHTML = t[hk]; }
    var phs = document.querySelectorAll("[data-i-ph]");
    for (var p=0;p<phs.length;p++){ var pk = phs[p].getAttribute("data-i-ph"); if (t[pk]) phs[p].setAttribute("placeholder", t[pk]); }
    langBtn.textContent = t.toggle;
  }
  langBtn.addEventListener("click", function(){
    lang = (lang === "de") ? "en" : "de";
    try { localStorage.setItem("hd_lang", lang); } catch(e){}
    apply();
  });
  if (lang !== "de") apply(); else langBtn.textContent = "EN";

  // iOS card: copy the contact address. navigator.clipboard is https-only and
  // absent in older browsers, hence the execCommand fallback - this button
  // replaced a bare mailto that did NOTHING for visitors without a mail
  // handler, so silently failing again would defeat the whole fix.
  var iosCopy = document.getElementById("ios-copy");
  if (iosCopy) iosCopy.addEventListener("click", function(){
    var addr = iosCopy.getAttribute("data-copy");
    function done(){
      iosCopy.textContent = I18N[lang].dlIosCopied;
      setTimeout(function(){ iosCopy.textContent = I18N[lang].dlIosCopyBtn; }, 2000);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(addr).then(done, fallback);
    } else { fallback(); }
    function fallback(){
      var ta = document.createElement("textarea");
      ta.value = addr; ta.setAttribute("readonly", "");
      ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); }
      catch(e){ /* last resort: the address is visible in the note above anyway */ }
      document.body.removeChild(ta);
    }
  });

  var form = document.getElementById("f");
  var input = document.getElementById("email");
  var errEl = document.getElementById("err");
  var go = document.getElementById("go");
  var EMAIL_RE = /^[^\\s@]{1,64}@[^\\s@]{1,190}\\.[^\\s@.]{2,24}$/;

  form.addEventListener("submit", function(ev){
    ev.preventDefault();
    var t = I18N[lang];
    var email = (input.value || "").trim();
    if (!EMAIL_RE.test(email)){
      form.classList.add("invalid");
      errEl.textContent = t.errInvalid;
      input.focus();
      return;
    }
    form.classList.remove("invalid");
    errEl.textContent = "";
    go.disabled = true;
    var ctaText = go.textContent;
    go.textContent = t.sending;
    fetch("/api/join", {
      method:"POST",
      headers:{ "content-type":"application/json" },
      body: JSON.stringify({ email: email, lang: lang, company: form.company.value || "" })
    }).then(function(r){ return r.json(); }).then(function(res){
      if (!res.ok){ throw new Error(res.error || "invalid"); }
      document.getElementById("done-mail").textContent = email;
      var h = document.getElementById("done-h");
      h.setAttribute("data-i", res.already ? "doneAlreadyH" : "doneH");
      var pSpan = document.querySelector("#done p span");
      pSpan.setAttribute("data-i", res.already ? "doneAlreadyP" : "doneP");
      apply();
      document.getElementById("joinbox").hidden = true;
      document.getElementById("done").hidden = false;
      h.focus();
    }).catch(function(e){
      form.classList.add("invalid");
      errEl.textContent = (e && e.message === "invalid_email") ? t.errInvalid : t.errNet;
    }).finally(function(){
      go.disabled = false;
      go.textContent = I18N[lang].cta;
    });
  });
})();
</script>
</body>
</html>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function html(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      "content-security-policy":
        "default-src 'none'; base-uri 'none'; form-action 'self'; " +
        "style-src 'unsafe-inline' https://fonts.googleapis.com; " +
        "font-src https://fonts.gstatic.com; script-src 'unsafe-inline'; " +
        "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
    },
  });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

async function handleJoin(req, env) {
  let email = "", lang = "de", honeypot = "", wantsHtml = false;
  const ct = req.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    const body = await req.json().catch(() => ({}));
    email = String(body.email || "");
    lang = body.lang === "en" ? "en" : "de";
    honeypot = String(body.company || "");
  } else {
    const form = await req.formData().catch(() => null);
    if (form) {
      email = String(form.get("email") || "");
      honeypot = String(form.get("company") || "");
    }
    wantsHtml = true; // no-JS form post
  }
  email = email.trim();

  const redirect = (qs) =>
    new Response(null, { status: 303, headers: { location: "/?" + qs } });

  if (honeypot) {
    // Bot filled the invisible field: pretend success, store nothing.
    return wantsHtml ? redirect("joined=1") : json({ ok: true, already: false });
  }
  if (!EMAIL_RE.test(email) || email.length > 254) {
    return wantsHtml ? redirect("err=1") : json({ ok: false, error: "invalid_email" }, 400);
  }

  const key = "email:" + email.toLowerCase();
  const existing = await env.WAITLIST.get(key);
  const already = existing !== null;
  if (!already) {
    const ts = new Date().toISOString();
    const product = "wearables";
    await env.WAITLIST.put(key, JSON.stringify({ email, ts, lang, product }), {
      metadata: { ts, lang, product },
    });
  }
  const q = "joined=1" + (already ? "&already=1" : "") + "&e=" + encodeURIComponent(email);
  return wantsHtml ? redirect(q) : json({ ok: true, already });
}

async function handleExport(req, env) {
  const url = new URL(req.url);
  const auth = req.headers.get("authorization") || "";
  const token = url.searchParams.get("token") || auth.replace(/^Bearer\s+/i, "");
  if (!env.EXPORT_TOKEN || token !== env.EXPORT_TOKEN) {
    return json({ ok: false, error: "unauthorized" }, 401);
  }
  const rows = [["email", "joined_at", "lang", "product"]];
  let cursor;
  do {
    const page = await env.WAITLIST.list({ prefix: "email:", cursor, limit: 1000 });
    for (const k of page.keys) {
      const meta = k.metadata || {};
      rows.push([k.name.slice(6), meta.ts || "", meta.lang || "", meta.product || ""]);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  // BOM so Excel opens the UTF-8 CSV with umlauts intact
  const csv = "﻿" + rows
    .map((r) => r.map((f) => '"' + String(f).replace(/"/g, '""') + '"').join(","))
    .join("\r\n");
  return new Response(csv, {
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": 'attachment; filename="helmdeck-waitlist.csv"',
      "cache-control": "no-store",
    },
  });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const p = url.pathname;

    if (p === "/" && req.method === "GET") {
      const rel = await getReleaseAssets(env);
      return html(page({
        rel,
        joined: url.searchParams.get("joined") === "1",
        already: url.searchParams.get("already") === "1",
        err: url.searchParams.get("err") === "1",
        email: url.searchParams.get("e") || "",
      }));
    }
    if (p === "/api/join" && req.method === "POST") return handleJoin(req, env);
    if (p === "/export.csv" && req.method === "GET") return handleExport(req, env);
    if (p === "/icon.svg" && req.method === "GET") {
      return new Response(ICON_SVG, {
        headers: { "content-type": "image/svg+xml", "cache-control": "public, max-age=86400" },
      });
    }
    if (p === "/health") return json({ ok: true, service: "helmdeck-waitlist" });
    return new Response("Not found", { status: 404 });
  },
};
