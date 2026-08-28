// HelmDeck Pair Worker - the ONLY thing on the public internet that can reach
// GET /relay/pair/claim. Built 2026-08-29 (ops/docs/backlog/wear-os-integration/
// README.md §4.13) to replace exposing the daemon's raw HTTP surface via a bare
// `cloudflare_tunnel.sh` origin - that origin answered EVERYTHING, including
// /auth/login, to anyone who found the hostname. This Worker answers exactly
// one route and 404s everything else, the same allowlist discipline
// surfaces/glasses/worker already established for /glance (that file's own
// header is the fuller rationale; this is its narrower sibling, not a
// reinvention - deliberately NOT added to that worker: its own test,
// ops/tests/test_glance_worker.py, asserts `/relay/pair` stays unreachable
// through it, and it strips Cookie/Authorization on the way up, which would
// have broken the (different, session-authenticated) code-MINTING route even
// if the allowlist boundary were lifted).
//
// THE SHAPE, industry-standard: this is the OAuth Device Authorization Grant
// pattern (RFC 8628) - a keyboard-less device polls a STABLE, ALWAYS-ON,
// narrowly-scoped endpoint with a short code; a separate, already-authenticated
// client (the phone, Settings -> Team -> "Uhr koppeln") mints that code. The
// architectural gap this Worker closes is that the "stable endpoint" half used
// to be an ad-hoc, wide-open tunnel instead of a purpose-built gateway.
//
// HOW THE DAEMON IS REACHED. Same constraint as the glance worker: a Worker
// runs at Cloudflare's edge and cannot see localhost:8140. DAEMON_URL is a
// wrangler SECRET (never committed) pointing at cloudflared's own
// `<tunnel-id>.cfargotunnel.com` address - NOT a customer-facing hostname,
// because nothing ever needs to type or dictate it; only this Worker ever
// calls it.
import { resolveRoute } from "./routes.js";

// Stripped on the way up for the same reason the glance worker strips them:
// the daemon also authenticates the desktop UI by session cookie, and
// GET /relay/pair/claim is deliberately unauthenticated - forwarding
// credentials here would be pointless at best and a replay path at worst.
const STRIP_UP = new Set([
  "cookie", "authorization", "host", "connection", "keep-alive",
  "transfer-encoding", "upgrade", "te", "trailer", "expect",
  "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "x-real-ip",
]);

const STRIP_DOWN = new Set([
  "set-cookie", "connection", "keep-alive", "transfer-encoding", "upgrade",
]);

async function proxy(request, env, path) {
  const daemon = (env.DAEMON_URL || "").trim();
  if (!daemon) {
    return json(503, {
      error: "DAEMON_URL is not configured on this Worker",
      fix: "npx wrangler secret put DAEMON_URL   (the tunnel's own cfargotunnel.com origin)",
    });
  }

  const headers = new Headers();
  for (const [k, v] of request.headers) {
    if (!STRIP_UP.has(k.toLowerCase())) headers.set(k, v);
  }

  let target;
  try {
    target = new URL(path + new URL(request.url).search, daemon);
  } catch (e) {
    return json(500, { error: "DAEMON_URL is not a valid URL" });
  }

  let res;
  try {
    res = await fetch(target.toString(), {
      method: request.method,
      headers,
      redirect: "manual",
    });
  } catch (e) {
    // The tunnel being down is the single most likely failure here, and it
    // is worth naming - same discipline as the glance worker's own proxy().
    return json(502, {
      error: "cannot reach the HelmDeck daemon",
      detail: String((e && e.message) || e),
    });
  }

  const out = new Headers();
  for (const [k, v] of res.headers) {
    if (!STRIP_DOWN.has(k.toLowerCase())) out.set(k, v);
  }
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
    const url = new URL(request.url); // normalises ../ before matching
    const path = url.pathname;

    if (path === "/health") {
      return json(200, { ok: true, service: "helmdeck-pair",
                         daemon: Boolean((env.DAEMON_URL || "").trim()) });
    }

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    const route = resolveRoute(path, request.method);
    if (route) return proxy(request, env, route);

    // No static assets here (unlike the glance worker) - there is no webapp
    // to fall back to. Anything off the allowlist is simply gone.
    return json(404, { error: "not found" });
  },
};
