import Foundation
import Security

public protocol SecretStore: AnyObject {
    func secret(for account: String) -> String?
    func setSecret(_ secret: String, for account: String) throws
    func deleteSecret(for account: String)
}

public final class InMemorySecretStore: SecretStore {
    private var values: [String: String] = [:]
    public init() {}
    public func secret(for account: String) -> String? { values[account] }
    public func setSecret(_ secret: String, for account: String) throws { values[account] = secret }
    public func deleteSecret(for account: String) { values[account] = nil }
}

public struct KeychainError: LocalizedError {
    public let status: OSStatus
    public var errorDescription: String? {
        "Keychain error \(status): \(SecCopyErrorMessageString(status, nil) as String? ?? "unknown")"
    }
}

public final class KeychainSecretStore: SecretStore {
    private let service: String
    public init(service: String = "TuxPane") { self.service = service }
    private func query(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
    public func secret(for account: String) -> String? {
        var item: CFTypeRef?
        var q = query(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess, let data = item as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }
    public func setSecret(_ secret: String, for account: String) throws {
        let data = Data(secret.utf8)
        let status = SecItemUpdate(query(account) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var add = query(account)
            add[kSecValueData as String] = data
            add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
            let added = SecItemAdd(add as CFDictionary, nil)
            guard added == errSecSuccess else { throw KeychainError(status: added) }
        } else if status != errSecSuccess {
            throw KeychainError(status: status)
        }
    }
    public func deleteSecret(for account: String) { SecItemDelete(query(account) as CFDictionary) }
}
