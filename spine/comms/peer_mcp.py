# -*- coding: utf-8 -*-
"""stdio MCP proxy to ONE connected HelmDeck instance (spine/comms/peers.py).

    python -m spine.comms.peer_mcp <account> <connection id>

Henry's chat process (cells/copilot/chat/copilot.py _lean_mcp_args) starts one
of these per connection of the account it serves. It reads JSON-RPC lines on
stdin, forwards each sealed end-to-end to the other daemon (peers.raw) and
writes the reply. The token is decrypted inside this process (DPAPI, same
Windows user as the daemon) - it is in no config file, argv or env var.
"""
import json
import sys


def main(argv):
    if len(argv) != 3:
        sys.stderr.write("usage: python -m spine.comms.peer_mcp <account> <connection id>\n")
        return 2
    account, pid = argv[1], argv[2]
    from spine.comms import peers
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            out = peers.raw(account, pid, line)
        except peers.PeerError as e:
            if isinstance(msg, dict) and msg.get("id") is not None:
                out = json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                  "error": {"code": -32000, "message": "HelmDeck connection: %s" % e}})
            else:
                out = ""
        if out.strip():
            sys.stdout.write(out.strip() + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
