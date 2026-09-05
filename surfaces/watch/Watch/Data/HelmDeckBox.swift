import Foundation
import Sodium

/// NaCl box (crypto_box, Curve25519-XSalsa20-Poly1305) via swift-sodium -
/// the Swift sibling of app.helmdeck.wear.crypto.HelmDeckBox (Kotlin,
/// lazysodium-android) and of e2ee.py/e2ee.ts. All three must agree on the
/// exact wire shape, confirmed against swift-sodium's own Box.swift source
/// this session (github.com/jedisct1/swift-sodium, tag 0.11.0), not guessed:
///
///   nonce = 24 random bytes
///   frame = nonce || ciphertext(+16-byte Poly1305 tag)
///   wire  = base64(frame)
///
/// `sodium.box.seal(message:recipientPublicKey:senderSecretKey:) -> Bytes?`
/// returns exactly `nonce + authenticatedCipherText` (crypto_box_easy under
/// the hood) - the combined-nonce overload, not the seal-anonymous variant
/// (`crypto_box_seal`, single-recipient-key only) which would be the WRONG
/// primitive here for the same reason HelmDeckBox.kt's own comment gives:
/// e2ee.py's Box authenticates BOTH parties, so a message from an
/// unauthenticated sender must never open.
///
/// UNVERIFIED AT RUNTIME (stated plainly, same as the Kotlin file's own
/// caveat): this worktree has no watch/simulator to round-trip against the
/// real daemon. What IS verified is the API shape itself, read from the
/// package's source rather than assumed - a signature mismatch fails the
/// Xcode build loudly, not silently.
enum HelmDeckBox {
    private static let sodium = Sodium()
    private static let nonceSize = 24
    private static let macBytes = 16

    struct KeyPairB64 {
        let secretKeyB64: String
        let publicKeyB64: String
    }

    /// A fresh device keypair - called once, at first pairing, and persisted
    /// by DeviceStore. Never regenerated afterward: a new keypair after
    /// pairing would no longer match the pinned key in the daemon's
    /// relay.phone_pubs[].
    static func generateKeyPair() -> KeyPairB64? {
        guard let kp = sodium.box.keyPair() else { return nil }
        return KeyPairB64(
            secretKeyB64: Data(kp.secretKey).base64EncodedString(),
            publicKeyB64: Data(kp.publicKey).base64EncodedString())
    }

    /// plaintext -> base64(nonce || ciphertext), matching e2ee.py's seal_b64()
    /// and e2ee.ts's seal().
    static func sealB64(_ plaintext: String, mySecretKeyB64: String, peerPublicKeyB64: String) -> String? {
        guard let mySk = Data(base64Encoded: mySecretKeyB64),
              let peerPk = Data(base64Encoded: peerPublicKeyB64),
              let message = plaintext.data(using: .utf8)
        else { return nil }
        // Explicit `Bytes?` annotation: swift-sodium overloads `seal(message:
        // recipientPublicKey:senderSecretKey:)` three ways, distinguished
        // ONLY by return type (plain `Bytes?` = nonce+cipher combined, vs. two
        // tuple forms that separate the nonce/mac back out) - without this
        // annotation the call is ambiguous to the compiler, not just to a
        // reader.
        let sealed: Bytes? = sodium.box.seal(
            message: Bytes(message), recipientPublicKey: Bytes(peerPk), senderSecretKey: Bytes(mySk))
        guard let frame = sealed else { return nil }
        return Data(frame).base64EncodedString()
    }

    /// base64(nonce || ciphertext) -> plaintext, matching e2ee.py's open_b64()
    /// and e2ee.ts's open(). Returns nil on a tampered frame or wrong keys -
    /// callers must not treat nil as "empty response".
    static func openB64(_ frameB64: String, mySecretKeyB64: String, peerPublicKeyB64: String) -> String? {
        guard let frame = Data(base64Encoded: frameB64), frame.count > nonceSize + macBytes,
              let mySk = Data(base64Encoded: mySecretKeyB64),
              let peerPk = Data(base64Encoded: peerPublicKeyB64)
        else { return nil }
        guard let plain = sodium.box.open(
            nonceAndAuthenticatedCipherText: Bytes(frame), senderPublicKey: Bytes(peerPk), recipientSecretKey: Bytes(mySk))
        else { return nil }
        return String(data: Data(plain), encoding: .utf8)
    }
}
