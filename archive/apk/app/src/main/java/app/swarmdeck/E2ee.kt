package app.swarmdeck

import android.util.Base64
import com.goterl.lazysodium.LazySodiumAndroid
import com.goterl.lazysodium.SodiumAndroid
import com.goterl.lazysodium.interfaces.Box
import java.security.SecureRandom

/**
 * End-to-end encryption for the relay path - libsodium crypto_box (Curve25519 +
 * XSalsa20-Poly1305), byte-for-byte compatible with the daemon's PyNaCl and
 * Paseo's tweetnacl. Frame = nonce(24) || ciphertext(+16-byte MAC). The relay
 * only ever sees this opaque frame.
 */
object E2ee {
    private val ls = LazySodiumAndroid(SodiumAndroid())
    private val rng = SecureRandom()

    private fun b64(b: ByteArray) = Base64.encodeToString(b, Base64.NO_WRAP)
    private fun unb64(s: String): ByteArray = Base64.decode(s, Base64.NO_WRAP)

    /** @return Pair(secretKeyB64, publicKeyB64) */
    fun generateKeyPair(): Pair<String, String> {
        val pk = ByteArray(Box.PUBLICKEYBYTES)
        val sk = ByteArray(Box.SECRETKEYBYTES)
        if (!ls.cryptoBoxKeypair(pk, sk)) throw RuntimeException("keypair failed")
        return Pair(b64(sk), b64(pk))
    }

    /** Seal plaintext to peer (peerPk). @return base64(nonce || ciphertext). */
    fun seal(plain: ByteArray, skB64: String, peerPkB64: String): String {
        val nonce = ByteArray(Box.NONCEBYTES)
        rng.nextBytes(nonce)
        val ct = ByteArray(Box.MACBYTES + plain.size)
        if (!ls.cryptoBoxEasy(ct, plain, plain.size.toLong(), nonce, unb64(peerPkB64), unb64(skB64)))
            throw RuntimeException("seal failed")
        return b64(nonce + ct)
    }

    /** Open a base64(nonce || ciphertext) frame from peer; throws if tampered. */
    fun open(frameB64: String, skB64: String, peerPkB64: String): ByteArray {
        val frame = unb64(frameB64)
        val nonce = frame.copyOfRange(0, Box.NONCEBYTES)
        val ct = frame.copyOfRange(Box.NONCEBYTES, frame.size)
        val msg = ByteArray(ct.size - Box.MACBYTES)
        if (!ls.cryptoBoxOpenEasy(msg, ct, ct.size.toLong(), nonce, unb64(peerPkB64), unb64(skB64)))
            throw RuntimeException("open failed (tampered or wrong key)")
        return msg
    }
}
