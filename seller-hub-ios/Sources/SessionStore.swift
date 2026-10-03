import Foundation
import Security

struct SessionStore {
    private let service: String
    private let defaults: UserDefaults
    private var signedOutKey: String { service + ".signed-out" }
    init(service: String = "com.pulltheory.sellerhub.session", defaults: UserDefaults = .standard) {
        self.service = service
        self.defaults = defaults
    }
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: "hub"]
    }

    func read() throws -> String? {
        // A logout tombstone contains no credentials. Even if Keychain deletion
        // was interrupted, a later launch must never restore the old account.
        if defaults.bool(forKey: signedOutKey) {
            try clear()
            return nil
        }
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var output: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &output)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw StoreError.unavailable }
        guard let data = output as? Data, let value = String(data: data, encoding: .utf8),
              let session = HubPolicy.session(value) else {
            try clear()
            return nil
        }
        return session
    }

    func save(_ value: String) throws {
        guard let clean = HubPolicy.session(value), let data = clean.data(using: .utf8) else {
            throw StoreError.invalidSession
        }
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw StoreError.unavailable }
        defaults.set(false, forKey: signedOutKey)
    }

    func clear() throws {
        defaults.set(true, forKey: signedOutKey)
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw StoreError.unavailable }
    }

    enum StoreError: Error { case unavailable, invalidSession }
}
