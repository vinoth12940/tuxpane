import CryptoKit
import Foundation

/// Compare-and-confirm pairing (mirrors agent/tuxpane/pairing_protocol.py).
public enum PairingProtocol {
    public static let port: UInt16 = 7301
    public static let version = 1

    public static func code(fingerprint: Data, agentNonce: Data, macNonce: Data) -> String {
        var input = Data("tuxpane-sas-v1".utf8)
        input.append(fingerprint)
        input.append(agentNonce)
        input.append(macNonce)
        let digest = Array(SHA256.hash(data: input))
        let value = digest.prefix(8).reduce(UInt64(0)) { $0 << 8 | UInt64($1) } % 1_000_000
        return String(format: "%03d %03d", Int(value / 1000), Int(value % 1000))
    }

    public static func commitment(_ nonce: Data) -> String { Fingerprint.sha256Hex(nonce) }

    static func hex(_ data: Data) -> String { data.map { String(format: "%02x", $0) }.joined() }

    public static func data(hexString hex: String) -> Data? {
        guard hex.count % 2 == 0 else { return nil }
        var out = Data()
        var index = hex.startIndex
        while index < hex.endIndex {
            let next = hex.index(index, offsetBy: 2)
            guard let byte = UInt8(hex[index..<next], radix: 16) else { return nil }
            out.append(byte)
            index = next
        }
        return out
    }

    static func frame(_ type: MessageType, _ object: [String: Any]) -> Data {
        Wire.frame(type, (try? JSONSerialization.data(withJSONObject: object)) ?? Data("{}".utf8))
    }
}

/// The Mac side of one pairing attempt, as a pure state machine (networking lives in the app target).
public struct PairingClientSession {
    public enum State: Equatable {
        case idle, waitingForNonce
        case awaitingConfirmation(code: String)
        case waitingForLinux(code: String)
        case accepted(PairingInfo)
        case rejected(String)
        case failed(String)
    }

    public private(set) var state: State = .idle
    private let macName: String
    private let fingerprint: Data
    private let nonce: Data

    public init(macName: String, fingerprint: Data, nonce: Data? = nil) {
        self.macName = macName
        self.fingerprint = fingerprint
        self.nonce = nonce ?? Data((0..<32).map { _ in UInt8.random(in: 0...255) })
    }

    public mutating func start() -> Data {
        state = .waitingForNonce
        return PairingProtocol.frame(
            .pairHello,
            ["v": PairingProtocol.version, "name": macName, "commit": PairingProtocol.commitment(nonce)])
    }

    public mutating func receive(_ frame: Frame) -> [Data] {
        let object = (try? JSONSerialization.jsonObject(with: frame.payload)) as? [String: Any] ?? [:]
        switch (MessageType(rawValue: frame.type), state) {
        case (.pairNonce, .waitingForNonce):
            guard let hex = object["nonce"] as? String, let agentNonce = PairingProtocol.data(hexString: hex),
                agentNonce.count == 32
            else { return invalid() }
            state = .awaitingConfirmation(
                code: PairingProtocol.code(fingerprint: fingerprint, agentNonce: agentNonce, macNonce: nonce))
            return [PairingProtocol.frame(.pairReveal, ["nonce": PairingProtocol.hex(nonce)])]
        // Only after the user clicked They Match: an ACCEPT any earlier would skip the code comparison.
        case (.pairAccept, .waitingForLinux):
            guard let token = object["token"] as? String, token.count >= 16,
                let port = object["port"] as? Int, (1...65535).contains(port),
                let name = object["name"] as? String,
                let hosts = (object["hosts"] as? [String])?.filter(PrivateAddress.isAllowed), !hosts.isEmpty
            else { return invalid() }
            state = .accepted(
                PairingInfo(
                    name: name, hosts: hosts, port: UInt16(port), token: token,
                    fingerprint: PairingProtocol.hex(fingerprint)))
            return []
        case (.pairReject, _):
            state = .rejected(object["reason"] as? String ?? "rejected")
            return []
        default:
            return invalid()
        }
    }

    public mutating func confirm() -> Data {
        if case let .awaitingConfirmation(code) = state { state = .waitingForLinux(code: code) }
        return PairingProtocol.frame(.pairConfirm, [:])
    }

    public mutating func abort(_ reason: String) -> Data {
        state = .rejected("cancelled")
        return PairingProtocol.frame(.pairAbort, ["reason": reason])
    }

    private mutating func invalid() -> [Data] {
        state = .failed("The Linux machine sent an invalid pairing message.")
        return []
    }
}
