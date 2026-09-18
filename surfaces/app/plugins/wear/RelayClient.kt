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
        readTimeoutMs: Int = 20_000,
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
            readTimeout = readTimeoutMs
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

    /** POST /wear/talk with the phone's patience, not a probe's.
     *
     *  "Henry nicht erreichbar" was mostly a STOPWATCH, not an outage: a Henry
     *  turn regularly runs 20-180s (176s measured on the phone, client.ts),
     *  while this client's single authedCall gave up at readTimeout=20s and the
     *  relay itself answers 504 at REPLY_TIMEOUT=120s - the daemon finished the
     *  turn either way, and the watch reported a dead Henry over a live one.
     *
     *  The phone survives the same layers by RESENDING the unacked POST and
     *  letting the daemon's chat_dedupe collapse the replays into one turn
     *  (client.ts documents this exact stack). /wear/talk claims the same
     *  dedupe since 2026-08-29, which is what makes this loop SAFE: a retry can
     *  never run a second turn or replay a board action - it either waits on
     *  the original claim or collects its settled answer.
     *
     *  Retry semantics come from the route: reply=""+duplicate=true means "the
     *  original turn is still running, ask again"; anything else with a 2xx is
     *  the answer. readTimeout 150s > the relay's 120s REPLY_TIMEOUT, so the
     *  relay's own 504 (a clean "still working" signal here) is what paces the
     *  loop rather than a client-side abort racing it. 4 attempts ~ 8-10 min
     *  worst case, the same order as the phone's 900s chat bound.
     *
     *  Blocking sleep, not delay(): every caller already runs this on
     *  Dispatchers.IO around a blocking HttpURLConnection - same thread
     *  discipline, no new suspend surface on a stdlib-style client. */

    /** talk()'s outcome, once its own retries are exhausted.
     *
     *  Introduced 2026-09-18 (owner bug report): the old `Pair<Int,String>?`
     *  collapsed EVERY failure into the same null - a plain 150s socket
     *  timeout (the turn is almost certainly still running server-side, talk()
     *  just gave up watching it) read identically to the relay's own 503
     *  "desktop offline" (a real, evidenced outage). A caller that cannot
     *  tell those apart has no honest way to decide whether "nicht
     *  erreichbar" is true. */
    sealed class TalkResult {
        data class Ok(val status: Int, val body: String) : TalkResult()
        /** The relay itself said the desktop is unreachable (503) - an
         *  outage the client did not have to guess at. */
        object Offline : TalkResult()
        /** Every attempt failed for some other reason (timeout, a transient
         *  relay error, ...) with nothing to confirm an outage. The turn may
         *  still be running server-side; only a caller's own follow-up read
         *  of a lighter endpoint can tell. */
        object Unknown : TalkResult()
    }

    fun talk(
        relayUrl: String, room: String, daemonPubB64: String,
        myPublicKeyB64: String, mySecretKeyB64: String, deviceToken: String,
        bodyStr: String,
    ): TalkResult {
        var offline = false
        for (attempt in 1..4) {
            val outcome = runCatching {
                authedCall(
                    relayUrl, room, daemonPubB64, myPublicKeyB64, mySecretKeyB64,
                    deviceToken, "POST", "/wear/talk", bodyStr,
                    readTimeoutMs = 150_000)
            }
            val r = outcome.getOrNull()
            if (r != null && r.first in 200..299) {
                val o = runCatching { JSONObject(r.second) }.getOrNull()
                val stillRunning = o?.optBoolean("duplicate") == true &&
                    (o.optString("reply").isBlank())
                if (!stillRunning) return TalkResult.Ok(r.first, r.second)
            }
            // STICKY, not overwritten: one confirmed "desktop offline" among
            // four attempts is still the honest signal even if a later retry
            // failed for some other, less specific reason.
            offline = offline || (outcome.exceptionOrNull() as? RelayError)?.message == "desktop offline"
            if (attempt < 4) Thread.sleep(2_000)
        }
        return if (offline) TalkResult.Offline else TalkResult.Unknown
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
