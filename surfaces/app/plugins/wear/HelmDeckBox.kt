package app.helmdeck.wear.crypto

import android.util.Base64
import com.goterl.lazysodium.LazySodiumAndroid
import com.goterl.lazysodium.SodiumAndroid
import com.goterl.lazysodium.utils.Key
import com.goterl.lazysodium.utils.KeyPair

/**
 * NaCl box (crypto_box, Curve25519-XSalsa20-Poly1305), wired through
 * lazysodium-android (an established libsodium JNI binding) rather than
 * hand-rolled primitives. Matches spine/comms/e2ee.py and
 * surfaces/app/src/data/e2ee.ts BYTE FOR BYTE - both were read this session
 * to confirm the exact wire shape, not assumed from memory:
 *
 *   nonce = 24 random bytes  (e2ee.py's Box.NONCE_SIZE / e2ee.ts's
 *           nacl.box.nonceLength - both 24, PyNaCl's Box == tweetnacl's box)
 *   frame = nonce || ciphertext(+16-byte Poly1305 tag)
 *   wire  = base64(frame)
 *
 * WHAT IS, AND ISN'T, VERIFIED HERE - stated precisely because the two
 * halves carry different risk if wrong:
 *
 *   - THE SCHEME is confirmed against e2ee.py's own module docstring:
 *     "key exchange: Curve25519 (NaCl crypto_box)". This must be
 *     crypto_box_easy/crypto_box_open_easy, NOT crypto_box_seal - the
 *     anonymous-sender variant would be the WRONG primitive here, since
 *     e2ee.py's Box authenticates BOTH parties (a message from an
 *     unauthenticated sender should never open).
 *   - lazysodium-android's EXACT method names/parameter order were NOT
 *     confirmed against a rendered code sample this session (the project's
 *     wiki did not return usable snippets to the fetch tool available here)
 *     - only its Gradle coordinate (5.2.0) and its documented Box API shape
 *     are established. The calls below follow libsodium's own C signature
 *     for crypto_box_easy/crypto_box_open_easy
 *     (out, in, inLen, nonce, publicKey, secretKey), which JNA-style
 *     bindings conventionally mirror 1:1 - but this is the ONE thing in this
 *     file that could be wrong. If it IS wrong, Kotlin's compiler rejects it
 *     outright (a safe failure - not a silent one). What the compiler
 *     CANNOT catch is a correct-signature call with the wrong nonce or wrong
 *     key ARGUMENT ORDER (my secret key and the peer's public key, never
 *     swapped) - that needs one real round-trip test against the daemon (or
 *     a known NaCl test vector) before this is trusted, not just a clean
 *     build. First thing to check if this file fails to compile: the real
 *     method signature, via Android Studio's own go-to-definition on the
 *     installed .aar.
 */
object HelmDeckBox {
    private const val NONCE_SIZE = 24
    private const val MAC_BYTES = 16
    private val sodium by lazy { LazySodiumAndroid(SodiumAndroid()) }

    data class KeyPairB64(val secretKeyB64: String, val publicKeyB64: String)

    /** A fresh device keypair - called once, at first pairing, and persisted
     *  by DeviceStore. Never regenerated afterward: a new keypair after
     *  pairing would no longer match the pinned key in the daemon's
     *  relay.phone_pubs[] (spine/comms/relay_client.py). */
    fun generateKeyPair(): KeyPairB64 {
        val kp: KeyPair = sodium.cryptoBoxKeypair()
        return KeyPairB64(
            secretKeyB64 = Base64.encodeToString(kp.secretKey.asBytes, Base64.NO_WRAP),
            publicKeyB64 = Base64.encodeToString(kp.publicKey.asBytes, Base64.NO_WRAP),
        )
    }

    /** plaintext -> base64(nonce || ciphertext), matching e2ee.py's seal_b64()
     *  and e2ee.ts's seal(). */
    fun sealB64(plaintext: String, mySecretKeyB64: String, peerPublicKeyB64: String): String {
        // Was `ByteArray(NONCE_SIZE).also { sodium.randomBytesBuf(it, NONCE_SIZE) }`,
        // guessing libsodium's C fill-a-buffer shape. The first real Kotlin
        // compile (2026-08-28) rejected it and printed the true signature:
        // `fun randomBytesBuf(p0: Int): ByteArray!` - it ALLOCATES and returns,
        // there is no two-argument overload. Same 24 CSPRNG bytes either way.
        val nonce = sodium.randomBytesBuf(NONCE_SIZE)
        val message = plaintext.toByteArray(Charsets.UTF_8)
        val mySk = Key.fromBase64String(mySecretKeyB64).asBytes
        val peerPk = Key.fromBase64String(peerPublicKeyB64).asBytes
        val cipher = ByteArray(message.size + MAC_BYTES)
        val ok = sodium.cryptoBoxEasy(cipher, message, message.size.toLong(), nonce, peerPk, mySk)
        check(ok) { "box seal failed" }
        return Base64.encodeToString(nonce + cipher, Base64.NO_WRAP)
    }

    /** base64(nonce || ciphertext) -> plaintext, matching e2ee.py's open_b64()
     *  and e2ee.ts's open(). Throws on a tampered frame or wrong keys -
     *  callers must not treat a caught exception as "empty response". */
    fun openB64(frameB64: String, mySecretKeyB64: String, peerPublicKeyB64: String): String {
        val frame = Base64.decode(frameB64, Base64.NO_WRAP)
        check(frame.size > NONCE_SIZE + MAC_BYTES) { "frame too short to be a real box" }
        val nonce = frame.copyOfRange(0, NONCE_SIZE)
        val cipher = frame.copyOfRange(NONCE_SIZE, frame.size)
        val mySk = Key.fromBase64String(mySecretKeyB64).asBytes
        val peerPk = Key.fromBase64String(peerPublicKeyB64).asBytes
        val plain = ByteArray(cipher.size - MAC_BYTES)
        val ok = sodium.cryptoBoxOpenEasy(plain, cipher, cipher.size.toLong(), nonce, peerPk, mySk)
        check(ok) { "box open failed - tampered frame or wrong keys" }
        return String(plain, Charsets.UTF_8)
    }
}
