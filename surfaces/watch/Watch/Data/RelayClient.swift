import Foundation

/// The watch's half of the relay protocol - the Swift sibling of
/// app.helmdeck.wear.data.RelayClient (Kotlin), which itself mirrors
/// relayReq() in surfaces/app/src/data/client.ts BYTE FOR BYTE: seal
/// {method,path,headers,body} to the daemon's pubkey, POST {pub,cipher} to
/// `$relayUrl/relay?room=$room`, open the returned {cipher} to get
/// {status,body}. `URLSession`, not a new HTTP dependency - same stdlib
/// preference the Kotlin/Python siblings both make.
///
/// TWO DIFFERENT NETWORK PATHS, same distinction the Kotlin file draws:
///   1. claim() - a plain, unencrypted HTTPS call to the pairing worker.
///      No NaCl involved yet - there is no shared secret until this returns
///      one.
///   2. authedCall() - the real relay path, sealed with HelmDeckBox, used
///      for every request after pairing.
enum RelayError: Error, LocalizedError {
    case desktopOffline
    case desktopTimeout
    case desktopSilent
    case relayError(Int)
    case malformed

    var errorDescription: String? {
        switch self {
        case .desktopOffline: return "desktop offline"
        case .desktopTimeout: return "desktop timeout"
        case .desktopSilent: return "desktop silent"
        case .relayError(let code): return "relay error \(code)"
        case .malformed: return "malformed request or response"
        }
    }
}

enum RelayClient {
    struct ClaimResult {
        let relayUrl: String
        let room: String
        let daemonPubB64: String
        let deviceToken: String
    }

    private static func trimSlash(_ s: String) -> String {
        var t = s
        while t.hasSuffix("/") { t.removeLast() }
        return t
    }

    /// GET {claimBaseUrl}/relay/pair/claim?code=XXXXXX - unauthenticated by
    /// design. Single-use: a second call with the same code returns nil,
    /// same as the daemon does.
    static func claim(claimBaseUrl: String, code: String) async -> ClaimResult? {
        let normalized = code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !normalized.isEmpty,
              let url = URL(string: trimSlash(claimBaseUrl) + "/relay/pair/claim?code=" + normalized)
        else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 15
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        guard let relayUrl = o["url"] as? String, !relayUrl.isEmpty,
              let room = o["room"] as? String, !room.isEmpty,
              let daemonPub = o["daemon_pub"] as? String, !daemonPub.isEmpty,
              let token = o["device_token"] as? String, !token.isEmpty
        else { return nil }
        return ClaimResult(relayUrl: relayUrl, room: room, daemonPubB64: daemonPub, deviceToken: token)
    }

    /// One sealed request/response round trip through the relay - the exact
    /// envelope RelayClient.kt's authedCall builds. The FIRST successful call
    /// a newly-claimed device makes pins its key into the daemon's
    /// relay.phone_pubs[], so this is also the pairing-completion step, not
    /// just the everyday transport.
    static func authedCall(
        relayUrl: String, room: String, daemonPubB64: String,
        myPublicKeyB64: String, mySecretKeyB64: String, deviceToken: String,
        method: String, path: String, body: String = "",
        timeout: TimeInterval = 20
    ) async throws -> (status: Int, body: String) {
        let inner: [String: Any] = [
            "method": method,
            "path": path,
            "headers": ["Authorization": "Bearer \(deviceToken)", "Content-Type": "application/json"],
            "body": body,
        ]
        guard let innerData = try? JSONSerialization.data(withJSONObject: inner),
              let innerStr = String(data: innerData, encoding: .utf8),
              let cipher = HelmDeckBox.sealB64(innerStr, mySecretKeyB64: mySecretKeyB64, peerPublicKeyB64: daemonPubB64)
        else { throw RelayError.malformed }
        let outer: [String: Any] = ["pub": myPublicKeyB64, "cipher": cipher]
        guard let outerData = try? JSONSerialization.data(withJSONObject: outer),
              let url = URL(string: trimSlash(relayUrl) + "/relay?room=" + room)
        else { throw RelayError.malformed }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = outerData
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw RelayError.malformed }
        // Distinct desktop-offline/timeout cases, everything else non-2xx a
        // generic relay error - mirrors relayReq()'s own distinction so a
        // future UI can tell them apart the same way.
        if http.statusCode == 503 { throw RelayError.desktopOffline }
        if http.statusCode == 504 { throw RelayError.desktopTimeout }
        guard (200...299).contains(http.statusCode) else { throw RelayError.relayError(http.statusCode) }
        guard let out = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let respCipher = out["cipher"] as? String, !respCipher.isEmpty
        else { throw RelayError.desktopSilent }
        guard let plain = HelmDeckBox.openB64(respCipher, mySecretKeyB64: mySecretKeyB64, peerPublicKeyB64: daemonPubB64),
              let resp = try? JSONSerialization.jsonObject(with: Data(plain.utf8)) as? [String: Any]
        else { throw RelayError.malformed }
        return (resp["status"] as? Int ?? 200, resp["body"] as? String ?? "")
    }

    /// POST /wear/talk with the phone's patience, not a probe's - mirrors
    /// RelayClient.kt's talk(): a Henry turn regularly runs 20-180s, so a
    /// single short-timeout authedCall would report a dead Henry over a live
    /// one. /wear/talk's chat_dedupe claim (owner decree 2026-08-29) is what
    /// makes retrying here safe - a retry either waits on the original claim
    /// or collects its settled answer, never runs a second turn.
    ///
    /// timeout 150s > the relay's own 120s REPLY_TIMEOUT, so the relay's 504
    /// (a clean "still working" signal here) paces the loop rather than a
    /// client-side abort racing it. 4 attempts ~ 8-10 min worst case.
    static func talk(
        relayUrl: String, room: String, daemonPubB64: String,
        myPublicKeyB64: String, mySecretKeyB64: String, deviceToken: String,
        body: String
    ) async -> (status: Int, body: String)? {
        var last: (status: Int, body: String)?
        for attempt in 1...4 {
            let result = try? await authedCall(
                relayUrl: relayUrl, room: room, daemonPubB64: daemonPubB64,
                myPublicKeyB64: myPublicKeyB64, mySecretKeyB64: mySecretKeyB64, deviceToken: deviceToken,
                method: "POST", path: "/wear/talk", body: body, timeout: 150)
            if let result, (200...299).contains(result.status) {
                let o = try? JSONSerialization.jsonObject(with: Data(result.body.utf8)) as? [String: Any]
                let stillRunning = (o?["duplicate"] as? Bool == true) && ((o?["reply"] as? String) ?? "").isEmpty
                if !stillRunning { return result }
            }
            last = result
            if attempt < 4 { try? await Task.sleep(nanoseconds: 2_000_000_000) }
        }
        return last
    }

    /// GET /me over the sealed relay - the watch's own pairing-completion
    /// probe, mirroring RelayClient.kt's completePairing().
    static func completePairing(
        relayUrl: String, room: String, daemonPubB64: String,
        myPublicKeyB64: String, mySecretKeyB64: String, deviceToken: String
    ) async -> Bool {
        guard let result = try? await authedCall(
            relayUrl: relayUrl, room: room, daemonPubB64: daemonPubB64,
            myPublicKeyB64: myPublicKeyB64, mySecretKeyB64: mySecretKeyB64, deviceToken: deviceToken,
            method: "GET", path: "/me")
        else { return false }
        return (200...299).contains(result.status)
    }
}
