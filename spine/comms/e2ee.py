# -*- coding: utf-8 -*-
"""End-to-end encryption for the relay path - byte-for-byte compatible with
Paseo's scheme (packages/surfaces/relay/src/crypto.ts) so the wire format is a known
quantity:

  * key exchange : Curve25519  (NaCl crypto_box / box.before)
  * encryption   : XSalsa20-Poly1305  (NaCl crypto_box / box.after)
  * frame        : [nonce (24 bytes)][ciphertext(+16-byte tag)]

PyNaCl's Box == NaCl crypto_box == tweetnacl's box, so a frame sealed here opens
in the phone's tweetnacl/libsodium and vice-versa. The relay only ever sees the
frame bytes (opaque) - it cannot read or forge traffic."""
import base64
from nacl.public import PrivateKey, PublicKey, Box
from nacl.utils import random as _random

NONCE = Box.NONCE_SIZE  # 24


def generate_keypair():
    sk = PrivateKey.generate()
    return sk, sk.public_key


def export_pub(pk):
    return base64.b64encode(bytes(pk)).decode()


def import_pub(b64):
    return PublicKey(base64.b64decode(b64))


def export_sec(sk):
    return base64.b64encode(bytes(sk)).decode()


def import_sec(b64):
    return PrivateKey(base64.b64decode(b64))


def seal(plaintext, my_sk, peer_pk, nonce=None):
    """plaintext bytes -> frame bytes (nonce||ciphertext)."""
    box = Box(my_sk, peer_pk)
    if nonce is None:
        nonce = _random(NONCE)
    return bytes(box.encrypt(plaintext, nonce))   # PyNaCl prepends the nonce


def open_frame(frame, my_sk, peer_pk):
    """frame bytes (nonce||ciphertext) -> plaintext bytes; raises on tamper."""
    return Box(my_sk, peer_pk).decrypt(frame)


def seal_b64(plaintext, my_sk, peer_pk):
    return base64.b64encode(seal(plaintext, my_sk, peer_pk)).decode()


def open_b64(frame_b64, my_sk, peer_pk):
    return open_frame(base64.b64decode(frame_b64), my_sk, peer_pk)
