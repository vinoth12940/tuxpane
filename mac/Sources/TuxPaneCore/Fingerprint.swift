import CryptoKit
import Foundation

public enum Fingerprint {
    public static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    public static func matches(der: Data, pinned: String) -> Bool {
        sha256Hex(der) == pinned.lowercased()
    }
}
