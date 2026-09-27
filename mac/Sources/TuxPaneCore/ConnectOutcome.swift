import Foundation

public enum ConnectOutcome: Equatable {
    case connected, unreachable, certificateMismatch, authenticationFailed
    case versionMismatch(String), captureFailed(String), serverError(String), connectionLost(String)
    case replaced

    public static func fromServerError(_ text: String) -> ConnectOutcome {
        if text == "authentication failed" { return .authenticationFailed }
        if text == "replaced by another connection" { return .replaced }
        if text.hasPrefix("unsupported protocol version") { return .versionMismatch(text) }
        if text.hasPrefix("capture failed:") || text.hasPrefix("agent cannot start capture:") {
            return .captureFailed(text)
        }
        return .serverError(text)
    }
    public var title: String {
        switch self {
        case .connected: return "Connected"
        case .unreachable: return "Can't reach the Linux machine"
        case .certificateMismatch: return "The machine's security certificate has changed"
        case .authenticationFailed: return "This pairing is no longer valid"
        case .versionMismatch: return "TuxPane versions don't match"
        case .captureFailed: return "The Linux machine can't capture its screen"
        case .serverError: return "The Linux machine reported a problem"
        case .connectionLost: return "The connection was closed"
        case .replaced: return "Another device connected to this machine"
        }
    }
    public var help: String {
        switch self {
        case .connected: return ""
        case .unreachable:
            return
                "Make sure the Linux machine is switched on and on the same network as this Mac (or both are on Tailscale), and that its agent is running: run `tuxpane status` on it."
        case .certificateMismatch:
            return
                "If you reinstalled TuxPane or ran `tuxpane pair --reset`, run `tuxpane pair` on Linux and pair again. If you didn't, another device may be answering at this address."
        case .authenticationFailed: return "Run `tuxpane pair` on Linux and pair again with the new code."
        case let .versionMismatch(detail):
            return "\(detail). Update the Mac app from GitHub and run `tuxpane update` on Linux."
        case let .captureFailed(detail):
            return "\(detail). Run `tuxpane status` on Linux for details; a desktop session must be logged in."
        case let .serverError(detail): return "\(detail). Run `tuxpane status` on Linux for details."
        case .replaced:
            return
                "Only one Mac can control a Linux machine at a time. To take it back, choose Machines › Show Machines and click Connect."
        case let .connectionLost(detail):
            return
                "\(detail). If this Mac is already connected to that machine in another TuxPane window, close it and try again; otherwise run `tuxpane status` on Linux."
        }
    }

    /// Being bumped by another Mac must not trigger an automatic reconnect, or the two would bump each other forever.
    public var shouldReconnect: Bool { self != .replaced }
}
