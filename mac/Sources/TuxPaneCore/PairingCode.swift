import Foundation

public struct PairingInfo: Equatable {
    public let name: String
    public let hosts: [String]
    public let port: UInt16
    public let token: String
    public let fingerprint: String

    public init(name: String, hosts: [String], port: UInt16, token: String, fingerprint: String) {
        self.name = name
        self.hosts = hosts
        self.port = port
        self.token = token
        self.fingerprint = fingerprint
    }
}

public enum PairingError: LocalizedError, Equatable {
    case notAPairingCode, damaged, incomplete, badFingerprint
    case publicAddress(String)

    public var errorDescription: String? {
        switch self {
        case .notAPairingCode:
            return
                "That isn't a TuxPane pairing code. It starts with “tuxpane1:”. Run `tuxpane pair` on Linux to show it."
        case .damaged:
            return "The pairing code looks cut off or changed. Copy the whole line again (run `tuxpane pair` on Linux)."
        case .incomplete, .badFingerprint:
            return "The pairing code is missing information. Update TuxPane on Linux (`tuxpane update`) and pair again."
        case let .publicAddress(host):
            return
                "The code contains \(host), which isn't a home-network or Tailscale address. TuxPane only connects over private networks."
        }
    }
}

public enum PairingCode {
    public static let prefix = "tuxpane1:"

    public static func parse(_ text: String) throws -> PairingInfo {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix(prefix) else { throw PairingError.notAPairingCode }
        // Terminals such as tmux hard-wrap the long line; whitespace is never part of the code.
        var body = String(trimmed.dropFirst(prefix.count).filter { !$0.isWhitespace })
            .replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        body += String(repeating: "=", count: (4 - body.count % 4) % 4)
        guard let data = Data(base64Encoded: body),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            throw PairingError.damaged
        }
        guard let name = object["n"] as? String,
            let hosts = object["h"] as? [String], !hosts.isEmpty,
            let port = object["p"] as? Int, (1...65535).contains(port),
            let token = object["t"] as? String, token.count >= 16
        else {
            throw PairingError.incomplete
        }
        guard let fingerprint = object["f"] as? String, fingerprint.count == 64,
            fingerprint.allSatisfy(\.isHexDigit)
        else { throw PairingError.badFingerprint }
        // Skip addresses the Mac must not dial (e.g. a VPN's benchmark range); fail only if nothing usable is left.
        let usable = hosts.filter(PrivateAddress.isAllowed)
        guard !usable.isEmpty else { throw PairingError.publicAddress(hosts[0]) }
        return PairingInfo(
            name: name, hosts: usable, port: UInt16(port), token: token,
            fingerprint: fingerprint.lowercased())
    }
}

/// Addresses a Mac may be told to dial: LAN (RFC 1918) and Tailscale only. Mirrors `is_pairable` in the agent.
public enum PrivateAddress {
    public static func isAllowed(_ host: String) -> Bool {
        let parts = host.split(separator: ".", omittingEmptySubsequences: false)
        let octets = parts.compactMap { UInt8($0) }
        guard parts.count == 4, octets.count == 4 else { return false }
        let (a, b) = (octets[0], octets[1])
        return a == 10 || (a == 172 && (16...31).contains(b)) || (a == 192 && b == 168)
            || (a == 100 && (64...127).contains(b))
    }
}
