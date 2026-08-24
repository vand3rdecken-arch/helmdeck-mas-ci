import "react-native-get-random-values"; // polyfills crypto.getRandomValues for tweetnacl
import nacl from "tweetnacl";
import util from "tweetnacl-util";

// Byte-for-byte compatible with daemon/e2ee.py (PyNaCl Box == tweetnacl box):
//   key exchange Curve25519, cipher XSalsa20-Poly1305,
//   frame = base64( nonce(24) || ciphertext(+16 tag) ).
// So a frame sealed here opens on the daemon and vice-versa.

export function generateKeyPair() {
  const kp = nacl.box.keyPair();
  return { pub: util.encodeBase64(kp.publicKey), sec: util.encodeBase64(kp.secretKey) };
}

export function seal(plaintext: string, mySecB64: string, peerPubB64: string): string {
  const nonce = nacl.randomBytes(nacl.box.nonceLength);
  const ct = nacl.box(util.decodeUTF8(plaintext), nonce, util.decodeBase64(peerPubB64), util.decodeBase64(mySecB64));
  const frame = new Uint8Array(nonce.length + ct.length);
  frame.set(nonce);
  frame.set(ct, nonce.length);
  return util.encodeBase64(frame);
}

export function open(frameB64: string, mySecB64: string, peerPubB64: string): string {
  const frame = util.decodeBase64(frameB64);
  const nonce = frame.slice(0, nacl.box.nonceLength);
  const ct = frame.slice(nacl.box.nonceLength);
  const msg = nacl.box.open(ct, nonce, util.decodeBase64(peerPubB64), util.decodeBase64(mySecB64));
  if (!msg) throw new Error("decrypt failed (key mismatch or tamper)");
  return util.encodeUTF8(msg);
}
