# -*- coding: utf-8 -*-
"""Build the Microsoft Store package (MSIX) of the TAURI desktop shell. Builds only - never submits.

    py -3.12 ops/deploy/build_msix_tauri.py --version 0.3.0             # cargo build + stage + makeappx
    py -3.12 ops/deploy/build_msix_tauri.py --version 0.3.0 --no-build  # reuse target/release/helmdeck-desktop.exe

Output: surfaces/desktop/tauri-app/target/msix/HelmDeck-<version>-x64.msix (UNSIGNED - Partner Center signs on
upload, the same as build_msix.ps1 does for the Electron package).

What goes in is an ALLOWLIST, the same one electron-builder.yml uses (that list was a denylist once, and a
Firebase private key, live session tokens and a sqlite backup shipped in a public installer): top-level
daemon/*.py|*.md|requirements.txt, spine/** and cells/** *.py|*.md, cells/**/harness/settings/*.json,
ops/harness agents|settings|schema|templates, and the built web app as app-dist. After staging, the stage is
scanned for secret-shaped files and the build FAILS if one is found.

Identity: Partner Center assigns Name and Publisher. They are read from the git-ignored
surfaces/desktop/build/appx-identity.json (or HELMDECK_APPX_IDENTITY_NAME / _PUBLISHER / _PUBLISHER_DISPLAY_NAME);
without them placeholders are used, which is fine for a manifest check and useless for the Store.

The Store version must be HIGHER than what the listing already has (the Electron package is 0.2.x).
"""
import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESKTOP = os.path.join(ROOT, "surfaces", "desktop")
APP = os.path.join(DESKTOP, "tauri-app")
OUT = os.path.join(APP, "target", "msix")
STAGE = os.path.join(OUT, "stage")
EXE_NAME = "HelmDeck.exe"

# (source dir relative to ROOT, target dir in the package, recursive?, patterns)
ALLOW = [
    ("daemon", "daemon", False, ["*.py", "*.md", "requirements.txt"]),
    ("spine", "spine", True, ["*.py", "*.md"]),
    ("cells", "cells", True, ["*.py", "*.md"]),
    ("ops/harness/agents", "ops/harness/agents", False, ["*.md"]),
    ("ops/harness/settings", "ops/harness/settings", False, ["*.json"]),
    ("ops/harness/schema", "ops/harness/schema", False, ["*.json"]),
    ("ops/harness/templates", "ops/harness/templates", False, ["*.md"]),
]
SKIP_DIRS = {"__pycache__", ".versions", "node_modules", ".git"}

# names/contents that must never be in a package, whatever the allowlist let through
SECRET_NAMES = ["settings.json", "users.json", "sessions.json", "fcm_service_account.json", "*.db", "*.db-*",
                "*.sqlite", "*.key", "*.pem", "*.pfx", ".env", "*.dpapi"]
SECRET_CONTENT = [re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"), re.compile(rb'"private_key"\s*:')]


def copy_allowlist():
    n = 0
    for src, dst, recursive, pats in ALLOW:
        base = os.path.join(ROOT, src)
        for dirpath, dirnames, files in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel = os.path.relpath(dirpath, base)
            if not recursive and rel != ".":
                continue
            for f in files:
                if any(fnmatch.fnmatch(f, p) for p in pats):
                    target = os.path.join(STAGE, dst, rel, f)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(os.path.join(dirpath, f), target)
                    n += 1
    # cells/<id>/harness/settings/*.json (the cells' policy settings)
    for f in glob.glob(os.path.join(ROOT, "cells", "**", "harness", "settings", "*.json"), recursive=True):
        rel = os.path.relpath(f, ROOT)
        target = os.path.join(STAGE, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(f, target)
        n += 1
    return n


def scan_for_secrets():
    hits = []
    for dirpath, _, files in os.walk(STAGE):
        for f in files:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, STAGE)
            if rel.startswith("app-dist" + os.sep) and f.endswith((".js", ".map", ".css", ".html", ".png", ".ttf", ".svg", ".ico", ".json", ".woff", ".woff2")):
                if f.endswith((".png", ".ttf", ".ico", ".woff", ".woff2")):
                    continue
            if any(fnmatch.fnmatch(f.lower(), pat) for pat in SECRET_NAMES):
                # the harness's own settings json files are policy, not secrets - allowed by path
                if not (rel.replace(os.sep, "/").startswith(("ops/harness/settings/", "cells/")) and "/harness/settings/" in "/" + rel.replace(os.sep, "/")
                        or rel.replace(os.sep, "/").startswith("ops/harness/settings/")):
                    hits.append(rel + " (name)")
                    continue
            try:
                with open(p, "rb") as fh:
                    data = fh.read(4 * 1024 * 1024)
            except OSError:
                continue
            if any(rx.search(data) for rx in SECRET_CONTENT):
                hits.append(rel + " (content)")
    return hits


def identity():
    ident = {"identityName": "HelmDeck.Placeholder", "publisher": "CN=ms", "publisherDisplayName": "HelmDeck"}
    f = os.path.join(DESKTOP, "build", "appx-identity.json")
    if os.path.isfile(f):
        ident.update(json.load(open(f, encoding="utf-8")))
    for k, env in (("identityName", "HELMDECK_APPX_IDENTITY_NAME"), ("publisher", "HELMDECK_APPX_PUBLISHER"),
                   ("publisherDisplayName", "HELMDECK_APPX_PUBLISHER_DISPLAY_NAME")):
        if os.environ.get(env):
            ident[k] = os.environ[env]
    return ident


def manifest(version, ident):
    e = lambda s: escape(s, {'"': "&quot;"})
    return """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap desktop rescap">
  <Identity Name="{name}" Publisher="{publisher}" Version="{version}.0" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>HelmDeck</DisplayName>
    <PublisherDisplayName>{pdn}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-US" />
    <Resource Language="de-DE" />
  </Resources>
  <Applications>
    <Application Id="HelmDeck" Executable="{exe}" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="HelmDeck" Description="HelmDeck"
                          BackgroundColor="#0b0f14"
                          Square150x150Logo="Assets\\Square150x150Logo.png"
                          Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png" Square310x310Logo="Assets\\LargeTile.png" Square71x71Logo="Assets\\SmallTile.png" />
        <uap:SplashScreen Image="Assets\\SplashScreen.png" />
      </uap:VisualElements>
      <Extensions>
        <!-- DECLARED but disabled: Store review expects opt-in by the user, never at first launch -->
        <desktop:Extension Category="windows.startupTask" Executable="{exe}" EntryPoint="Windows.FullTrustApplication">
          <desktop:StartupTask TaskId="HelmDeckStartup" Enabled="false" DisplayName="HelmDeck" />
        </desktop:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <Capability Name="internetClient" />
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
""".format(name=e(ident["identityName"]), publisher=e(ident["publisher"]), pdn=e(ident["publisherDisplayName"]),
           version=version, exe=EXE_NAME)


def makeappx():
    kits = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\10.*\x64\makeappx.exe"))
    if kits:
        return kits[-1]
    cached = glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "electron-builder", "Cache", "winCodeSign", "*", "windows-10", "x64", "makeappx.exe"))
    if cached:
        return cached[0]
    sys.exit("makeappx.exe not found (install the Windows 10/11 SDK)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="x.y.z - must be higher than the listing's current package")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit("--version must be x.y.z")
    exe = os.path.join(APP, "target", "release", "helmdeck-desktop.exe")
    if not a.no_build:
        subprocess.run(["cargo", "build", "--release"], cwd=APP, check=True)
    if not os.path.isfile(exe):
        sys.exit("no release build at " + exe)
    dist = os.path.join(ROOT, "surfaces", "app", "dist")
    if not os.path.isfile(os.path.join(dist, "index.html")):
        sys.exit("no web build at surfaces/app/dist (cd surfaces/app && npx expo export -p web)")

    shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(STAGE)
    shutil.copy2(exe, os.path.join(STAGE, EXE_NAME))
    shutil.copytree(dist, os.path.join(STAGE, "app-dist"))
    n = copy_allowlist()
    os.makedirs(os.path.join(STAGE, "Assets"))
    for f in glob.glob(os.path.join(DESKTOP, "build", "appx", "*.png")):
        shutil.copy2(f, os.path.join(STAGE, "Assets", os.path.basename(f)))
    ident = identity()
    with open(os.path.join(STAGE, "AppxManifest.xml"), "w", encoding="utf-8") as fh:
        fh.write(manifest(a.version, ident))

    hits = scan_for_secrets()
    if hits:
        sys.exit("REFUSING to package - secret-shaped files in the stage:\n  " + "\n  ".join(hits))

    out = os.path.join(OUT, "HelmDeck-%s-x64.msix" % a.version)
    r = subprocess.run([makeappx(), "pack", "/d", STAGE, "/p", out, "/o"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("makeappx failed:\n" + (r.stdout + r.stderr)[-3000:])
    size = os.path.getsize(out) / 1e6
    print("staged %d source files, web app, %s" % (n, EXE_NAME))
    print("identity: %s%s" % (ident["identityName"] if ident["identityName"] == "HelmDeck.Placeholder" else "<from appx-identity.json>",
                              "" if ident["publisher"] != "CN=ms" else " (PLACEHOLDER - not uploadable)"))
    print("package : %s (%.1f MB, unsigned - Partner Center signs on upload)" % (out, size))


if __name__ == "__main__":
    main()
