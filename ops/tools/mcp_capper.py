# -*- coding: utf-8 -*-
"""MCP stdio proxy that caps oversized tool-call results before they ever
reach a card's model context (ops/docs/backlog/token-burn-hardening/README.md,
Karte A - the 190M-token Wear-OS turn: windows-mcp's `Snapshot` returned
600-700 KB of UIA tree PER CALL, 122 calls straight into context, paid again
on every cache-read as the turn grew - quadratic cost from ONE unbounded tool).

Sits IN FRONT of the real MCP server on the stdio channel: stdin/stdout speak
the same newline-delimited JSON-RPC the CLI expects, a child process runs the
real server, and every message is relayed through UNCHANGED except a
tool-call response whose result/error exceeds the cap (default 50_000 chars,
per-tool override) - that text is cut to the cap and a marker tail appended,
never dropped whole, so a card can still act on a truncated-but-present
result.

Downstream truncation (e.g. the daemon's own stream fold) saves NOTHING - by
the time anything downstream observes a result, the model has already paid
for the full thing. The cap has to sit upstream, on the MCP channel itself.

Wired by spine/agent/agentcli.py's `_mcp_config_arg` for machine cards, which
already resolves the real server's command/args from `~/.claude.json` - this
script never resolves or invents a command of its own, it only wraps one it
is handed. Manual invocation for a replay/verify:

    py -3.12 ops/tools/mcp_capper.py --max-chars 50000 \\
        --override Snapshot=20000 -- uvx windows-mcp serve --transport stdio
"""
import json
import subprocess
import sys
import threading

MARKER = "\n…[gekürzt — Query verengen]"
DEFAULT_MAX_CHARS = 50_000


def _truncate(obj, cap):
    """Cap every string leaf, recursively - so ANY future MCP server's result
    shape shrinks, not just the `content[].text` shape windows-mcp uses today."""
    if isinstance(obj, str):
        return obj[:cap] + MARKER if len(obj) > cap else obj
    if isinstance(obj, list):
        return [_truncate(x, cap) for x in obj]
    if isinstance(obj, dict):
        return {k: _truncate(v, cap) for k, v in obj.items()}
    return obj


def _cap_response(msg, tool_of_id, default_cap, overrides):
    mid = msg.get("id")
    tool = tool_of_id.pop(mid, None) if mid is not None else None
    cap = overrides.get(tool, default_cap)
    for key in ("result", "error"):
        if key in msg:
            msg[key] = _truncate(msg[key], cap)
    return msg


def _pump_requests(inp, outp, tool_of_id):
    """Client -> server: relayed byte-for-byte. The only thing read out of a
    request is which tool a `tools/call` id names, so the matching response
    can be capped by that tool's own override."""
    for line in iter(inp.readline, b""):
        stripped = line.strip()
        if stripped:
            try:
                msg = json.loads(stripped)
            except ValueError:
                msg = None
            if msg is not None and msg.get("method") == "tools/call" and "id" in msg:
                name = (msg.get("params") or {}).get("name")
                if name:
                    tool_of_id[msg["id"]] = name
        outp.write(line)
        outp.flush()
    try:
        outp.close()
    except OSError:
        pass


def _pump_responses(inp, outp, tool_of_id, default_cap, overrides):
    """Server -> client: only a JSON-RPC response (has `result` or `error`)
    is re-serialized; requests/notifications pass through byte-identical."""
    for line in iter(inp.readline, b""):
        stripped = line.strip()
        if stripped:
            try:
                msg = json.loads(stripped)
            except ValueError:
                msg = None
            if msg is not None and ("result" in msg or "error" in msg):
                msg = _cap_response(msg, tool_of_id, default_cap, overrides)
                line = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        outp.write(line)
        outp.flush()
    try:
        outp.close()
    except OSError:
        pass


def _parse_argv(argv):
    if "--" in argv:
        i = argv.index("--")
        own, child = argv[:i], argv[i + 1:]
    else:
        own, child = argv, []
    if not child:
        sys.exit(__doc__)
    max_chars = DEFAULT_MAX_CHARS
    overrides = {}
    j = 0
    while j < len(own):
        a = own[j]
        if a == "--max-chars":
            j += 1
            max_chars = int(own[j])
        elif a == "--override":
            j += 1
            name, _, n = own[j].partition("=")
            overrides[name] = int(n)
        else:
            sys.exit("mcp_capper: unknown option %r\n\n%s" % (a, __doc__))
        j += 1
    return max_chars, overrides, child


def main():
    max_chars, overrides, child = _parse_argv(sys.argv[1:])
    proc = subprocess.Popen(child, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    tool_of_id = {}
    t_in = threading.Thread(target=_pump_requests,
                             args=(sys.stdin.buffer, proc.stdin, tool_of_id),
                             daemon=True)
    t_out = threading.Thread(target=_pump_responses,
                              args=(proc.stdout, sys.stdout.buffer, tool_of_id,
                                    max_chars, overrides),
                              daemon=True)
    t_in.start()
    t_out.start()
    rc = proc.wait()
    t_out.join(timeout=5)
    sys.exit(rc)


if __name__ == "__main__":
    main()
