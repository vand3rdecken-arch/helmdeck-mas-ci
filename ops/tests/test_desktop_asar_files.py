# -*- coding: utf-8 -*-
"""Every local file the Electron shell references at runtime must be in the
asar - i.e. listed under `files:` in surfaces/desktop/electron-builder.yml.

Root cause this pins (2026-09-14): preload.js was added to main.js on
2026-08-26 (5a9a830) but never added to the electron-builder `files`
allowlist, so installers 0.2.9..0.2.18 shipped a main.js whose BrowserWindow
named a preload the asar did not contain. Every packaged window logged
"Unable to load preload script ... ENOENT" and window.helmdeckNative (the
desktop update banner) was silently absent on every installed machine. Found
via DevTools on a fresh laptop install. Verified to FAIL against the pre-fix
yml (`git show 7fea69b:surfaces/desktop/electron-builder.yml`).

Static: reads the shell sources + the yml, no build needed - cheap enough for
run_gate.py. The mas config `extends` the base yml, so one list covers both.

    py -3.12 ops/tests/test_desktop_asar_files.py
"""
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DESK = os.path.join(ROOT, "surfaces", "desktop")
YML = os.environ.get("HELMDECK_BUILDER_YML") or os.path.join(DESK, "electron-builder.yml")

# Shell modules that run inside the asar. Anything they pull in by a relative
# path (`require("./x")`) or hand to Electron by `__dirname` (`path.join(
# __dirname, "x.js")`) is loaded from the asar at runtime and must ship in it.
SHELL_MODULES = ("main.js", "setup.js", "updater.js", "native-updater.js", "preload.js")
REQ_RE = re.compile(r"""require\(\s*["']\./([^"']+)["']\s*\)""")
DIRNAME_RE = re.compile(r"""path\.join\(\s*__dirname\s*,\s*["']([^"']+\.(?:js|json|html))["']\s*\)""")

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def referenced_files():
    refs = {}
    for mod in SHELL_MODULES:
        fp = os.path.join(DESK, mod)
        if not os.path.exists(fp):
            continue
        src = open(fp, encoding="utf-8").read()
        for m in REQ_RE.finditer(src):
            name = m.group(1)
            if not os.path.splitext(name)[1]:
                name += ".js"
            refs.setdefault(name, set()).add(mod)
        for m in DIRNAME_RE.finditer(src):
            refs.setdefault(m.group(1), set()).add(mod)
    return refs


def asar_files(yml_path):
    with open(yml_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    files = cfg.get("files") or []
    out = set()
    for entry in files:
        if isinstance(entry, str):
            out.add(entry.strip())
        elif isinstance(entry, dict):
            # {from, to, filter} shape - not used for the asar here, but keep
            # the test honest if someone switches to it.
            for pat in entry.get("filter") or []:
                out.add(str(pat).strip())
    return out


def main():
    print("desktop asar allowlist covers every runtime-referenced shell file")
    print("  yml: %s" % YML)
    listed = asar_files(YML)
    check("main.js" in listed, "main.js (the entry) is listed")
    check("package.json" in listed, "package.json (electron reads `main` from it) is listed")
    refs = referenced_files()
    check(bool(refs), "found runtime references in the shell sources (%d)" % len(refs))
    for name in sorted(refs):
        exists = os.path.exists(os.path.join(DESK, name))
        check(exists, "%s exists on disk (referenced by %s)" % (name, ", ".join(sorted(refs[name]))))
        check(name in listed, "%s is in electron-builder.yml files: (referenced by %s)"
              % (name, ", ".join(sorted(refs[name]))))
    print()
    if _fails:
        print("FAILED: %d" % len(_fails))
        for f in _fails:
            print("  - " + f)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
