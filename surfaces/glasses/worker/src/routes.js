// The routing ALLOWLIST for the Glance worker - the one security decision in
// surfaces/glasses/worker, kept in its own module for two reasons:
//
//  1. It is pure. No env, no fetch, no Workers runtime - so
//     ops/tests/test_glance_worker.py can execute it directly under plain node and
//     assert the traversal / prefix-confusion cases for real.
//  2. It CANNOT live in src/index.js. The Workers runtime treats every named
//     export of the entry module as a service export and rejects anything that
//     is not a function or an ExportedHandler - exporting `MAX_BODY` from there
//     fails at startup with "Incorrect type for map entry 'MAX_BODY'". Measured,
//     not reasoned: it took down `wrangler dev` on the first run.
//
// THE PROPERTY THIS FILE EXISTS TO HOLD:
//
//     The worker proxies an EXPLICIT LIST of paths to the daemon and nothing
//     else, ever.
//
// The daemon behind it serves cards, settings, chat and driver commands. A
// generic pass-through would publish all of it behind one query-string token.
//
// (The count used to be written into this sentence and into index.js's header.
// It went stale twice - the list said five while the prose said four - so the
// invariant is now stated without a number that has to be maintained. The list
// below is the specification.)

// The daemon's own id rule, mirrored exactly: daemon/voice.py:63-69 accepts an
// id only if `vid.isalnum() and len(vid) <= 32`. Anchored at both ends so
// "/glance/voice/../../x.mp3" cannot match - though WHATWG URL parsing has
// already collapsed dot-segments before the fetch handler ever sees the path.
export const VOICE_RE = /^\/glance\/voice\/([A-Za-z0-9]{1,32})\.mp3$/;

// Exact path -> the single permitted method. Adding an entry widens what the
// public internet can reach on the owner's machine; do it deliberately.
export const PROXY_ROUTES = {
  "/glance": "GET",
  "/glance/answer": "POST",
  "/glance/talk": "POST",
  // THE FIX FOR A ROUTE THAT WAS DEAD IN PRODUCTION ONLY. The daemon has served
  // /glance/banner since the spoken-blocker card, and app.js has requested it
  // same-origin since the same day - but it was never added here, so through the
  // deployed Worker the request fell through to the static assets, r.json() threw
  // on index.html, and speakBanner's own .catch() swallowed it. The result: the
  // proactive "N new cards need you" announcement worked when the lens pointed
  // straight at a daemon on the LAN and was SILENT on glance.helmdeck.de - the
  // exact configuration the owner actually wears. Nothing errored anywhere.
  //
  // Safe by the same argument glance_voice already makes: this route speaks a
  // server-clamped integer (1-99) and can never carry a task name.
  "/glance/banner": "GET",
  // The lens's read of the ONE Henry conversation plus the live turn state. A
  // HANGING GET (~20s) rather than a poll - see routes_glance.glance_chat. The
  // Worker needs nothing special for that: it awaits the origin fetch like any
  // other, and 20s is well inside the edge's patience.
  "/glance/chat": "GET",
  // The microphone's own report - the one signal the daemon cannot observe for
  // itself. Bounded on the daemon side to a two-word vocabulary, so the widest
  // thing this can do is light or clear a "listening" indicator.
  "/glance/state": "POST",
  // Added 2026-08-21 for the DAT camera. Deliberately, and with the two
  // mitigations that make it defensible: the daemon side is OFF unless
  // settings.glance_photo is set (its own switch, not glance_token's), and it
  // REFUSES without a card id, so this path cannot be used to dump arbitrary
  // files at the machine - only to attach an image to a card that already
  // exists.
  "/glance/photo": "POST",
  // THE CONFIRM STEP (owner, 2026-09-04: "user spricht, es wird als text
  // Transkript, user kann bestaetigen oder loeschen und neu sprechen").
  //
  // /glance/decide is the owner's verdict on a draft, tapped on the lens. It
  // carries a word from a three-item closed vocabulary (send/redo/cancel) and a
  // seq, and the daemon refuses it unless a draft with that seq is live - so the
  // widest thing it can do is release or discard words the owner just spoke
  // himself. It cannot introduce text.
  "/glance/decide": "POST",
  // /glance/decision is the phone service waiting for that verdict. A HANGING
  // GET like /glance/chat and sized against the SAME edge limit - ~25s per
  // request, re-armed by the client - because Cloudflare abandons an origin
  // response at ~100s and a longer hold would 524 (see glassturn.DECIDE_WAIT_S).
  // Read-only: it returns one word and can change nothing.
  "/glance/decision": "GET",
};

// Upstream bodies are small by construction (a spoken sentence, or a chosen
// option id). Anything larger is not a glance.
export const MAX_BODY = 64 * 1024;

// ...EXCEPT a photo, which is the one legitimately large body here. Kept as a
// per-route override rather than by raising MAX_BODY, because raising the
// global would let a 12 MB body be posted to /glance/talk - straight into an
// agent prompt - and to /glance/answer. The wide cap belongs to exactly the
// one route that needs it.
//
// 12 MB mirrors the daemon's own pre-decode cap (routes_glance.glance_photo
// refuses b64 longer than 12_000_000), so the edge and the origin agree and a
// payload is never accepted here only to be refused there. A glasses frame is
// ~100 KB-2 MB, so this is generous headroom, not a target.
export const MAX_BODY_BY_ROUTE = {
  "/glance/photo": 12 * 1024 * 1024,
};

/** The body cap for a resolved upstream path. Default unless overridden. */
export function maxBodyFor(pathname) {
  return Object.prototype.hasOwnProperty.call(MAX_BODY_BY_ROUTE, pathname)
    ? MAX_BODY_BY_ROUTE[pathname]
    : MAX_BODY;
}

/**
 * Returns the canonical upstream path, or null meaning "not ours - serve the
 * static app". Never returns a path derived from raw user input.
 */
export function resolveRoute(pathname, method) {
  const allowed = PROXY_ROUTES[pathname];
  if (allowed) return allowed === method ? pathname : null;
  const m = VOICE_RE.exec(pathname);
  if (m && method === "GET") return "/glance/voice/" + m[1] + ".mp3";
  return null;
}
