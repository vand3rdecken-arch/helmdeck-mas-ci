import type { NextRequest } from "next/server";

// Real SSE streaming. The `/backend/*` rewrite is a buffering proxy - it holds
// a streamed response until the upstream closes, so incremental SSE frames never
// reach the browser. A Route Handler instead pipes the daemon's response body
// straight through as a live ReadableStream (this is the streaming Next.js is for).
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const DAEMON = "http://localhost:8140";

export async function GET(request: NextRequest, ctx: RouteContext<"/sse/tracks/[id]">) {
  const { id } = await ctx.params;
  const cookie = request.headers.get("cookie") || "";
  let upstream: Response;
  try {
    upstream = await fetch(`${DAEMON}/tracks/${encodeURIComponent(id)}/stream`, {
      headers: { cookie, accept: "text/event-stream" },
      signal: request.signal,   // client disconnect aborts the upstream too
      // @ts-expect-error - undici streaming duplex flag, not in the DOM types
      duplex: "half",
    });
  } catch {
    return new Response("upstream unavailable", { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response("upstream error", { status: upstream.status || 502 });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
