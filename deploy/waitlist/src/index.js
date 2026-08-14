/**
 * HelmDeck waitlist worker (M4 public-launch prep).
 *
 * Routes
 *   GET  /            waitlist page (DE default, EN toggle; no-JS fallback via query params)
 *   POST /api/join    store an address in KV (idempotent per email)
 *   GET  /export.csv  owner-only CSV export (?token=... or Bearer, secret EXPORT_TOKEN)
 *   GET  /icon.svg    brand mark (also used as favicon)
 *   GET  /health      liveness probe
 *
 * Storage: Workers KV, key `email:<lowercased>`, value JSON {email, ts, lang},
 * same {ts, lang} duplicated into KV metadata so the CSV export needs only
 * list() calls (no N single reads). First signup wins; re-joining never
 * overwrites the original timestamp. No IP / UA stored (data minimization).
 * Addresses can later be pushed into a Loops segment once that integration
 * exists; the CSV is the neutral interchange format until then.
 */

const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@.]{2,24}$/;

// Owner-picked Userjot board (matches app/src/data/feedback.ts) - update both
// in lockstep if the board URL ever changes.
const FEEDBACK_URL = "https://helmdeck.userjot.com";

const ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
<defs>
<linearGradient id="t" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#16191d"/><stop offset="1" stop-color="#0c0d0e"/>
</linearGradient>
<linearGradient id="h" x1="0" y1="270" x2="0" y2="740" gradientUnits="userSpaceOnUse">
<stop offset="0" stop-color="#E8F4FC"/><stop offset="1" stop-color="#96B4CD"/>
</linearGradient>
<clipPath id="c"><rect width="1024" height="1024" rx="230"/></clipPath>
<filter id="b" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="150"/></filter>
</defs>
<rect width="1024" height="1024" rx="230" fill="url(#t)"/>
<g clip-path="url(#c)">
<circle cx="205" cy="143" r="470" fill="#2893CC" opacity=".55" filter="url(#b)"/>
<circle cx="880" cy="123" r="420" fill="#967AF0" opacity=".5" filter="url(#b)"/>
<circle cx="563" cy="1045" r="470" fill="#2893CC" opacity=".33" filter="url(#b)"/>
</g>
<rect x="61" y="51" width="902" height="922" rx="185" fill="none" stroke="#fff" stroke-opacity=".14" stroke-width="7"/>
<g fill="url(#h)">
<rect x="322.6" y="291.8" width="138.2" height="440.4" rx="58"/>
<rect x="563.3" y="291.8" width="138.2" height="440.4" rx="58"/>
<rect x="322.6" y="440.3" width="378.9" height="122.9" rx="39.3"/>
</g>
</svg>`;

function page({ joined, already, err, email }) {
  const showSuccess = joined || already;
  const safeEmail = escapeHtml(email || "");
  return `<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HelmDeck – Warteliste</title>
<meta name="description" content="HelmDeck orchestriert Coding-Agenten auf deinem eigenen Rechner. Trag dich ein und erfahre als Erste(r) vom öffentlichen Start.">
<meta property="og:title" content="HelmDeck – Warteliste">
<meta property="og:description" content="Übernimm das Steuer deiner Agenten. Öffentlicher Start folgt – trag dich ein.">
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
main{
  flex:1; display:flex; flex-direction:column; justify-content:center;
  width:100%; max-width:31rem; margin:0 auto; padding:4.5rem 1.25rem 2.5rem;
}
.lockup{display:flex; align-items:center; gap:.65rem; margin-bottom:2.25rem}
.lockup svg{width:2.4rem; height:2.4rem; display:block}
.lockup b{font-size:1.05rem; font-weight:700; letter-spacing:.01em}
h1{
  margin:0 0 .8rem; font-size:clamp(1.9rem,6.5vw,2.6rem); line-height:1.14;
  font-weight:800; letter-spacing:-.02em; text-wrap:balance;
}
.sub{margin:0 0 2rem; color:var(--ink-2); max-width:60ch; text-wrap:pretty}
.sub .status{color:var(--accent-hi)}
.lead{margin:0 0 .8rem; font-size:.92rem; color:var(--ink-3)}
form{display:flex; gap:.6rem; flex-wrap:wrap}
.field{flex:1 1 14rem; position:relative}
input[type=email]{
  width:100%; height:3rem; padding:0 .95rem; border-radius:10px;
  background:var(--surface); border:1px solid var(--border-strong);
  color:var(--ink); font:inherit; font-size:.95rem; outline:none;
  transition:border-color .15s, box-shadow .15s;
}
input[type=email]::placeholder{color:var(--ph)}
input[type=email]:focus{border-color:var(--accent); box-shadow:0 0 0 3px rgba(35,150,229,.28)}
form.invalid input[type=email]{border-color:var(--danger)}
form.invalid input[type=email]:focus{box-shadow:0 0 0 3px rgba(234,106,102,.25)}
button{
  height:3rem; padding:0 1.3rem; border:0; border-radius:10px; cursor:pointer;
  background:var(--accent); color:#0A1620; font:inherit; font-size:.95rem; font-weight:700;
  transition:background .15s, transform .1s;
}
button:hover{background:var(--accent-hi)}
button:active{transform:translateY(1px)}
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
details{margin-top:2.4rem; border-top:1px solid var(--border); padding-top:1rem}
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
.lang{
  position:fixed; top:1rem; right:1rem; z-index:2;
  height:2rem; padding:0 .7rem; border-radius:999px;
  background:transparent; border:1px solid var(--border-strong);
  color:var(--ink-3); font-size:.78rem; font-weight:600;
}
.lang:hover{background:var(--layer); color:var(--ink-2); transform:none}
@keyframes rise{from{opacity:0; transform:translateY(10px)}}
.r1,.r2,.r3,.r4{animation:rise .5s cubic-bezier(.22,1,.36,1) both}
.r2{animation-delay:.06s}.r3{animation-delay:.12s}.r4{animation-delay:.18s}
@media (prefers-reduced-motion:reduce){.r1,.r2,.r3,.r4{animation:none}}
@media (max-width:480px){form button{flex:1 1 100%}}
</style>
</head>
<body>
<button class="lang" id="lang" type="button" aria-label="Switch language">EN</button>
<main>
  <div class="lockup r1">${ICON_SVG}<b>HelmDeck</b></div>
  <h1 class="r2" data-i="h1">Übernimm das Steuer deiner Agenten.</h1>
  <p class="sub r3"><span data-i="sub">HelmDeck orchestriert Coding-Agenten auf deinem eigenen Rechner –
  Karten aufs Board, Arbeit in isolierten Worktrees, Freigabe vom Handy. </span><span
  class="status" data-i="status">Aktuell läuft der geschlossene Test.</span></p>

  <section class="r4">
    <div id="joinbox" ${showSuccess ? "hidden" : ""}>
      <p class="lead" data-i="lead">Trag dich ein – wir melden uns, sobald HelmDeck öffentlich verfügbar ist.</p>
      <form id="f" action="/api/join" method="post" novalidate>
        <div class="field">
          <label class="hp" for="email" data-i="label">E-Mail-Adresse</label>
          <input id="email" name="email" type="email" required maxlength="254"
                 placeholder="du@example.com" autocomplete="email" spellcheck="false" data-i-ph="ph">
          <input class="hp" type="text" name="company" tabindex="-1" autocomplete="off" aria-hidden="true">
        </div>
        <button id="go" type="submit" data-i="cta">Auf die Liste</button>
        <p class="err" id="err" role="status" aria-live="polite">${err ? "Das sieht nicht nach einer gültigen E-Mail-Adresse aus." : ""}</p>
      </form>
      <p class="consent" data-i="consent">Ein Eintrag, eine Mail: Wir speichern deine Adresse nur,
      um dich einmalig zum Start zu benachrichtigen. Kein Newsletter, keine Weitergabe.</p>
    </div>

    <div class="success" id="done" ${showSuccess ? "" : "hidden"}>
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="11" stroke="#5CB572" stroke-width="1.6"/>
        <path d="M7.4 12.4l3 3 6-6.4" stroke="#5CB572" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <div>
        <h2 id="done-h" tabindex="-1" data-i="${already ? "doneAlreadyH" : "doneH"}">${already ? "Schon eingetragen." : "Du stehst auf der Liste."}</h2>
        <p><span data-i="${already ? "doneAlreadyP" : "doneP"}">${already ? "Diese Adresse steht bereits auf der Liste – alles gut." : "Wir melden uns einmalig, sobald es losgeht:"}</span> <b id="done-mail">${safeEmail}</b></p>
      </div>
    </div>

    <details>
      <summary data-i="privacyQ">Was passiert mit deiner E-Mail?</summary>
      <div data-i-html="privacyA">Deine Adresse wird bei Cloudflare (Workers KV) gespeichert und
      ausschließlich verwendet, um dich einmalig über den öffentlichen Start von HelmDeck zu
      informieren. Danach wird die Liste gelöscht. Keine Weitergabe an Dritte, kein Tracking auf
      dieser Seite. Löschung jederzeit auf Zuruf: <a href="mailto:tienduyvo@googlemail.com">tienduyvo@googlemail.com</a>
      (Verantwortlicher: Tien Duy Vo).</div>
    </details>
  </section>
</main>
<footer>HelmDeck · <a href="mailto:tienduyvo@googlemail.com" data-i="contact">Kontakt</a> · <a href="${FEEDBACK_URL}" target="_blank" rel="noopener noreferrer">Feedback</a></footer>
<script>
(function(){
  var I18N = {
    de:{ h1:"Übernimm das Steuer deiner Agenten.",
      sub:"HelmDeck orchestriert Coding-Agenten auf deinem eigenen Rechner – Karten aufs Board, Arbeit in isolierten Worktrees, Freigabe vom Handy. ",
      status:"Aktuell läuft der geschlossene Test.",
      lead:"Trag dich ein – wir melden uns, sobald HelmDeck öffentlich verfügbar ist.",
      label:"E-Mail-Adresse", ph:"du@example.com", cta:"Auf die Liste",
      consent:"Ein Eintrag, eine Mail: Wir speichern deine Adresse nur, um dich einmalig zum Start zu benachrichtigen. Kein Newsletter, keine Weitergabe.",
      doneH:"Du stehst auf der Liste.", doneP:"Wir melden uns einmalig, sobald es losgeht:",
      doneAlreadyH:"Schon eingetragen.", doneAlreadyP:"Diese Adresse steht bereits auf der Liste – alles gut.",
      errInvalid:"Das sieht nicht nach einer gültigen E-Mail-Adresse aus.",
      errNet:"Gerade nicht erreichbar – bitte versuch es gleich nochmal.",
      privacyQ:"Was passiert mit deiner E-Mail?",
      privacyA:'Deine Adresse wird bei Cloudflare (Workers KV) gespeichert und ausschließlich verwendet, um dich einmalig über den öffentlichen Start von HelmDeck zu informieren. Danach wird die Liste gelöscht. Keine Weitergabe an Dritte, kein Tracking auf dieser Seite. Löschung jederzeit auf Zuruf: <a href="mailto:tienduyvo@googlemail.com">tienduyvo@googlemail.com</a> (Verantwortlicher: Tien Duy Vo).',
      contact:"Kontakt", sending:"…", toggle:"EN", title:"HelmDeck – Warteliste" },
    en:{ h1:"Take the helm of your agents.",
      sub:"HelmDeck orchestrates coding agents on your own machine – cards onto the board, work in isolated worktrees, approve from your phone. ",
      status:"Currently in closed testing.",
      lead:"Join the list – we'll reach out once HelmDeck is publicly available.",
      label:"Email address", ph:"you@example.com", cta:"Join the list",
      consent:"One entry, one email: we store your address only to notify you once at launch. No newsletter, no sharing.",
      doneH:"You're on the list.", doneP:"We'll reach out once when it ships:",
      doneAlreadyH:"Already signed up.", doneAlreadyP:"This address is already on the list – you're all set.",
      errInvalid:"That doesn't look like a valid email address.",
      errNet:"Can't reach the server right now – please try again shortly.",
      privacyQ:"What happens to your email?",
      privacyA:'Your address is stored with Cloudflare (Workers KV) and used solely to notify you once about HelmDeck\\u2019s public launch. The list is deleted afterwards. No third-party sharing, no tracking on this page. Deletion any time on request: <a href="mailto:tienduyvo@googlemail.com">tienduyvo@googlemail.com</a> (controller: Tien Duy Vo).',
      contact:"Contact", sending:"…", toggle:"DE", title:"HelmDeck – Waitlist" }
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
    await env.WAITLIST.put(key, JSON.stringify({ email, ts, lang }), {
      metadata: { ts, lang },
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
  const rows = [["email", "joined_at", "lang"]];
  let cursor;
  do {
    const page = await env.WAITLIST.list({ prefix: "email:", cursor, limit: 1000 });
    for (const k of page.keys) {
      const meta = k.metadata || {};
      rows.push([k.name.slice(6), meta.ts || "", meta.lang || ""]);
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
      return html(page({
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
