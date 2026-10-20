# -*- coding: utf-8 -*-
"""Henry's board verbs, called INSIDE a turn - the result comes back at once.

    py -3.12 ../ops/tools/henry_act.py '{"type":"new_process","request":"...","repo":"C:/p","template":"id"}'
    py -3.12 ../ops/tools/henry_act.py --file acts.json
    py -3.12 ../ops/tools/henry_act.py --list

ONE verb, or a JSON LIST of verbs run in order in one call. Later verbs may use
what earlier ones produced: "$1.process", "$1.card", "$1.template", "$1.id"
(the Nth verb of THIS call). A verb whose reference has no id is skipped, never
guessed. At most 12 verbs per call.

It talks to the daemon with the token this process was spawned with
(HELMDECK_ACT_TOKEN) - the same executor, role gates and chat rows as the
```actions block, only now: you see each result before you continue.
Output: one JSON document, {"results": [{"n", "type", "result", "ids"}]}.
"""
import json
import os
import sys
import urllib.error
import urllib.request


def main(argv):
    url = (os.environ.get("HELMDECK_ACT_URL") or "http://127.0.0.1:8140").rstrip("/") + "/henry/act"
    tok = os.environ.get("HELMDECK_ACT_TOKEN") or ""
    if not tok:
        print("henry_act: no HELMDECK_ACT_TOKEN - this process was not spawned by the daemon "
              "(use the ```actions block)", file=sys.stderr)
        return 2
    if "--list" in argv:
        here = os.path.dirname(os.path.abspath(__file__))
        print("Verbs: run `py -3.12 %s/henry_brief_get.py get actions`" % here)
        return 0
    if argv[:1] == ["--file"] and len(argv) > 1:
        with open(argv[1], encoding="utf-8") as f:
            raw = f.read()
    elif argv:
        raw = " ".join(argv)
    else:
        raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError as e:
        print("henry_act: not valid JSON: %s" % e, file=sys.stderr)
        return 2
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "X-Henry-Act-Token": tok})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(body)
        return 1
    except OSError as e:
        print("henry_act: daemon unreachable: %s" % e, file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
