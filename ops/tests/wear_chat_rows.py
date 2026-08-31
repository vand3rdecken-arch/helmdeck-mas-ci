# -*- coding: utf-8 -*-
"""Compile and run ops/tests/wear_chat_rows.kt against the REAL Wear chat
layout model (surfaces/app/plugins/wear/ChatRows.kt).

No Gradle, no emulator, no daemon: ChatRows.kt deliberately imports nothing, so
the Kotlin compiler already sitting in this machine's Gradle cache can build it
straight to a jar and run it. That is the whole reason the layout was pulled out
of HenryScreen.kt - an index bug can only be checked against a layout that
exists as data.

Run:  py -3.12 ops/tests/wear_chat_rows.py
"""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, ".wear_rows_check")
SRC = [
    os.path.join(ROOT, "surfaces", "app", "plugins", "wear", "ChatRows.kt"),
    os.path.join(ROOT, "ops", "tests", "wear_chat_rows.kt"),
]


def one(pattern: str) -> str:
    """The newest jar matching `pattern` in the Gradle cache, or "" if none.
    Newest rather than first: the cache holds several Kotlin lines side by side
    and the compiler must not be paired with an older stdlib than it expects."""
    hits = glob.glob(os.path.join(
        os.path.expanduser("~"), ".gradle", "caches", "modules-2", "files-2.1", "**", pattern),
        recursive=True)
    return max(hits, key=os.path.getmtime) if hits else ""


def java_home() -> str:
    for d in sorted(glob.glob("C:/Program Files/Microsoft/jdk-17*")):
        return d
    return os.environ.get("JAVA_HOME", "")


def main() -> int:
    jh = java_home()
    if not jh:
        print("SKIP: no JDK 17 (winget install Microsoft.OpenJDK.17)")
        return 0
    compiler = one("kotlin-compiler-embeddable-*.jar")
    if not compiler:
        print("SKIP: kotlin compiler not in the Gradle cache - "
              "run ops/deploy/build_wear_apk.sh once to populate it")
        return 0
    # The stdlib must MATCH the compiler: the embeddable jar carries no runtime
    # of its own, and pairing 2.1.x with a 2.2.x stdlib is how this first failed
    # (NoClassDefFoundError kotlin/jvm/internal/Intrinsics).
    ver = os.path.basename(compiler).replace("kotlin-compiler-embeddable-", "").replace(".jar", "")
    stdlib = one("kotlin-stdlib-%s.jar" % ver) or one("kotlin-stdlib-2*.jar")
    if not stdlib:
        print("SKIP: kotlin stdlib not in the Gradle cache")
        return 0
    print("kotlinc:", os.path.basename(compiler))
    print("stdlib :", os.path.basename(stdlib))

    # The embeddable compiler shades most of its dependencies but NOT all of
    # them: it needs coroutines and trove4j at runtime (ClassNotFoundException
    # kotlinx.coroutines.CoroutineScope on the first attempt). All of these are
    # already in the cache because :wear itself pulls them.
    extra = [one(p) for p in (
        "kotlin-reflect-*.jar", "kotlin-script-runtime-*.jar",
        "kotlin-daemon-embeddable-*.jar", "kotlinx-coroutines-core-jvm-*.jar",
        "trove4j-*.jar", "annotations-2*.jar",
    )]
    cp = os.pathsep.join([compiler, stdlib] + [j for j in extra if j])

    java = os.path.join(jh, "bin", "java.exe")
    classes = os.path.join(OUT, "classes")
    os.makedirs(classes, exist_ok=True)
    # The embeddable compiler is a normal jar with the CLI entrypoint inside;
    # calling it directly avoids needing a kotlinc distribution on PATH.
    # Plain class output, NOT `-include-runtime`: bundling the runtime makes the
    # compiler look for a kotlinc HOME layout it does not have here, and the
    # stdlib is on the run classpath below anyway.
    cc = subprocess.run(
        [java, "-cp", cp, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
         *SRC, "-classpath", stdlib, "-d", classes, "-nowarn"],
        capture_output=True, text=True)
    # kotlinc writes progress to stderr even on success; only a non-zero code is
    # a failure, and then the whole message is worth showing.
    if cc.returncode != 0:
        print(cc.stdout)
        print(cc.stderr)
        print("RESULT: FAIL (compile)")
        return 1
    for line in (cc.stderr or "").splitlines():
        if "error" in line.lower():
            print(line)

    run = subprocess.run(
        [java, "-cp", os.pathsep.join([classes, stdlib]), "helmdeck.check.Wear_chat_rowsKt"],
        capture_output=True, text=True)
    print(run.stdout, end="")
    if run.stderr.strip():
        print(run.stderr, end="")
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
