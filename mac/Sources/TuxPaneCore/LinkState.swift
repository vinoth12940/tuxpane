import Foundation

/// Connection bookkeeping: what may be sent before the handshake, how long to wait before
/// reconnecting, and when a silent link counts as dead.
public struct LinkState {
    public static let staleAfter: TimeInterval = 5
    public static let maxRetryDelay: TimeInterval = 5

    public private(set) var authenticated = false
    public private(set) var serverError: String?
    private var retryDelay: TimeInterval = 1
    private var lastHeard: TimeInterval = 0

    public init() {}

    public mutating func connecting(now: TimeInterval) {
        serverError = nil  // each attempt reports its own problem
        authenticated = false
        lastHeard = now
    }

    public mutating func received(_ message: ServerMessage, now: TimeInterval) {
        lastHeard = now
        switch message {
        case .welcome:
            authenticated = true
            serverError = nil
            retryDelay = 1
        case let .error(text):
            serverError = text
        default:
            break
        }
    }

    /// Input sent before WELCOME would be read by the agent as a bad handshake.
    public func allowsSending(_ frame: Data) -> Bool {
        authenticated || frame.first == MessageType.hello.rawValue
    }

    public func isStale(now: TimeInterval) -> Bool {
        authenticated && now - lastHeard > Self.staleAfter
    }

    /// Delay before the next attempt. A server-reported error (bad token, capture failure) waits the longest.
    public mutating func disconnected() -> TimeInterval {
        authenticated = false
        let delay = serverError == nil ? retryDelay : Self.maxRetryDelay
        retryDelay = min(retryDelay * 2, Self.maxRetryDelay)
        return delay
    }
}
