# -*- coding: utf-8 -*-
"""CAPABILITY PROBE - re-run this whenever the claude CLI is upgraded.

Question it answers: does the CLI, driven exactly the way HelmDeck's driver
drives it (`-p --input-format stream-json`), expose AskUserQuestion and send a
control_request/can_use_tool to US when the model wants to ask the owner?

Measured 2026-08-07 against CLI 2.1.207: NO on both counts. The model reports
that AskUserQuestion does not exist, and no control_request ever arrives - not
even after an SDK `initialize` handshake (PROBE_INIT=1). That is why the
question channel is a TAUGHT protocol (daemon/ask.py) plus a repair turn rather
than a stream interception, and why the adoption plan's "intercept
AskUserQuestion in the stream" step could not be built as written.

If a future CLI answers YES, the debt item [ask-protocol-prompt-compliance] can
be paid: park the tool in the driver's control plane and resolve it with
{behavior:"allow", updatedInput:{...answers}} - which needs neither prompt
compliance nor a repair turn.

Run: py -3.12 tests/probe_cli_askuser.py [extra-cli-args...]
     PROBE_INIT=1 py -3.12 tests/probe_cli_askuser.py   (with the SDK handshake)
"""
import json, os, shutil, subprocess, sys, threading, time

CLAUDE = (os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")


def cmd_line(argv):
    if os.name != "nt":
        return argv
    return 'cmd /s /c "%s"' % subprocess.list2cmdline(argv)


PROMPT = ("Use the AskUserQuestion tool RIGHT NOW to ask me exactly one question: "
          "'Which colour do you prefer?' with the two options 'Red' and 'Blue'. "
          "Do not do anything else first, do not read any files.")


def main():
    argv = [CLAUDE, "-p",
            "--output-format", "stream-json", "--input-format", "stream-json",
            "--verbose", "--permission-mode", "acceptEdits"] + sys.argv[1:]
    print("SPAWN:", " ".join(argv[1:]), flush=True)
    p = subprocess.Popen(cmd_line(argv), cwd=os.path.dirname(os.path.abspath(__file__)),
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", bufsize=1)

    def drain_err():
        for ln in p.stderr:
            print("STDERR:", ln.rstrip()[:300], flush=True)

    threading.Thread(target=drain_err, daemon=True).start()

    if os.environ.get("PROBE_INIT"):
        # SDK handshake first: does merely performing `initialize` flip the CLI
        # into SDK mode (interactive tools exposed, permissions via can_use_tool)?
        init = {"type": "control_request", "request_id": "init-1",
                "request": {"subtype": "initialize", "hooks": {}}}
        print(">>> INIT:", json.dumps(init), flush=True)
        p.stdin.write(json.dumps(init) + "\n")
        p.stdin.flush()
        time.sleep(2)

    p.stdin.write(json.dumps({"type": "user",
                              "message": {"role": "user", "content": PROMPT}}) + "\n")
    p.stdin.flush()

    saw_control = False
    deadline = time.time() + 180
    while time.time() < deadline:
        line = p.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            print("RAW:", line[:200], flush=True)
            continue
        typ = ev.get("type")
        if typ == "control_request":
            saw_control = True
            print("\n*** CONTROL_REQUEST ***", flush=True)
            print(json.dumps(ev, indent=2)[:4000], flush=True)
            req = ev.get("request") or {}
            if req.get("subtype") == "can_use_tool":
                # answer it: allow, with the owner's pick folded into the input
                inp = dict(req.get("input") or {})
                qs = inp.get("questions") or []
                answers = {}
                for q in qs:
                    if isinstance(q, dict) and q.get("question"):
                        opts = q.get("options") or []
                        pick = (opts[0] or {}).get("label") if opts else "Red"
                        answers[q["question"]] = pick
                inp["answers"] = answers
                resp = {"type": "control_response",
                        "response": {"subtype": "success",
                                     "request_id": ev.get("request_id"),
                                     "response": {"behavior": "allow",
                                                  "updatedInput": inp}}}
                print(">>> ANSWERING:", json.dumps(resp)[:600], flush=True)
                p.stdin.write(json.dumps(resp) + "\n")
                p.stdin.flush()
            continue
        if typ == "assistant":
            for part in ((ev.get("message") or {}).get("content") or []):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    print("TOOL_USE:", part.get("name"),
                          json.dumps(part.get("input"))[:600], flush=True)
                elif part.get("type") == "text":
                    print("TEXT:", (part.get("text") or "")[:400], flush=True)
        elif typ == "user":
            for part in ((ev.get("message") or {}).get("content") or []):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    print("TOOL_RESULT:", json.dumps(part.get("content"))[:500],
                          "is_error=", part.get("is_error"), flush=True)
        elif typ == "result":
            print("RESULT subtype=", ev.get("subtype"),
                  "| result=", str(ev.get("result"))[:400], flush=True)
            break
        elif typ == "system":
            print("SYSTEM:", ev.get("subtype"), "session=", ev.get("session_id"), flush=True)

    print("\n=== saw control_request:", saw_control, "===", flush=True)
    try:
        p.kill()
    except Exception:
        pass


if __name__ == "__main__":
    main()
