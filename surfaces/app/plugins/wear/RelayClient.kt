package app.helmdeck.wear.data

import app.helmdeck.wear.crypto.HelmDeckBox
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import org.json.JSONObject

/**
 * The watch's half of the relay protocol - mirrors relayReq() in
 * surfaces/app/src/data/client.ts BYTE FOR BYTE (read this session, not
 * recalled): seal {method,path,headers,body} to the daemon's pubkey, POST
 * {pub,cipher} to `$relayUrl/relay?room=$room`, open the returned
 * {cipher} to get {status,body}. Plain java.net.HttpURLConnection, not a new
 * HTTP library dependency - matches relay_client.py's own preference for
 * stdlib urllib over anything heavier.
 *
 * TWO DIFFERENT NETWORK PATHS, not one - worth stating plainly because they
 * are easy to conflate:
 *   1. claim(): a PLAIN, UNENCRYPTED HTTPS call to whatever origin currently
 *      exposes the daemon directly (see claimBaseUrl - deliberately a
 *      caller-supplied value, not hardcoded, because this repo has no
 *      always-on public path to the daemon's raw HTTP surface today; the
 *      owner runs ops/deploy/cloudflare_tunnel.sh for the few minutes
 *      pairing takes). No NaCl involved yet - there is no shared secret
 *      until this call returns one.
 *   2. authedCall(): the REAL relay path, sealed with HelmDeckBox, used for
 *      every request after pairing (the /me call that completes admission,
 *      and eventually the board itself).
 */
object RelayClient {
    data class ClaimResult(
        val relayUrl: String,
        val room: String,
        val daemonPubB64: String,
        val deviceToken: String,
    )

    /** GET {claimBaseUrl}/relay/pair/claim?code=XXXXXX - unauthenticated by
     *  design (routes_relay.py's relay_pair_claim_get, spine/http/server.py's
     *  OPEN tuple). Single-use: a second call with the same code returns
     *  null, same as the daemon does. */
    fun claim(claimBaseUrl: String, code: String): ClaimResult? {
        val url = URL(claimBaseUrl.trimEnd('/') + "/relay/pair/claim?code=" +
            code.trim().uppercase())
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15_000
            readTimeout = 15_000
        }
        try {
            if (conn.responseCode != 200) return null
            val body = conn.inputStream.bufferedReader(StandardCharsets.UTF_8).readText()
            val o = JSONObject(body)
            val url2 = o.optString("url", "")
            val room = o.optString("room", "")
            val daemonPub = o.optString("daemon_pub", "")
            val token = o.optString("device_token", "")
            if (url2.isEmpty() || room.isEmpty() || daemonPub.isEmpty() || token.isEmpty())
                return null
            return ClaimResult(url2, room, daemonPub, token)
        } finally {
            conn.disconnect()
        }
    }

    class RelayError(message: String) : Exception(message)

    /** One sealed request/response round trip through the relay - the SAME
     *  envelope shape relayReq() in client.ts builds, confirmed by reading
     *  it this session, not assumed:
     *    outer POST body:  {"pub": myPub, "cipher": base64(seal(inner))}
     *    inner (sealed):   {"method","path","headers":{Authorization:...},"body"}
     *    reply body:       {"cipher": base64(seal({"status","body"}))}
     *  The FIRST successful call a newly-claimed device makes is what pins
     *  its key into the daemon's relay.phone_pubs[] (relay_client.py's
     *  _admit(), consuming the pairing window claim() already opened
     *  server-side via mint_claim_code/claim_code's own TTL) - so this
     *  function is not just "how the watch talks to the board", it is also
     *  the pairing-completion step. */
    fun authedCall(
        relayUrl: String, room: String, daemonPubB64: String,
        myPublicKeyB64: String, mySecretKeyB64: String, deviceToken: String,
        method: String, path: String, bodyStr: String = "",
    ): Pair<Int, String> {
        val inner = JSONObject().apply {
            put("method", method)
            put("path", path)
            put("headers", JSONObject().apply {
                put("Authorization", "Bearer $deviceToken")
                put("Content-Type", "application/json")
            })
            put("body", bodyStr)
        }.toString()
        val cipher = HelmDeckBox.sealB64(inner, mySecretKeyB64, daemonPubB64)
        val outer = JSONObject().apply {
            put("pub", myPublicKeyB64)
            put("cipher", cipher)
        }.toString()

        val url = URL(relayUrl.trimEnd('/') + "/relay?room=" + room)
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 15_000
            readTimeout = 20_000
            setRequestProperty("Content-Type", "application/json")
        }
        try {
            conn.outputStream.use { it.write(outer.toByteArray(StandardCharsets.UTF_8)) }
            // relayReq() treats 503/504 as distinct desktop-offline/timeout
            // cases and anything else non-2xx as a generic relay error -
            // mirrored here rather than collapsing all failures into one
            // message, so a future UI can tell them apart the same way.
            when (conn.responseCode) {
                503 -> throw RelayError("desktop offline")
                504 -> throw RelayError("desktop timeout")
            }
            if (conn.responseCode !in 200..299) {
                throw RelayError("relay error ${conn.responseCode}")
            }
            val raw = conn.inputStream.bufferedReader(StandardCharsets.UTF_8).readText()
            val out = JSONObject(raw)
            val respCipher = out.optString("cipher", "")
            if (respCipher.isEmpty()) throw RelayError("desktop silent")
            val plain = HelmDeckBox.openB64(respCipher, mySecretKeyB64, daemonPubB64)
            val resp = JSONObject(plain)
            return resp.optInt("status", 200) to resp.optString("body", "")
        } finally {
            conn.disconnect()
        }
    }

    /** GET /me over the sealed relay - the exact call config.ts's onboarding
     *  flow makes right after applyPairing() (pairing_gate.tsx: "the SAME
     *  applyPairing()+api.me() round trip"), mirrored here as the watch's
     *  own pairing-completion probe rather than inventing a new one. */
    fun completePairing(
        relayUrl: String, room: String, daemonPubB64: String,
        myPublicKeyB64: String, mySecretKeyB64: String, deviceToken: String,
    ): Boolean {
        return try {
            val (status, _) = authedCall(
                relayUrl, room, daemonPubB64, myPublicKeyB64, mySecretKeyB64,
                deviceToken, "GET", "/me")
            status in 200..299
        } catch (_: Exception) {
            false
        }
    }
}
