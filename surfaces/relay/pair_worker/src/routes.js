// The routing ALLOWLIST for the pairing Worker - mirrors
// surfaces/glasses/worker/src/routes.js's own shape and reasoning (that file's
// own header explains WHY this lives in its own module, not index.js: the
// Workers runtime treats every named export of the ENTRY module as a service
// export, so `export const MAX_BODY = ...` there kills the worker at startup).
//
// THE PROPERTY THIS FILE EXISTS TO HOLD:
//
//     This Worker proxies ONE path and nothing else, ever.
//
// Narrower even than the glance worker's five: this exists purely so a
// keyboard-less, camera-less device (a Wear OS watch - see
// ops/docs/backlog/wear-os-integration/README.md §4.11/§4.13) can dictate ONE
// stable, permanent hostname instead of a rotating cloudflared tunnel URL,
// without ever exposing the daemon's raw HTTP surface (/auth/login and
// everything else) to the open internet the way a bare `cloudflare_tunnel.sh`
// origin does. GET /relay/pair/claim is safe to expose unauthenticated by
// design (spine/comms/relay_client.py's claim_code(): single-use, 15-minute
// TTL, a 6-char confusable-free code) - it is the ONLY daemon route with that
// property, which is exactly why it is the only one allowlisted here.

export const PROXY_ROUTES = {
  "/relay/pair/claim": "GET",
};

// GET only, no body ever accepted - there is nothing to cap, but the shape is
// kept identical to the glance worker's maxBodyFor() so proxy() doesn't need
// a special case.
export const MAX_BODY = 0;
export function maxBodyFor() {
  return MAX_BODY;
}

/**
 * Returns the canonical upstream path, or null meaning "not ours - 404".
 * Never returns a path derived from raw user input - same discipline as
 * routes_glance's resolveRoute(), even though this allowlist has only one
 * entry: the NEXT route someone adds here inherits the same guarantee for
 * free instead of having to rediscover it.
 */
export function resolveRoute(pathname, method) {
  const allowed = PROXY_ROUTES[pathname];
  return allowed && allowed === method ? pathname : null;
}
