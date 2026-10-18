# -*- coding: utf-8 -*-
"""ops/tools/private_guard.py refuses private content - against a REAL git repo and the REAL hook.

  1. the rule parser reads path:/regex lines, skips comments;
  2. an added line matching a term is refused with file:line; a removed line is not (deleting private
     data must stay possible);
  3. a file under a private path is refused;
  4. end to end: a throw-away repo whose pre-commit runs the guard (with a throw-away rule list) refuses
     a commit carrying a term and accepts a clean one.

Never reads or prints the owner's real list: every rule here is made up.
Run: py -3.12 ops/tests/test_private_guard.py
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
spec = importlib.util.spec_from_file_location("pg", os.path.join(ROOT, "ops", "tools", "private_guard.py"))
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)
_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="hd-guard-")
    try:
        rules_file = os.path.join(tmp, "rules.txt")
        open(rules_file, "w", encoding="utf-8").write("# comment\n\\bZZQX\\b\npath:secret/area\n")
        paths, terms = pg.load_rules(rules_file)
        check(paths == ["secret/area"] and len(terms) == 1, "the list parses: one path, one term, comment skipped")

        diff = ("+++ b/a.py\n@@ -0,0 +1,3 @@\n+fine\n+holding ZZQX here\n+fine\n"
                "+++ b/b.py\n@@ -5 +5 @@\n-old zzqx line\n+new clean line\n")
        bad = pg.check(diff, ["a.py", "b.py", "secret/area/x.md"], (paths, terms))
        check(("a.py", 2, "matches a private term (\\bZZQX\\b)") in bad, "an added line with a term is refused at file:line (%s)" % bad[:1])
        check(not any(f == "b.py" for f, _, _ in bad), "a REMOVED line with the term is allowed - deleting private data must stay possible")
        check(any(f == "secret/area/x.md" for f, _, _ in bad), "a file under a private path is refused")

        # end to end through a real git hook
        repo = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(repo, "ops", "tools"))
        shutil.copy2(os.path.join(ROOT, "ops", "tools", "private_guard.py"), os.path.join(repo, "ops", "tools"))
        g = lambda *a, **k: subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=" + os.path.join(repo, ".hooks"), *a],
                                          capture_output=True, text=True, **k)
        subprocess.run(["git", "init", "-q", repo], check=True)
        g("config", "user.email", "t@example.invalid"); g("config", "user.name", "t")
        os.makedirs(os.path.join(repo, ".hooks"))
        hook = os.path.join(repo, ".hooks", "pre-commit")
        open(hook, "w", newline="\n").write(
            "#!/bin/sh\nexec \"%s\" \"$(git rev-parse --show-toplevel)/ops/tools/private_guard.py\"\n" % sys.executable.replace("\\", "/"))
        os.chmod(hook, 0o755)
        env = dict(os.environ, USERPROFILE=tmp, HOME=tmp)
        os.makedirs(os.path.join(tmp, ".helmdeck"))
        shutil.copy2(rules_file, os.path.join(tmp, ".helmdeck", "publish_private.txt"))
        open(os.path.join(repo, "a.txt"), "w").write("clean\n")
        g("add", "-A", env=env)
        r = g("commit", "-q", "-m", "clean", env=env)
        check(r.returncode == 0, "a clean commit passes the hook (%s)" % r.stderr.strip()[:120])
        open(os.path.join(repo, "a.txt"), "a").write("my zzqx position\n")
        g("add", "-A", env=env)
        r = g("commit", "-q", "-m", "leak", env=env)
        check(r.returncode != 0 and "COMMIT REFUSED" in r.stderr and "a.txt:2" in r.stderr,
              "a commit with a private term is REFUSED by the real hook, naming a.txt:2")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("private guard: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
