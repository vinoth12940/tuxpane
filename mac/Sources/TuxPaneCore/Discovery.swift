import Foundation

public struct DiscoveredMachine: Equatable, Identifiable {
    public let name: String
    public let os: String
    public let host: String
    public let pairingPort: UInt16
    public var id: String { host }

    public init(name: String, os: String, host: String, pairingPort: UInt16) {
        self.name = name
        self.os = os
        self.host = host
        self.pairingPort = pairingPort
    }
}

/// Finding Linux machines that are in pairing mode (`tuxpane pair`) on the local network.
public enum Discovery {
    public static let query = Data(#"{"q":"tuxpane-discover","v":1}"#.utf8)

    public static func parseReply(_ data: Data, from host: String) -> DiscoveredMachine? {
        guard PrivateAddress.isAllowed(host),
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
            object["v"] as? Int == PairingProtocol.version,
            let name = object["n"] as? String, !name.isEmpty,
            let port = object["pp"] as? Int, (1...65535).contains(port)
        else { return nil }
        return DiscoveredMachine(
            name: name, os: object["os"] as? String ?? "Linux", host: host, pairingPort: UInt16(port))
    }
}

/// Machines currently answering discovery: one entry per machine name, dropped when it stops answering.
public struct DiscoveryList {
    public private(set) var machines: [DiscoveredMachine] = []
    private var lastSeen: [String: TimeInterval] = [:]
    private let expiry: TimeInterval

    public init(expiry: TimeInterval = 3) { self.expiry = expiry }

    /// Records a reply; returns true when the visible list changed.
    public mutating func saw(_ machine: DiscoveredMachine, at now: TimeInterval) -> Bool {
        lastSeen[machine.name] = now
        if let index = machines.firstIndex(where: { $0.name == machine.name }) {
            guard machines[index].os != machine.os else { return false }
            machines[index] = DiscoveredMachine(
                name: machine.name, os: machine.os, host: machines[index].host, pairingPort: machine.pairingPort)
            return true
        }
        machines.append(machine)
        return true
    }

    /// Removes machines not heard from within the expiry; returns true when the visible list changed.
    public mutating func prune(at now: TimeInterval) -> Bool {
        let before = machines.count
        machines.removeAll { now - (lastSeen[$0.name] ?? 0) > expiry }
        return machines.count != before
    }
}
