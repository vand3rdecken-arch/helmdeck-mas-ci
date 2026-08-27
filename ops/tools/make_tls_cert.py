# -*- coding: utf-8 -*-
"""Mint a self-signed TLS certificate for the daemon's https listener
(pays debt [single-secret-transport] together with server._tls_config).

    py -3.12 ops/tools/make_tls_cert.py [extra-hostname-or-ip ...]

Writes daemon/certs/tls.crt + tls.key (git-ignored; the daemon auto-detects
them on next start and moves plain http to loopback-only). SANs cover
localhost, this machine's hostname and every LAN IP found, plus any extras
passed on the command line - so browsers pin the same cert whichever address
you use.

Self-signed means clients see a trust warning ONCE (browsers: accept; Android
refuses untrusted certs outright - phones should use the relay or a tunnel).
For a cert that is trusted everywhere without warnings, use Tailscale instead:

    tailscale up
    tailscale cert <your-machine>.<tailnet>.ts.net
    set HELMDECK_TLS_CERT/HELMDECK_TLS_KEY to the two files it writes

(825-day validity: Apple/Android reject longer-lived leaf certs even when
manually trusted, so a longer cert would HELP nothing and break iOS.)"""
import datetime
import ipaddress
import os
import socket
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

DAYS = 825
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   os.pardir, "daemon", "certs")


def lan_ips():
    """Every address this box answers on: hostname lookup + the UDP-connect
    trick (finds the outbound-facing IP without sending a packet)."""
    ips = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 80))     # TEST-NET: never actually sent
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("169.254."))


def main():
    host = socket.gethostname()
    names, ips = {"localhost", host}, {"127.0.0.1"} | set(lan_ips())
    for extra in sys.argv[1:]:
        try:
            ipaddress.ip_address(extra)
            ips.add(extra)
        except ValueError:
            names.add(extra)
    san = x509.SubjectAlternativeName(
        [x509.DNSName(n) for n in sorted(names)] +
        [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)])

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HelmDeck daemon (" + host + ")")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=DAYS))
            .add_extension(san, critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))

    os.makedirs(OUT, exist_ok=True)
    crt, kf = os.path.join(OUT, "tls.crt"), os.path.join(OUT, "tls.key")
    with open(crt, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(kf, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    try:
        os.chmod(kf, 0o600)              # best effort; no-op semantics on Windows
    except OSError:
        pass

    print("wrote %s" % crt)
    print("wrote %s  (private key - stays on this machine)" % kf)
    print("SANs: %s" % ", ".join(sorted(names) + sorted(ips)))
    print("valid: %d days (Apple/Android cap for leaf certs)" % DAYS)
    print()
    print("Restart the daemon: it auto-detects these files and serves")
    print("  https on :8443 (HELMDECK_TLS_PORT / settings.tls.port to change)")
    print("  plain http on LOOPBACK ONLY - nothing cleartext on the LAN.")


if __name__ == "__main__":
    main()
