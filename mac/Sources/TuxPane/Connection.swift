import Foundation
import Network
import Security
import TuxPaneCore

final class Connection {
    var onMessage: ((ServerMessage) -> Void)?
    var onStatus: ((String) -> Void)?
    var onDisconnect: (() -> Void)?
    var onOutcome: ((ConnectOutcome) -> Void)?
    /// TLS is up with the pinned certificate (before the token is checked).
    var onSecured: (() -> Void)?
    private let machine: Machine
    private let token: String
    private let requestedSize: (width: Int, height: Int)
    private let reconnect: Bool
    private var connection: NWConnection?
    private var parser = FrameParser()
    private var link = LinkState()
    private var hostIndex = 0
    private var reachedReady = false
    private var pinMismatch = false
    private var stopped = false
    private var reconnectPending = false
    private var watchdog: Timer?

    init(machine: Machine, token: String, requestedSize: (width: Int, height: Int), reconnect: Bool) {
        self.machine = machine
        self.token = token
        self.requestedSize = requestedSize
        self.reconnect = reconnect
    }
    private var host: String { machine.hosts[hostIndex] }
    func start() {
        stopped = false
        reconnectPending = false
        connect()
        if watchdog == nil {
            let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.checkLiveness() }
            RunLoop.main.add(timer, forMode: .common)
            watchdog = timer
        }
    }
    func stop() {
        stopped = true
        watchdog?.invalidate()
        watchdog = nil
        connection?.cancel()
        connection = nil
    }
    func send(_ data: Data) {
        guard link.allowsSending(data) else { return }
        connection?.send(content: data, completion: .idempotent)
    }
    private static func now() -> TimeInterval { ProcessInfo.processInfo.systemUptime }
    private func tlsOptions() -> NWProtocolTLS.Options {
        let tls = NWProtocolTLS.Options()
        let options = tls.securityProtocolOptions
        sec_protocol_options_set_min_tls_protocol_version(options, .TLSv13)
        let pinned = machine.fingerprint
        sec_protocol_options_set_verify_block(
            options,
            { [weak self] _, trust, complete in
                let secTrust = sec_trust_copy_ref(trust).takeRetainedValue()
                let chain = (SecTrustCopyCertificateChain(secTrust) as? [SecCertificate]) ?? []
                let trusted =
                    chain.first.map { Fingerprint.matches(der: SecCertificateCopyData($0) as Data, pinned: pinned) }
                    ?? false
                if !trusted { self?.pinMismatch = true }
                complete(trusted)
            }, .main)
        return tls
    }
    private func connect() {
        guard !stopped, let port = NWEndpoint.Port(rawValue: machine.port) else { return }
        let tcp = NWProtocolTCP.Options()
        tcp.noDelay = true
        tcp.connectionTimeout = 3
        let conn = NWConnection(
            host: NWEndpoint.Host(host), port: port, using: NWParameters(tls: tlsOptions(), tcp: tcp))
        connection = conn
        parser = FrameParser()
        reachedReady = false
        pinMismatch = false
        link.connecting(now: Self.now())
        conn.stateUpdateHandler = { [weak self, weak conn] state in
            guard let self, let conn, conn === self.connection else { return }
            switch state {
            case .ready:
                self.reachedReady = true
                self.onSecured?()
                self.onStatus?("Signing in to \(self.machine.name)…")
                self.send(
                    Wire.hello(
                        token: self.token, width: UInt16(clamping: self.requestedSize.width),
                        height: UInt16(clamping: self.requestedSize.height)))
                self.receive(on: conn)
            case .waiting(let error), .failed(let error): self.connectFailed(error)
            default: break
            }
        }
        onStatus?("Connecting to \(machine.name) (\(host))…")
        conn.start(queue: .main)
    }
    private func connectFailed(_ error: NWError) {
        if reachedReady {
            drop("Connection lost: \(error.localizedDescription)")
        } else if pinMismatch {
            drop("Certificate mismatch", outcome: .certificateMismatch)
        } else if hostIndex + 1 < machine.hosts.count {
            connection?.cancel()
            connection = nil
            hostIndex += 1
            connect()
        } else {
            hostIndex = 0
            drop("Cannot reach \(machine.name): \(error.localizedDescription)", outcome: .unreachable)
        }
    }
    private func checkLiveness() {
        if connection != nil, link.isStale(now: Self.now()) { drop("No data from \(machine.name) for 5 s") }
    }
    private func receive(on conn: NWConnection) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 1 << 20) { [weak self] data, _, isComplete, error in
            guard let self, conn === self.connection else { return }
            if let data, !data.isEmpty {
                do {
                    for frame in try self.parser.append(data) {
                        let message = try ServerMessage.parse(frame)
                        self.link.received(message, now: Self.now())
                        if case .welcome = message { self.onOutcome?(.connected) }
                        self.onMessage?(message)
                    }
                } catch {
                    self.drop("Protocol error: \(error)")
                    return
                }
            }
            if let error {
                self.drop("Connection lost: \(error.localizedDescription)")
            } else if isComplete {
                self.drop("Disconnected by \(self.machine.name)")
            } else {
                self.receive(on: conn)
            }
        }
    }
    private func drop(_ reason: String, outcome: ConnectOutcome? = nil) {
        connection?.cancel()
        connection = nil
        // A one-shot probe (Setup) must always hear why it ended, or its spinner would wait for a timeout.
        let reported =
            link.serverError.map(ConnectOutcome.fromServerError) ?? outcome
            ?? (reconnect ? nil : .connectionLost(reason))
        if let reported { onOutcome?(reported) }
        onStatus?(reported?.title ?? reason)
        onDisconnect?()
        let backoff = link.disconnected()
        guard reconnect, !stopped, !reconnectPending, reported?.shouldReconnect ?? true else { return }
        reconnectPending = true
        let delay = outcome == .certificateMismatch ? LinkState.maxRetryDelay : backoff
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self, !self.stopped else { return }
            self.reconnectPending = false
            self.connect()
        }
    }
}
