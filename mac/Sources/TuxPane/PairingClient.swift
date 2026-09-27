import CryptoKit
import Foundation
import Network
import Security
import TuxPaneCore

/// One compare-and-confirm pairing attempt over TLS (trust on first use; the code comparison is the trust).
final class PairingClient {
    enum Outcome {
        case paired(PairingInfo)
        case rejected(String)
        case failed(String)
    }

    var onCode: ((String) -> Void)?
    var onFinished: ((Outcome) -> Void)?

    private let host: String
    private let port: UInt16
    private var connection: NWConnection?
    private var session: PairingClientSession?
    private var parser = FrameParser()
    private var leafCertificate: Data?
    private var finished = false
    private var userConfirmed = false

    init(host: String, port: UInt16 = PairingProtocol.port) {
        self.host = host
        self.port = port
    }

    func start() {
        let tls = NWProtocolTLS.Options()
        let options = tls.securityProtocolOptions
        sec_protocol_options_set_min_tls_protocol_version(options, .TLSv13)
        sec_protocol_options_set_verify_block(
            options,
            { [weak self] _, trust, complete in
                let secTrust = sec_trust_copy_ref(trust).takeRetainedValue()
                let chain = (SecTrustCopyCertificateChain(secTrust) as? [SecCertificate]) ?? []
                self?.leafCertificate = chain.first.map { SecCertificateCopyData($0) as Data }
                complete(self?.leafCertificate != nil)
            }, .main)
        let tcp = NWProtocolTCP.Options()
        tcp.noDelay = true
        tcp.connectionTimeout = 5
        guard let endpointPort = NWEndpoint.Port(rawValue: port) else { return finish(.failed("Invalid port.")) }
        let conn = NWConnection(
            host: NWEndpoint.Host(host), port: endpointPort, using: NWParameters(tls: tls, tcp: tcp))
        connection = conn
        conn.stateUpdateHandler = { [weak self, weak conn] state in
            guard let self, let conn, conn === self.connection else { return }
            switch state {
            case .ready:
                guard let leaf = self.leafCertificate else { return self.finish(.failed("No certificate received.")) }
                var session = PairingClientSession(
                    macName: Host.current().localizedName ?? "Mac", fingerprint: Data(SHA256.hash(data: leaf)))
                self.send(session.start())
                self.session = session
                self.receive(on: conn)
            case .failed, .waiting:
                self.finish(
                    .failed(
                        "Couldn't reach \(self.host) on port \(self.port). Make sure `tuxpane pair` is running there "
                            + "and that its firewall allows TuxPane."))
            default:
                break
            }
        }
        conn.start(queue: .main)
    }

    func confirm() {
        guard var session else { return }
        send(session.confirm())
        self.session = session
        userConfirmed = true
    }

    func abort() {
        guard var session, let connection else { return cancel() }
        finished = true
        connection.send(
            content: session.abort("codes differ"),
            completion: .contentProcessed { _ in connection.cancel() })  // keeps the connection alive until sent
        self.session = session
        self.connection = nil
    }

    func cancel() {
        finished = true
        connection?.cancel()
        connection = nil
    }

    private func send(_ data: Data) { connection?.send(content: data, completion: .idempotent) }

    private func receive(on conn: NWConnection) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { [weak self] data, _, isComplete, error in
            guard let self, conn === self.connection, var session = self.session else { return }
            if let data, !data.isEmpty {
                let frames: [Frame]
                do {
                    frames = try self.parser.append(data)
                } catch {
                    return self.finish(.failed("The Linux machine sent an invalid pairing message."))
                }
                for frame in frames {
                    for reply in session.receive(frame) { self.send(reply) }
                }
                self.session = session
                switch session.state {
                case let .awaitingConfirmation(code): self.onCode?(code)
                case let .accepted(info):
                    // Defence in depth: never save a pairing the user didn't confirm on this Mac.
                    guard self.userConfirmed else {
                        return self.finish(.failed("The Linux machine answered before you confirmed the code."))
                    }
                    return self.finish(.paired(info))
                case let .rejected(reason): return self.finish(.rejected(reason))
                case let .failed(message): return self.finish(.failed(message))
                default: break
                }
            }
            if error != nil || isComplete {
                return self.finish(.failed("The Linux machine closed the connection."))
            }
            self.receive(on: conn)
        }
    }

    private func finish(_ outcome: Outcome) {
        guard !finished else { return }
        finished = true
        connection?.cancel()
        connection = nil
        onFinished?(outcome)
    }
}
