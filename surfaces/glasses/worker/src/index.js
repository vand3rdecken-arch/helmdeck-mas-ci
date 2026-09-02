// HelmDeck Glance - Cloudflare Worker that HOSTS the glasses webapp and is the
// ONLY thing on the public internet that can reach the daemon's /glance surface.
//
// WHY THIS EXISTS (ops/docs/glasses-reference.md 11.9). Getting a webapp onto the
// Ray-Ban Display permanently is a self-serve registration - Meta AI app ->
// Developer Mode -> App Connections -> Web Apps -> Add a Web App - and it needs
// exactly one thing we did not have: a PUBLIC HTTPS URL. The store listing being
// partner-only is a different question and does not apply. So the blocker was
// never permission, it was reachability, and this file is the reachability.
//
// The pattern is lifted from the owner's glass-crud-harness, which ships this
// way in production: ONE origin serves both the static app and the API, so you
// register ONE URL forever and ship new screens by redeploying. Same-origin is
// not cosmetic - glass-crud-harness had to make its TTS proxy same-origin
// because "an <audio> can't send the bearer header" (worker.js:341-344), and
// this app hits the identical wall with /glance/voice/<id>.mp3.
//
// HOW THE DAEMON IS REACHED. A Worker runs at Cloudflare's edge and CANNOT see
// localhost:8140. DAEMON_URL must therefore be an inbound-reachable HTTPS origin
// in front of the daemon - `bash ops/deploy/cloudflare_tunnel.sh` already produces
// exactly that. It is a wrangler SECRET, never committed: it is a public door to
// a machine in the owner's flat.
//
// THE SECURITY PROPERTY THIS FILE MUST HOLD, above all else:
//
//     This Worker proxies an EXPLICIT ALLOWLIST of paths and nothing else, ever.
//
// (This line used to name a count. It was wrong - it said FOUR while routes.js
// listed five - which is how /glance/banner went missing from the list without
// anyone noticing the prose and the code disagreeing. routes.js IS the list.)
//
// A generic pass-through would publish the entire daemon - cards, settings,
// chat, the driver commands - to the open internet behind one query-string
// token. So routing is an ALLOWLIST of exact paths (plus one tightly-anchored
// regex for the audio id), and anything unmatched is served from static assets
// or 404s. It never falls through to the daemon. ops/tests/test_glance_worker.py
// asserts this, including the traversal and prefix-confusion attempts.
//
// Cookies and Authorization are stripped on the way UP. The daemon also serves
// the desktop UI on session cookies; forwarding credentials would turn this
// into a replay path into an authenticated session. /glance auth is the
// glance_token and only the glance_token.

// The allowlist and the routing decision live in ./routes.js, NOT here. The
// Workers runtime treats every named export of the ENTRY module as a service
// export and refuses anything that is not a function or an ExportedHandler, so
// `export const MAX_BODY = ...` in this file kills the worker at startup:
//   "Incorrect type for map entry 'MAX_BODY'"
// Keeping them next door also lets the gate test execute the real routing
// function under plain node. This module exports the handler and nothing else.
import { resolveRoute, maxBodyFor } from "./routes.js";

// Headers we refuse to pass upstream. Cookie/Authorization are the load-bearing
// ones (see the header); the rest are hop-by-hop or edge metadata that would
// only confuse the daemon's stdlib HTTP server.
const STRIP_UP = new Set([
  "cookie", "authorization", "host", "connection", "keep-alive",
  "transfer-encoding", "upgrade", "te", "trailer", "expect",
  "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "x-real-ip",
]);

// ...and back down. `set-cookie` must never reach the glasses from a proxied
// daemon response; nothing in /glance sets one, and if that ever changes this
// should not be the thing that quietly starts honouring it.
const STRIP_DOWN = new Set([
  "set-cookie", "connection", "keep-alive", "transfer-encoding", "upgrade",
]);

/**
 * The token reaches us either as a header (preferred - a URL with a token in
 * the query string is written to Cloudflare's request logs, a header is not) or
 * as ?token= . It always leaves as ?token= , because that is the only shape the
 * daemon accepts (daemon/server.py:415-418).
 *
 * The <audio> element is the exception that forces the query form to stay
 * supported: it cannot set headers, so /glance/voice/<id>.mp3 is fetched with
 * the token in the URL. That is the same constraint glass-crud-harness hit.
 */
function upstreamUrl(daemonBase, path, reqUrl, headerToken) {
  const src = new URL(reqUrl);
  const out = new URL(path, daemonBase);
  for (const [k, v] of src.searchParams) {
    if (k !== "token") out.searchParams.set(k, v);
  }
  const tok = headerToken || src.searchParams.get("token") || "";
  if (tok) out.searchParams.set("token", tok);
  return out;
}

async function proxy(request, env, path) {
  const daemon = (env.DAEMON_URL || "").trim();
  if (!daemon) {
    // Fail closed and say why. A silent 502 here reads as "the daemon is down"
    // and sends the owner debugging the wrong machine.
    return json(503, {
      error: "DAEMON_URL is not configured on this Worker",
      fix: "npx wrangler secret put DAEMON_URL   (the HTTPS tunnel in front of :8140)",
    });
  }

  let body;
  if (request.method === "POST") {
    body = await request.arrayBuffer();
    // PER-ROUTE cap. `path` here is the value resolveRoute() already returned,
    // i.e. one of the allowlisted paths - never raw user input - so it cannot
    // be steered to pick the wide photo cap for a different route.
    if (body.byteLength > maxBodyFor(path)) {
      return json(413, { error: "glance body too large" });
    }
  }

  const headers = new Headers();
  for (const [k, v] of request.headers) {
    if (!STRIP_UP.has(k.toLowerCase()) && k.toLowerCase() !== "x-glance-token") {
      headers.set(k, v);
    }
  }

  let target;
  try {
    target = upstreamUrl(daemon, path, request.url,
                         request.headers.get("x-glance-token"));
  } catch (e) {
    return json(500, { error: "DAEMON_URL is not a valid URL" });
  }

  let res;
  try {
    res = await fetch(target.toString(), {
      method: request.method,
      headers,
      body,
      redirect: "manual",   // a redirect off the allowlist is not ours to follow
    });
  } catch (e) {
    // The tunnel being down is the single most likely failure in this whole
    // path, and it is worth naming rather than surfacing a bare 502.
    return json(502, {
      error: "cannot reach the HelmDeck daemon",
      detail: String(e && e.message || e),
    });
  }

  const out = new Headers();
  for (const [k, v] of res.headers) {
    if (!STRIP_DOWN.has(k.toLowerCase())) out.set(k, v);
  }
  // Same-origin now, so the daemon's permissive CORS is redundant here. Drop it
  // rather than re-publish "*" from our own origin.
  out.delete("access-control-allow-origin");
  out.delete("access-control-allow-headers");
  return new Response(res.body, { status: res.status, headers: out });
}

function json(status, obj) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);        // normalises ../ before we match
    const path = url.pathname;

    if (path === "/health") {
      return json(200, { ok: true, service: "helmdeck-glance",
                         daemon: Boolean((env.DAEMON_URL || "").trim()) });
    }

    if (request.method === "OPTIONS") {
      // Same-origin in normal use, so this is only for a hand-driven client.
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, X-Glance-Token",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    const route = resolveRoute(path, request.method);
    if (route) return proxy(request, env, route);

    // Not an allowlisted API path: it is the static app, or it is nothing.
    if (env.ASSETS) return env.ASSETS.fetch(request);
    return json(404, { error: "not found" });
  },
};
