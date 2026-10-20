/**
 * HelmDeck relay - Cloudflare Worker edition (2026-09-22).
 *
 * Same wire protocol as surfaces/relay/relay.py, so phone (surfaces/app),
 * daemon (spine/comms/relay_client.py) and desktop OTA (surfaces/desktop/
 * desktop_update.py, updater.js) need no change beyond the DNS cutover:
 *
 *   GET  /health                         liveness + per-isolate instance id
 *   POST /relay?room=R        {pub,cipher} -> waits for the daemon's {cipher}
 *   GET  /tunnel/pull?room=R  daemon long-poll for the next frame (204 = none)
 *   POST /tunnel/push?room=R  {id,cipher}  daemon's reply for a waiting frame
 *   GET  /updates/manifest               Expo Updates v1 manifest (headers or ?platform&runtime-version&channel)
 *   GET  /updates/assets?path=&channel=  OTA asset (phone bundle or desktop channel)
 *   GET  /apk/version.json               sideload version marker (static)
 *   GET  /apk/helmdeck.apk               302 -> APK_URL (too big for a static asset)
 *   GET  /pair?c=                        pairing fallback page
 *   GET  /.well-known/assetlinks.json    Android App Links
 *   GET  /privacy | /datenschutz         privacy policy (Play Console link)
 *
 * Frames go through a Durable Object per room (src/room.js). OTA bundles are
 * static assets under public/ota/<channel>/ with a publish-time _index.json
 * (hashes, runtimeVersion, createdAt, rollback) written by
 * ops/deploy/publish_relay_worker.sh - the worker never hashes at request time
 * and never touches anything but its own bundled assets.
 */
import { Room } from "./room.js";
import { PAIR_HTML, PRIVACY_HTML, ASSETLINKS, MCP_SHIM, MCP_SHIM_SHA256 } from "./static.js";
import { MCP_PAGE } from "./mcp_page.js";
export { Room };

// per-isolate id (relay.py's _INSTANCE); random values are not allowed at
// global scope in Workers, so it is minted on first use inside a handler
let INSTANCE = "";
const instance = () => (INSTANCE ||= crypto.randomUUID().replace(/-/g, ""));
const MAX_BODY = 4 * 1024 * 1024;          // one sealed frame; daemon replies are ~2 MB max
const ROOM_RE = /^[A-Za-z0-9_-]{1,128}$/;
const CHANNEL_RE = /^[A-Za-z0-9._-]{1,64}$/;
const CT = {
  hbc: "application/javascript", js: "application/javascript",
  png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif",
  webp: "image/webp", svg: "image/svg+xml", ttf: "font/ttf", otf: "font/otf",
  json: "application/json", html: "text/html; charset=utf-8", css: "text/css",
  ico: "image/x-icon", txt: "text/plain; charset=utf-8", map: "application/json",
};

const json = (code, obj, extra = {}) =>
  new Response(JSON.stringify(obj), { status: code, headers: { "content-type": "application/json", ...extra } });
const html = (body) =>
  new Response(body, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---- OTA helpers -----------------------------------------------------------
// Asset paths come from the client (or from metadata.json, which may use
// backslashes - Windows export). Normalise and reject anything that is not a
// plain relative path. There is no filesystem behind this - a bad path can at
// most 404 - but the shape is pinned anyway so a URL never selects an asset
// outside the channel it names.
function normPath(rel) {
  const s = String(rel || "").replace(/\\/g, "/");
  if (!s || s.startsWith("/") || s.includes("..") || s.includes(":") || s.includes("\0")) return null;
  const parts = s.split("/").filter((p) => p && p !== ".");
  return parts.length ? parts.join("/") : null;
}

function channelKey(name) {
  const c = String(name || "").trim();
  return c && c !== "production" && CHANNEL_RE.test(c) ? c : "production";
}

async function loadIndex(env, channel) {
  const r = await env.ASSETS.fetch(new Request(`https://assets/ota/${channel}/_index.json`));
  if (!r.ok) return null;
  try { return await r.json(); } catch { return null; }
}

async function resolveChannel(env, requested) {
  const c = channelKey(requested);
  if (c !== "production") {
    const idx = await loadIndex(env, c);
    if (idx) return { channel: c, idx, label: c };
  }
  return { channel: "production", idx: await loadIndex(env, "production"), label: "" };
}

// uuid5(NAMESPACE_URL, name) - same derivation as relay.py so a bundle keeps
// its manifest id across the migration (the client skips ids it already applied).
async function uuid5url(name) {
  const ns = "6ba7b8119dad11d180b400c04fd430c8";
  const nsBytes = Uint8Array.from(ns.match(/../g).map((h) => parseInt(h, 16)));
  const nameBytes = new TextEncoder().encode(name);
  const buf = new Uint8Array(nsBytes.length + nameBytes.length);
  buf.set(nsBytes); buf.set(nameBytes, nsBytes.length);
  const h = new Uint8Array(await crypto.subtle.digest("SHA-1", buf));
  h[6] = (h[6] & 0x0f) | 0x50; h[8] = (h[8] & 0x3f) | 0x80;
  const hex = [...h.slice(0, 16)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function buildManifest(idx, platform, baseUrl, runtimeVersion, label) {
  const fm = idx.metadata && idx.metadata.fileMetadata && idx.metadata.fileMetadata[platform];
  if (!fm || !fm.bundle) return null;
  const asset = (rel, ext) => {
    const n = normPath(rel);
    const hash = n && idx.hashes && idx.hashes[n];
    if (!hash) return null;
    const a = {
      // The KEY is a file name on the phone, not a path (owner 2026-10-19, OTA stuck on "Base build"):
      // expo-updates stores an asset as <key><fileExtension> and now refuses a key with a path
      // separator ("…is not a valid filename"), so "_expo/static/js/android/entry-<hash>.hbc" failed
      // every download. The last segment is already unique - the bundler names files by content hash.
      key: n.split("/").pop(),
      contentType: CT[(ext || "").toLowerCase().replace(/^\./, "")] || "application/octet-stream",
      url: `${baseUrl}/updates/assets?path=${encodeURIComponent(n)}${label ? "&channel=" + encodeURIComponent(label) : ""}`,
      hash,
    };
    if (ext) a.fileExtension = "." + ext.replace(/^\./, "");
    return a;
  };
  const launch = asset(fm.bundle, "");
  if (!launch) return null;
  launch.contentType = "application/javascript";
  delete launch.fileExtension;
  const assets = (fm.assets || []).map((x) => asset(x.path, x.ext || "")).filter(Boolean);
  return { launch, assets };
}

async function manifest(request, env, url) {
  const q = url.searchParams;
  const platform = request.headers.get("expo-platform") || q.get("platform") || "android";
  const rtv = request.headers.get("expo-runtime-version") || q.get("runtime-version") || "1.0.0";
  let { idx, label } = await resolveChannel(env, request.headers.get("expo-channel-name") || q.get("channel"));
  if (idx && idx.rollback && idx.rollback.commitTime) {
    const boundary = "helmdeck-" + crypto.randomUUID().replace(/-/g, "");
    const inner = JSON.stringify({ type: "rollBackToEmbedded", parameters: { commitTime: idx.rollback.commitTime } });
    const body = `--${boundary}\r\ncontent-type: application/json\r\ncontent-disposition: form-data; name="directive"\r\n\r\n${inner}\r\n--${boundary}--\r\n`;
    return new Response(body, { status: 200, headers: {
      "expo-protocol-version": "1", "expo-sfv-version": "0", "cache-control": "private, max-age=0",
      "content-type": "multipart/mixed; boundary=" + boundary } });
  }
  // Validate the runtimeVersion against the bundle's own marker (relay.py
  // manifest route, 2026-09-13): a mismatch means the client's native runtime
  // differs from what this JS was exported for. A stranded runtime may have
  // its own channel "rt-<version>" - serve that when its marker matches.
  const real = idx && idx.runtimeVersion;
  if (real && real !== rtv) {
    const alt = await loadIndex(env, "rt-" + rtv);
    if (alt && alt.runtimeVersion === rtv && CHANNEL_RE.test("rt-" + rtv)) { idx = alt; label = "rt-" + rtv; }
    else return json(404, { error: "no update for this runtimeVersion" });
  }
  if (!idx) return json(404, { error: "no update available" });
  const parts = buildManifest(idx, platform, `https://${url.host}`, idx.runtimeVersion || rtv, label);
  if (!parts) return json(404, { error: "no update available" });
  const man = {
    id: await uuid5url(parts.launch.hash),
    createdAt: idx.createdAt,
    runtimeVersion: idx.runtimeVersion || rtv,
    launchAsset: parts.launch, assets: parts.assets, metadata: {}, extra: {},
  };
  return json(200, man, { "expo-protocol-version": "1", "expo-sfv-version": "0", "cache-control": "private, max-age=0" });
}

async function otaAsset(request, env, url) {
  const q = url.searchParams;
  const { channel } = await resolveChannel(env, q.get("channel") || request.headers.get("expo-channel-name"));
  const n = normPath(q.get("path"));
  if (!n) return json(404, { error: "not found" });
  const r = await env.ASSETS.fetch(new Request(`https://assets/ota/${channel}/${n.split("/").map(encodeURIComponent).join("/")}`));
  if (!r.ok) return json(404, { error: "not found" });
  const ext = n.includes(".") ? n.split(".").pop().toLowerCase() : "";
  return new Response(r.body, { status: 200, headers: {
    "content-type": CT[ext] || "application/octet-stream",
    "cache-control": "public, max-age=31536000, immutable" } });
}

// ---- MCP door (spine/comms/mcp_door.py) -------------------------------------
// External MCP clients cannot seal frames, so they get their OWN room, named
// by an alias the WORKER derives from a key only the daemon holds. The alias is
// public (it is in the shared URL); without the key nobody can be the daemon
// behind it. Must match mcp_door.alias_of(). Requests here are readable by the
// relay (TLS ends at Cloudflare) - debt mcp-door-relay-plaintext.
const MCP_ALIAS_RE = /^[A-Za-z0-9_-]{32}$/;
const MCP_KEY_RE = /^[A-Za-z0-9_-]{16,128}$/;
const MCP_MAX_BODY = 1024 * 1024;

async function mcpAlias(key) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key)));
  let b = btoa(String.fromCharCode(...d)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return b.slice(0, 32);
}

function mcpStub(env, alias) {
  return env.ROOMS.get(env.ROOMS.idFromName("mcp:" + alias));
}

async function mcpDaemon(request, env, url) {
  const key = url.searchParams.get("key") || "";
  if (!MCP_KEY_RE.test(key)) return json(400, { error: "key required" });
  if (request.headers.get("Upgrade") !== "websocket") return json(426, { error: "expected websocket" });
  return mcpStub(env, await mcpAlias(key)).fetch(new Request("https://room/ws", request));
}

// The resource URL as the client sees it (OAuth issuer + audience). https
// always, except a loopback dev relay (wrangler dev) - mcp_door._usable.
function mcpBase(url, alias) {
  const local = url.hostname === "localhost" || url.hostname === "127.0.0.1";
  return (local ? url.origin : "https://" + url.host) + "/mcp/" + alias;
}

// One request to the door: the MCP resource itself (sub "") or its OAuth
// surface (spine/auth/mcp_oauth.py). The daemon decides; we only carry.
async function mcpCall(request, env, url, alias, sub) {
  if (!MCP_ALIAS_RE.test(alias)) return json(404, { error: "not found" });
  const len = Number(request.headers.get("content-length") || 0);
  if (len > MCP_MAX_BODY) return json(413, { error: "too large" });
  const body = request.method === "POST" ? await request.text() : "";
  if (body.length > MCP_MAX_BODY) return json(413, { error: "too large" });
  // Origin is judged by the daemon (mcp._origin_ok). Our OWN pages (the setup
  // page redeeming a code, the /authorize form) are the browser callers we
  // vouch for, so a same-origin Origin is dropped here; any other is passed on.
  const origin = request.headers.get("origin") || "";
  const fwdOrigin = origin && origin === url.origin ? "" : origin;
  return mcpStub(env, alias).fetch(new Request("https://room/mcp", {
    // the /authorize answer is a 302 to the CLIENT's redirect_uri: hand it back,
    // never follow it here (a stub fetch follows redirects by default)
    method: "POST", redirect: "manual", headers: { "content-type": "application/json" },
    body: JSON.stringify({ method: request.method, sub, query: url.search.slice(1),
      auth: request.headers.get("authorization") || "", origin: fwdOrigin,
      base: mcpBase(url, alias), body }) }));
}

// Path -> [alias, sub] for everything the door serves, or null.
const MCP_SUBS = new Set(["authorize", "token", "register"]);
function mcpRoute(p) {
  let m = /^\/\.well-known\/(oauth-protected-resource|oauth-authorization-server|openid-configuration)\/mcp\/([A-Za-z0-9_-]{32})$/.exec(p);
  if (m) return [m[2], m[1] === "oauth-protected-resource" ? "wk/prm" : "wk/as"];
  m = /^\/mcp\/([A-Za-z0-9_-]{32})(?:\/(.*))?$/.exec(p);
  if (!m) return null;
  const rest = m[2] || "";
  if (rest === "") return [m[1], ""];
  if (MCP_SUBS.has(rest)) return [m[1], rest];
  if (rest === ".well-known/oauth-protected-resource") return [m[1], "wk/prm"];
  if (rest === ".well-known/oauth-authorization-server" || rest === ".well-known/openid-configuration") return [m[1], "wk/as"];
  return null;
}

// ---- relay core ------------------------------------------------------------
function roomStub(env, url) {
  const room = url.searchParams.get("room") || "";
  if (!ROOM_RE.test(room)) return null;
  return env.ROOMS.get(env.ROOMS.idFromName(room));
}

async function boundedBody(request) {
  const len = Number(request.headers.get("content-length") || 0);
  if (len > MAX_BODY) return null;
  const buf = await request.arrayBuffer();
  return buf.byteLength > MAX_BODY ? null : buf;
}

async function toRoom(request, env, url, inner) {
  const stub = roomStub(env, url);
  if (!stub) return json(400, { error: "room required" });
  let body;
  if (request.method === "POST") {
    body = await boundedBody(request);
    if (body === null) return json(413, { error: "frame too large" });
  }
  return stub.fetch(new Request("https://room" + inner, {
    method: request.method, body, headers: { "content-type": "application/json" } }));
}

// CORS for the ONE route a browser-origin client (the desktop shell's SPA, the
// web app) calls: POST /relay. Native phones never preflight, so this was
// invisible until the desktop tried to pair as a CLIENT (measured 2026-10-08:
// "Relay unreachable" - the preflight got a 404 without Allow-Origin and the
// browser dropped the request). `*` is safe here: the body is E2E-sealed to
// the room's daemon key, the relay reads nothing, and no cookie/credential
// rides on this request (auth is inside the sealed inner request).
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, GET, OPTIONS",
  "access-control-allow-headers": "content-type",
  "access-control-max-age": "86400",
};
const CORS_PATHS = new Set(["/relay", "/health"]);

export default {
  async fetch(request, env) {
    const p = new URL(request.url).pathname;
    if (!CORS_PATHS.has(p)) return route.fetch(request, env);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const r = await route.fetch(request, env);
    const out = new Response(r.body, r);   // r.headers is immutable; copy, then add
    for (const [k, v] of Object.entries(CORS)) out.headers.set(k, v);
    return out;
  },
};

const route = {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    const m = request.method;
    if (m === "GET" && p === "/health")
      return json(200, { ok: true, rooms: -1, instance: instance(), edge: true });
    if (m === "POST" && p === "/relay")        return toRoom(request, env, url, "/relay");
    if (m === "GET"  && p === "/tunnel/pull")  return toRoom(request, env, url, "/pull");
    if (m === "POST" && p === "/tunnel/push")  return toRoom(request, env, url, "/push");
    if (m === "GET"  && p === "/tunnel/mcpd") return mcpDaemon(request, env, url);
    const mr = (p.startsWith("/mcp/") || p.startsWith("/.well-known/")) ? mcpRoute(p) : null;
    if (mr) {
      const [alias, sub] = mr;
      if (sub === "" && m === "GET") {
        // Streamable HTTP: a client may open GET for server push; we offer none.
        // A browser (the shared link) gets the setup page instead.
        if ((request.headers.get("accept") || "").includes("text/event-stream"))
          return new Response(null, { status: 405, headers: { allow: "POST" } });
        const host = (url.hostname === "localhost" || url.hostname === "127.0.0.1") ? url.origin : "https://" + url.host;
        return new Response(MCP_PAGE.replaceAll("__URL__", esc(mcpBase(url, alias)))
            .replaceAll("__SHIM_URL__", esc(host + "/helmdeck_mcp.py"))
            .replaceAll("__SHIM_SHA__", esc(MCP_SHIM_SHA256)), { status: 200, headers: {
          "content-type": "text/html; charset=utf-8", "cache-control": "no-store",
          "referrer-policy": "no-referrer" } });
      }
      if (m !== "GET" && m !== "POST") return new Response(null, { status: 405, headers: { allow: "GET, POST" } });
      return mcpCall(request, env, url, alias, sub);
    }
    if (m === "GET"  && p === "/tunnel/ws") {
      // NOT toRoom(): that rebuilds the request with a content-type only and
      // would drop the Upgrade header. The upgrade must reach the room intact.
      const stub = roomStub(env, url);
      if (!stub) return json(400, { error: "room required" });
      if (request.headers.get("Upgrade") !== "websocket") return json(426, { error: "expected websocket" });
      return stub.fetch(new Request("https://room/ws", request));
    }
    if (m === "GET"  && p === "/tunnel/client") {
      // The PHONE's socket - same forwarding rule as /tunnel/ws: the upgrade
      // must reach the room with its headers intact.
      const stub = roomStub(env, url);
      if (!stub) return json(400, { error: "room required" });
      if (request.headers.get("Upgrade") !== "websocket") return json(426, { error: "expected websocket" });
      return stub.fetch(new Request("https://room/client" + url.search, request));
    }
    if (m === "GET"  && p === "/updates/manifest") return manifest(request, env, url);
    if (m === "GET"  && p === "/updates/assets")   return otaAsset(request, env, url);
    if (m === "GET"  && p === "/apk/version.json") {
      const r = await env.ASSETS.fetch(new Request("https://assets/apk/version.json"));
      return r.ok ? new Response(r.body, { headers: { "content-type": "application/json", "cache-control": "no-cache" } })
                  : json(404, { error: "not found" });
    }
    if (m === "GET" && p.startsWith("/apk/")) return Response.redirect(env.APK_URL, 302);
    if (m === "GET" && p === "/pair") {
      // reflected parameter: escaped for the attribute AND JSON-encoded for the
      // script (relay.py substituted it raw into both - reflected XSS, 2026-09-22)
      const c = url.searchParams.get("c") || "";
      // JSON.stringify alone is NOT enough inside <script>: it leaves "</script>"
      // intact, which the HTML parser honours before JS ever runs (the e2e test
      // caught exactly that). Escape the HTML-significant characters as \uXXXX.
      const js = JSON.stringify("helmdeck://pair?c=" + c)
        .replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026")
        .replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
      return html(PAIR_HTML.replace("__C_ATTR__", esc(c)).replace("__C_JS__", js));
    }
    if (m === "GET" && p === "/helmdeck_mcp.py")
      return new Response(MCP_SHIM, { headers: { "content-type": "text/x-python; charset=utf-8",
        "content-disposition": 'attachment; filename="helmdeck_mcp.py"', "x-content-sha256": MCP_SHIM_SHA256 } });
    if (m === "GET" && p === "/.well-known/assetlinks.json") return json(200, ASSETLINKS);
    if (m === "GET" && (p === "/privacy" || p === "/datenschutz")) return html(PRIVACY_HTML);
    return json(404, { error: "not found" });
  },
};
