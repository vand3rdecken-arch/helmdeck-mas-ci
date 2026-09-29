# -*- coding: utf-8 -*-
"""Look up REAL code in a reference project - BEST PRACTICE FIRST needs source,
not recall (owner 2026-09-29). ONE call, prints file + excerpt.

    py -3.12 ops/tools/ref_code.py paseo "turn_completed"          # known alias
    py -3.12 ops/tools/ref_code.py getpaseo/paseo "replaceAgentRun" # any owner/name
    py -3.12 ops/tools/ref_code.py "how do apps debounce typing" "debounce"  # not a repo:
                                                                    # gh search code across GitHub

owner/name: shallow clone (depth 1) into a cache OUTSIDE the worktree
(%LOCALAPPDATA%/helmdeck/ref_cache), then `git grep` it - the excerpts are
PRINTED here, so the worker never has to Read the cache path (card_tool_guard
denies reads outside the worktree, by design). Aliases with a local checkout use
that instead of cloning. Every hit is logged to <worktree>/.refs.log (git-ignored)
- the delivered-parked escalation reports it as "Vorbild-Code gelesen".
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "helmdeck" / "ref_cache"
# alias -> (owner/name, local checkout that beats a clone). Reference projects the
# repo docs name (ops/docs/paseo-adoption-plan.md, glasses-reference.md).
ALIASES = {
    "paseo": ("getpaseo/paseo", Path.home() / "Downloads" / "_paseo_src"),
    "meta-wearables-ios": ("facebook/meta-wearables-dat-ios", None),
    "meta-wearables-android": ("facebook/meta-wearables-dat-android", None),
}
MAX_FILES, MAX_LINES = 6, 14         # bounded output: a screenful, not a dump


def _run(*cmd, cwd=None):
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)


def _log(repo, path):
    with open(ROOT / ".refs.log", "a", encoding="utf-8") as f:
        f.write("%s:%s\n" % (repo, path))


def _checkout(repo, local):
    if local and (Path(local) / ".git").exists():
        return Path(local)
    dest = CACHE / repo.replace("/", "__")
    if not dest.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        r = _run("git", "clone", "--depth", "1", "-q", "https://github.com/%s.git" % repo, str(dest))
        if r.returncode:
            sys.exit("clone failed: " + r.stderr.strip()[:200])
    return dest


def repo_search(repo, local, term):
    d = _checkout(repo, local)
    r = _run("git", "grep", "-n", "-I", "-i", "-F", "-C", "2", "-e", term, cwd=str(d))
    files = {}                                   # path -> excerpt lines, in order
    for line in r.stdout.splitlines():
        if line == "--":
            continue
        # "path-12-text" (context) or "path:12:text" (match); paths hold no ':'
        for sep in (":", "-"):
            head, _, rest = line.partition(sep)
            if head and rest[:1].isdigit():
                files.setdefault(head, []).append("  " + rest)
                break
    if not files:
        print("no hit for %r in %s" % (term, repo))
        return
    for path, lines in list(files.items())[:MAX_FILES]:
        print("== %s:%s" % (repo, path))
        print("\n".join(lines[:MAX_LINES]))
        _log(repo, path)
    if len(files) > MAX_FILES:
        print("(+%d more files - narrow the term)" % (len(files) - MAX_FILES))


def gh_search(term):
    r = _run("gh", "search", "code", term, "--limit", "%d" % MAX_FILES,
             "--json", "repository,path,textMatches")
    if r.returncode:
        sys.exit("gh search failed: " + r.stderr.strip()[:200])
    import json
    hits = json.loads(r.stdout or "[]")
    if not hits:
        print("no hit for %r on GitHub" % term)
    for h in hits:
        repo = h["repository"]["nameWithOwner"]
        print("== %s:%s" % (repo, h["path"]))
        for m in (h.get("textMatches") or [])[:1]:
            print("\n".join("  " + l for l in m.get("fragment", "").splitlines()[:MAX_LINES]))
        _log(repo, h["path"])


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # cp1252 console vs repo text
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    what, term = sys.argv[1], sys.argv[2]
    if what in ALIASES:
        repo_search(ALIASES[what][0], ALIASES[what][1], term)
    elif "/" in what and " " not in what:
        repo_search(what, None, term)
    else:
        gh_search(term)                          # `what` is the question; the term is what is searched


if __name__ == "__main__":
    main()
