# -*- coding: utf-8 -*-
"""Password-unlocked signing keys + GPG-signed approval tags (the last GxP gap).

Closes debt gxp-signature-not-independently-verifiable: the signature RECORD
existed and was enforced, but it lived in storage HelmDeck owns (helmdeck.db,
events.jsonl). An auditor who asked "how do I know this record wasn't edited"
got "the append-only log" - a convention, not a proof. Now every APPROVED
signature also lands as a signed git tag, and the auditor verifies it with
stock git:

    gpg --import <user>.asc          # the signer's exported public key
    git verify-tag gxp/approve/<card>-<seq>

No HelmDeck code in that loop - which is the entire point.

WHY GPG AND NOT SSH SIGNING (measured, not preferred): the design (ops/docs/
gxp-mode-design.md 2.0) suggested gpg.format=ssh, but that landed in git 2.34
and this host runs git 2.27. GPG tag verification has worked in git for a
decade and gpg 2.2 ships inside Git for Windows, so the auditor story is
identical - only the key format changed.

THE KEY IS UNLOCKED BY THE PASSWORD, owner-chosen Option A: each user gets an
Ed25519 GPG key whose passphrase IS their HelmDeck password. Signing therefore
requires the password cryptographically, not just against a hash check -
a signature cannot be forged by patching auth.verify_password(), because
without the passphrase gpg will not produce one. The honest cost, stated in
the design and repeated here: the encrypted private key lives on this host
(daemon/signkeys/<user>/, git-ignored); a daemon compromised at the moment of
signing can capture the passphrase. That is the price of signing from a phone.

PASSWORD CHANGES ROTATE THE KEY. set_password() cannot re-encrypt the keyring
(it never sees the old password), so the first signature after a password
change fails to unlock the old key and a fresh one is generated. Old tags
stay verifiable forever: every public key ever used is exported to
signkeys/<user>/pubkeys/<fingerprint>.asc at generation time, append-only.
Key rotation is normal life for signing keys, not an anomaly.

THE TAG IS BUILT AS PLUMBING, NOT `git tag -s`: git would invoke gpg itself
and expect an interactive pinentry for the passphrase. Instead the tag object
body is composed here, detach-signed via gpg --pinentry-mode loopback (we hold
the passphrase, we pass it), the armored signature appended - which is
byte-for-byte what a signed tag IS - and `git mktag` + `git update-ref` turn
it into a real ref. `git verify-tag` cannot tell the difference, because
there is none.
"""
import json
import os
import shutil
import subprocess
import time

from daemon.paths import DAEMON_ROOT

KEYS_DIR = os.path.join(DAEMON_ROOT, "signkeys")


def _gpg_exe():
    """gpg for the daemon process. The Windows daemon runs outside git-bash,
    so PATH may not carry /usr/bin - fall back to Git for Windows' bundled
    copy, which is the one that is always there when git itself is."""
    p = shutil.which("gpg")
    if p:
        return p
    for cand in (r"C:\Program Files\Git\usr\bin\gpg.exe",
                 r"C:\Program Files (x86)\Git\usr\bin\gpg.exe"):
        if os.path.exists(cand):
            return cand
    raise RuntimeError("gpg not found - GxP approval tags need GnuPG "
                       "(ships with Git for Windows)")


def _home(user):
    d = os.path.join(KEYS_DIR, user, "gnupg")
    os.makedirs(d, exist_ok=True)
    # NO passphrase caching, written before the first agent can ever start.
    # Found by the rotation test, not by reading docs: with the default ~10min
    # agent cache, a signature "succeeded" with the WRONG passphrase because
    # the agent still held the right one from the previous signing - meaning
    # anyone with daemon access could have signed without the password for as
    # long as the cache lived. That silently converts "the password is
    # cryptographically required" into "the password was required a while
    # ago", which is exactly the claim the whole key design exists to make.
    conf = os.path.join(d, "gpg-agent.conf")
    if not os.path.exists(conf):
        with open(conf, "w", encoding="utf-8") as f:
            f.write("default-cache-ttl 0\nmax-cache-ttl 0\n")
    return d


def _bash_exe():
    for cand in (r"C:\Program Files\Git\usr\bin\bash.exe",
                 r"C:\Program Files (x86)\Git\usr\bin\bash.exe"):
        if os.path.exists(cand):
            return cand
    return shutil.which("bash")


def _run_gpg(user, args, passphrase=None, data=None, needs_agent=False):
    """One gpg call, isolated to this user's keyring via GNUPGHOME. Loopback
    pinentry because the daemon holds the passphrase - there is no terminal.

    needs_agent: key generation and signing talk to gpg-agent, and the MSYS
    gpg that ships with Git for Windows CANNOT autostart its agent from a
    native Windows process ("can't connect to the agent: Invalid value passed
    to IPC" - measured here, not read about). Those calls go through Git's own
    bash, which gives gpg the MSYS environment the agent launch expects, with
    GNUPGHOME converted by cygpath. Agent-less operations (list, export,
    import, verify) stay direct - no shell in the path when none is needed.
    The passphrase always travels as its own argv element, never interpolated
    into a shell string."""
    home = _home(user)
    gargs = ["--batch", "--no-tty", "--yes"]
    if passphrase is not None:
        gargs += ["--pinentry-mode", "loopback", "--passphrase", passphrase]
    gargs += args
    if needs_agent and os.name == "nt":
        bash = _bash_exe()
        if bash:
            # $0 = the Windows GNUPGHOME, "$@" = the untouched gpg args.
            script = 'export GNUPGHOME="$(cygpath -u "$0")"; exec gpg "$@"'
            return subprocess.run([bash, "-c", script, home] + gargs,
                                  input=data, capture_output=True)
    env = dict(os.environ, GNUPGHOME=home)
    return subprocess.run([_gpg_exe()] + gargs, input=data,
                          capture_output=True, env=env)


def _fingerprints(user):
    """Fingerprints in this user's keyring, NEWEST last (gpg lists in
    creation order). needs_agent even though it looks read-only: in GnuPG 2
    the SECRET half lives under gpg-agent's management, so --list-secret-keys
    consults the agent - measured: the direct call listed nothing while the
    key demonstrably existed."""
    r = _run_gpg(user, ["--list-secret-keys", "--with-colons"], needs_agent=True)
    return [line.split(":")[9] for line in r.stdout.decode("utf-8", "replace").splitlines()
            if line.startswith("fpr:")]


def _generate(user, password):
    """Fresh Ed25519 key, passphrase = the user's password, public half
    exported immediately - the export is what keeps OLD tags verifiable after
    a later rotation, so it is not optional hygiene."""
    uid = "%s (HelmDeck GxP) <%s@helmdeck.local>" % (user, user)
    r = _run_gpg(user, ["--quick-generate-key", uid, "ed25519", "sign", "never"],
                 passphrase=password, needs_agent=True)
    if r.returncode != 0:
        raise RuntimeError("gpg key generation failed: %s"
                           % r.stderr.decode("utf-8", "replace")[:300])
    fpr = _fingerprints(user)[-1]
    pubdir = os.path.join(KEYS_DIR, user, "pubkeys")
    os.makedirs(pubdir, exist_ok=True)
    exp = _run_gpg(user, ["--armor", "--export", fpr])
    with open(os.path.join(pubdir, fpr + ".asc"), "wb") as f:
        f.write(exp.stdout)
    return fpr


def _sign_detached(user, fpr, password, payload):
    """Armored detached signature over payload, or None if the passphrase
    does not unlock this key (the password-changed case, not an error)."""
    r = _run_gpg(user, ["--local-user", fpr, "--armor", "--detach-sign"],
                 passphrase=password, data=payload, needs_agent=True)
    if r.returncode != 0:
        return None
    return r.stdout.decode("ascii")


def sign_payload(user, password, payload):
    """Detach-sign payload with the user's current key, generating or rotating
    as needed. Returns (armored_signature, fingerprint).

    Rotation is the FALLBACK, not the default: an existing key that the
    password unlocks is reused, so a user's fingerprint stays stable between
    password changes and an auditor tracks one key per person per period."""
    fprs = _fingerprints(user)
    if fprs:
        sig = _sign_detached(user, fprs[-1], password, payload)
        if sig:
            return sig, fprs[-1]
        # Wrong passphrase on the newest key = the password changed since it
        # was generated (verify_password already vouched for the password
        # itself before we were called). Rotate.
    fpr = _generate(user, password)
    sig = _sign_detached(user, fpr, password, payload)
    if not sig:
        raise RuntimeError("freshly generated key refused its own passphrase - "
                           "gpg loopback pinentry broken?")
    return sig, fpr


def public_key_path(user, fpr):
    return os.path.join(KEYS_DIR, user, "pubkeys", fpr + ".asc")


# -- the approval tag ------------------------------------------------------

def create_approval_tag(repo, card, seq, head_sha, signer, password, manifestation):
    """Write refs/tags/gxp/approve/<card>-<seq> as a REAL signed tag on the
    approved commit. Returns (tag_name, tag_sha, fingerprint); raises on any
    failure - the caller treats an approval that cannot be independently
    anchored as a failed signature, not a cosmetic warning.

    The tag message is the manifestation itself (11.50: name, UTC time,
    meaning, reason, and the commit pair), as canonical JSON - English,
    untranslated, greppable, same standard as the event log."""
    tag_name = "gxp/approve/%s-%d" % (card, seq)
    message = json.dumps(manifestation, ensure_ascii=False, sort_keys=True)
    tagger = "%s <%s@helmdeck.local> %d +0000" % (signer, signer, int(time.time()))
    body = ("object %s\ntype commit\ntag %s\ntagger %s\n\n%s\n"
            % (head_sha, tag_name, tagger, message))

    armor, fpr = sign_payload(signer, password, body.encode("utf-8"))
    full = body + armor
    if not full.endswith("\n"):
        full += "\n"

    r = subprocess.run(["git", "-C", repo, "mktag"],
                       input=full.encode("utf-8"), capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError("git mktag refused the tag object: %s"
                           % r.stderr.decode("utf-8", "replace")[:300])
    tag_sha = r.stdout.decode().strip()
    r = subprocess.run(["git", "-C", repo, "update-ref",
                        "refs/tags/" + tag_name, tag_sha], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError("git update-ref failed: %s"
                           % r.stderr.decode("utf-8", "replace")[:300])
    return tag_name, tag_sha, fpr
