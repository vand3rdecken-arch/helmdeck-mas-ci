import Foundation
import Security

/// Where the watch's own pairing material lives: relay URL, room, the
/// daemon's public key, this device's own NaCl keypair, and its Bearer
/// device token - the Swift sibling of app.helmdeck.wear.data.DeviceStore
/// (Kotlin, EncryptedSharedPreferences). Keychain is the platform's own
/// at-rest-encrypted store for exactly this case, so it is the floor here,
/// not an upgrade - same reasoning the Kotlin file gives for its choice.
///
/// `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` on every item: this
/// device's own keypair/token must never ride an iCloud Keychain sync to
/// another device (mirrors the Kotlin store's device-scoped intent) and must
/// be unreadable before the first unlock after a reboot.
enum DeviceStore {
    struct Device: Codable {
        let relayUrl: String
        let room: String
        let daemonPubB64: String
        let mySecretKeyB64: String
        let myPublicKeyB64: String
        let deviceToken: String
    }

    private static let service = "app.helmdeck.watchcompanion"
    private static let deviceAccount = "device"
    private static let chatAccount = "chat"

    // MARK: - Keychain plumbing

    private static func keychainSet(_ account: String, data: Data) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    private static func keychainGet(_ account: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data
    }

    private static func keychainDelete(_ account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }

    // MARK: - Pairing credentials

    /// nil when unreadable or never written - a partially-written store must
    /// never be read as "paired".
    static func load() -> Device? {
        guard let data = keychainGet(deviceAccount) else { return nil }
        return try? JSONDecoder().decode(Device.self, from: data)
    }

    static func save(_ device: Device) {
        guard let data = try? JSONEncoder().encode(device) else { return }
        keychainSet(deviceAccount, data: data)
    }

    /// Forgets this device's own pairing only - does NOT reach the daemon
    /// (the owner revokes a lost watch's token from the phone/desktop
    /// instead, same as the Kotlin store's own comment).
    static func clear() {
        keychainDelete(deviceAccount)
    }

    // MARK: - Henry transcript cache
    //
    // Owner, 2026-08-29 (Wear OS): "Der chat sollte gecacht sein." Kept in the
    // KEYCHAIN, deliberately not in UserDefaults: these lines are whatever
    // Henry said about the owner's cards, the same class of content the relay
    // is end-to-end encrypted for - writing them in cleartext onto a device
    // that leaves the house on a wrist would quietly undo that.

    struct ChatLine: Codable {
        let mine: Bool
        let text: String
        let ts: String
        let date: String
        let label: String
    }

    /// Bounded on purpose - re-encrypting the whole blob on every save should
    /// stay cheap, and a round screen never usefully scrolls further than this.
    static let chatMax = 40

    static func loadChat() -> [ChatLine] {
        guard let data = keychainGet(chatAccount) else { return [] }
        return (try? JSONDecoder().decode([ChatLine].self, from: data)) ?? []
    }

    static func saveChat(_ lines: [ChatLine]) {
        let kept = lines.count > chatMax ? Array(lines.suffix(chatMax)) : lines
        guard let data = try? JSONEncoder().encode(kept) else { return }
        keychainSet(chatAccount, data: data)
    }

    static func clearChat() {
        keychainDelete(chatAccount)
    }

    // MARK: - UI preference (not a credential)
    //
    // Deliberately UserDefaults, not Keychain: a "should Henry speak out
    // loud" toggle is neither a credential nor key material, and putting it
    // in the encrypted store would mean every tap re-encrypts a blob for a
    // boolean. Same split the Kotlin store keeps (its own plain
    // SharedPreferences file).

    private static let voiceOnKey = "voice_on"

    /// Defaults to false - the daemon renders the clip unconditionally
    /// either way; this only decides whether the watch PLAYS it. Starting
    /// silent is the safe direction to be wrong in.
    static func loadVoiceOn() -> Bool {
        UserDefaults.standard.bool(forKey: voiceOnKey)
    }

    static func saveVoiceOn(_ on: Bool) {
        UserDefaults.standard.set(on, forKey: voiceOnKey)
    }
}
