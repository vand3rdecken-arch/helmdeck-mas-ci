"""Jev (TypeSafe System One) as a shared cheap classifier for every card.

  py -3.12 ops/tools/jev.py --question "Which district?" --options "Mitte,Nord,unbekannt" --context "Altbau 3 Zi. Prenzlauer Berg"
  py -3.12 ops/tools/jev.py --batch [--fallback sonnet] [--threshold 0.7] < in.jsonl > out.jsonl

Batch in: one JSON per line {"question","options","context"[, "id"]} (--question/--options act as defaults).
Out: {"id","choice","confidence","uncertain","source":"jev|sonnet|cache"}; a cost line goes to stderr.
Call path = alphaloop / ops/tools/research/jev_loop_probe.py: POST api.typesafe.ai systemone, jev-latest, one choice
question, state = small JSON, 6 parallel, 3 retries. Key: TYPESAFE_API_KEY from the env, else the repo-root .env;
never printed.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
URL = "https://api.typesafe.ai/v1/systemone"
USD_PER_TOK = 0.042 / 1e6
CACHE = os.path.join(tempfile.gettempdir(), "jev_cache")


def _key():
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k
    p = os.path.join(ROOT, ".env")
    try:
        for line in open(p, encoding="utf-8-sig"):
            if line.startswith("TYPESAFE_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError as e:
        sys.exit(f"jev: cannot read {p} ({type(e).__name__}); set TYPESAFE_API_KEY")
    sys.exit("jev: no TYPESAFE_API_KEY in env or repo .env")


def _opts(o):
    return [x.strip() for x in o.split(",")] if isinstance(o, str) else list(o)


def _jev(item, key):
    q = {"type": "choice", "instructions": item["question"] + " Read `context`.",
         "criteria": {o: o for o in item["options"]}}
    body = json.dumps({"state": {"context": item["context"]}, "model": "jev-latest", "questions": {"q": q}}).encode()
    req = urllib.request.Request(URL, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    err = ""
    for attempt in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=60))
            a = r["answers"]["q"]
            return a.get("choice"), a.get("confidence") or 0.0, (r.get("usage") or {}).get("input_tokens", 0)
        except Exception as e:  # noqa: BLE001 - retry, then report as uncertain
            err = type(e).__name__
            time.sleep(1 + attempt)
    return None, 0.0, 0


def _sonnet(item):
    prompt = (item["question"] + "\nOptions: " + " | ".join(item["options"]) + "\nContext:\n" + item["context"]
              + "\nAnswer with exactly one option and nothing else.")
    p = subprocess.run(["claude.cmd", "-p", "--model", "sonnet", "--output-format", "json", "--tools", "",
                        "--system-prompt", "You are a strict classifier.", "--no-session-persistence"],
                       input=prompt, capture_output=True, text=True, timeout=180, cwd=tempfile.gettempdir(), encoding="utf-8")
    j = json.loads(p.stdout)
    res = j.get("result", "").strip()
    pick = next((o for o in item["options"] if o.lower() == res.lower()), None) or \
        next((o for o in item["options"] if re.search(re.escape(o), res, re.I)), None)
    return pick, j.get("total_cost_usd", 0.0)


def classify(item, key, threshold=0.7, fallback=None, cache=True):
    """item: {question, options, context}. Returns dict(choice, confidence, uncertain, source, usd)."""
    item = {**item, "options": _opts(item["options"]), "context": str(item["context"])}
    h = hashlib.sha256(json.dumps([item["question"], item["options"], item["context"], threshold, fallback],
                                  ensure_ascii=False).encode()).hexdigest()
    f = os.path.join(CACHE, h + ".json")
    if cache and os.path.exists(f):
        return {**json.load(open(f, encoding="utf-8")), "source": "cache", "usd": 0.0}
    choice, conf, tok = _jev(item, key)
    out = {"choice": choice, "confidence": conf, "uncertain": choice not in item["options"] or conf < threshold,
           "source": "jev", "usd": tok * USD_PER_TOK}
    if out["uncertain"] and fallback == "sonnet":
        try:
            pick, usd = _sonnet(item)
            if pick:
                out.update(choice=pick, uncertain=False, source="sonnet", usd=out["usd"] + usd)
        except Exception as e:  # noqa: BLE001 - keep the jev answer, flagged uncertain
            out["fallback_error"] = type(e).__name__
    if cache and choice:
        os.makedirs(CACHE, exist_ok=True)
        json.dump({k: out[k] for k in ("choice", "confidence", "uncertain", "source")},
                  open(f, "w", encoding="utf-8"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--question")
    ap.add_argument("--options")
    ap.add_argument("--context")
    ap.add_argument("--batch", action="store_true", help="JSON lines on stdin")
    ap.add_argument("--fallback", choices=["sonnet"])
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    items = [json.loads(line) for line in sys.stdin if line.strip()] if a.batch else [{}]
    for i, it in enumerate(items):
        it.setdefault("id", i)
        it.setdefault("question", a.question)
        it.setdefault("options", a.options)
        it.setdefault("context", a.context)
        if not (it["question"] and it["options"] and it["context"] is not None):
            sys.exit("jev: question, options and context are required")
    key = _key()
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda it: classify(it, key, a.threshold, a.fallback, not a.no_cache), items))
    for it, r in zip(items, res):
        print(json.dumps({"id": it["id"], **{k: r[k] for k in ("choice", "confidence", "uncertain", "source")}},
                         ensure_ascii=False))
    n = lambda s: sum(r["source"] == s for r in res)  # noqa: E731
    print(f"jev: {len(res)} items, jev={n('jev')} sonnet={n('sonnet')} cache={n('cache')}, "
          f"uncertain={sum(r['uncertain'] for r in res)}, cost=${sum(r['usd'] for r in res):.5f}", file=sys.stderr)


if __name__ == "__main__":
    main()
