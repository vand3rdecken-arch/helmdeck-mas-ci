# -*- coding: utf-8 -*-
"""Read the pipeline payload out of a running sandbox, in words.

Not a test - a LOOKING GLASS. Before spending a browser on the screen, this
prints what the daemon actually answers for each repo, so a wrong pipeline is
caught as data rather than mis-read off a screenshot.

    py -3.12 ops/docs/shots/probe_pipeline.py --port 8869 --token <tok> --repo <path>
"""
import argparse
import http.client
import json
import urllib.parse

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8869)
ap.add_argument("--token", required=True)
ap.add_argument("--repo", default="")
a = ap.parse_args()


def get(path):
    c = http.client.HTTPConnection("127.0.0.1", a.port, timeout=10)
    c.request("GET", path, headers={"Authorization": "Bearer " + a.token})
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"{}")


def show(repo):
    q = ("?repo=" + urllib.parse.quote(repo)) if repo else ""
    st, m = get("/loop/map" + q)
    rt = m.get("runtime") or {}
    print("\n--- /loop/map%s  (HTTP %d)" % (q[:60], st))
    by = {x["key"]: x for x in rt.get("lanes") or []}
    for k in ("gate", "deploy"):
        if rt.get(k):
            by[k] = rt[k]
    for k in rt.get("stations") or []:
        n = by.get(k) or {}
        print("  %-8s active=%-5s switchable=%-5s off=%-46s note=%s"
              % (k, n.get("active"), n.get("switchable"),
                 (n.get("off_reason") or "-")[:46], (n.get("note") or "-")[:46]))
    rv = m.get("repo")
    if rv:
        print("  template=%s (%s)  hook=%r" % (rv.get("template"),
                                               rv.get("template_label"), rv.get("deploy_hook")))
        print("  deviations=%s" % [d["key"] for d in rv.get("deviations") or []])


st, t = get("/repo/templates")
print("--- /repo/templates (HTTP %d)" % st)
print("  templates : %s" % [x["id"] for x in t.get("templates") or []])
print("  switchable: %s" % t.get("switchable"))
for r in t.get("repos") or []:
    print("  repo      : %-58s -> %s" % (r["repo"][-58:], r["template"] or "(kein Typ)"))

show("")
if a.repo:
    show(a.repo)
