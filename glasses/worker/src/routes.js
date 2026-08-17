// The routing ALLOWLIST for the Glance worker - the one security decision in
// glasses/worker, kept in its own module for two reasons:
//
//  1. It is pure. No env, no fetch, no Workers runtime - so
//     tests/test_glance_worker.py can execute it directly under plain node and
//     assert the traversal / prefix-confusion cases for real.
//  2. It CANNOT live in src/index.js. The Workers runtime treats every named
//     export of the entry module as a service export and rejects anything that
//     is not a function or an ExportedHandler - exporting `MAX_BODY` from there
//     fails at startup with "Incorrect type for map entry 'MAX_BODY'". Measured,
//     not reasoned: it took down `wrangler dev` on the first run.
//
// THE PROPERTY THIS FILE EXISTS TO HOLD:
//
//     The worker proxies FOUR paths to the daemon and nothing else, ever.
//
// The daemon behind it serves cards, settings, chat and driver commands. A
// generic pass-through would publish all of it behind one query-string token.

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
};

// Upstream bodies are small by construction (a spoken sentence, or a chosen
// option id). Anything larger is not a glance.
export const MAX_BODY = 64 * 1024;

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
