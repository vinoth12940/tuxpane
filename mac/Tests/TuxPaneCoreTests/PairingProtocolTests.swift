import XCTest

@testable import TuxPaneCore

private let fingerprint = Data(repeating: 0x11, count: 32)
private let agentNonce = Data(repeating: 0x22, count: 32)
private let macNonce = Data(repeating: 0x33, count: 32)

private func json(_ frame: Data) -> [String: Any] {
    (try? JSONSerialization.jsonObject(with: frame.dropFirst(5))) as? [String: Any] ?? [:]
}

private func frame(_ type: UInt8, _ object: [String: Any]) -> Frame {
    Frame(type: type, payload: try! JSONSerialization.data(withJSONObject: object))
}

final class PairingProtocolTests: XCTestCase {
    func testCodeMatchesThePythonVector() {
        XCTAssertEqual(
            PairingProtocol.code(fingerprint: fingerprint, agentNonce: agentNonce, macNonce: macNonce), "614 176")
        XCTAssertEqual(
            PairingProtocol.commitment(macNonce), "deb0e38ced1e41de6f92e70e80c418d2d356afaaa99e26f5939dbc7d3ef4772a")
    }

    func testMismatchedCertificateGivesDifferentCode() {
        XCTAssertNotEqual(
            PairingProtocol.code(
                fingerprint: Data(repeating: 0x12, count: 32), agentNonce: agentNonce, macNonce: macNonce),
            "614 176")
    }

    func testFullExchange() {
        var session = PairingClientSession(macName: "Sam's MacBook Pro", fingerprint: fingerprint, nonce: macNonce)
        let hello = session.start()
        XCTAssertEqual(hello.first, MessageType.pairHello.rawValue)
        XCTAssertEqual(json(hello)["commit"] as? String, PairingProtocol.commitment(macNonce))
        XCTAssertEqual(json(hello)["name"] as? String, "Sam's MacBook Pro")

        let reveal = session.receive(frame(0x41, ["nonce": String(repeating: "22", count: 32)]))
        XCTAssertEqual(reveal.first?.first, MessageType.pairReveal.rawValue)
        XCTAssertEqual(json(reveal[0])["nonce"] as? String, String(repeating: "33", count: 32))
        XCTAssertEqual(session.state, .awaitingConfirmation(code: "614 176"))

        XCTAssertEqual(session.confirm().first, MessageType.pairConfirm.rawValue)
        XCTAssertEqual(session.state, .waitingForLinux(code: "614 176"))

        _ = session.receive(
            frame(
                0x45,
                ["token": "token-token-token-1", "port": 7300, "hosts": ["192.168.1.20", "8.8.8.8"], "name": "box"]))
        XCTAssertEqual(
            session.state,
            .accepted(
                PairingInfo(
                    name: "box", hosts: ["192.168.1.20"], port: 7300, token: "token-token-token-1",
                    fingerprint: String(repeating: "11", count: 32))))
    }

    func testRejectionAndAbort() {
        var declined = PairingClientSession(macName: "Mac", fingerprint: fingerprint, nonce: macNonce)
        _ = declined.start()
        _ = declined.receive(frame(0x46, ["reason": "busy"]))
        XCTAssertEqual(declined.state, .rejected("busy"))

        var aborted = PairingClientSession(macName: "Mac", fingerprint: fingerprint, nonce: macNonce)
        _ = aborted.start()
        _ = aborted.receive(frame(0x41, ["nonce": String(repeating: "22", count: 32)]))
        XCTAssertEqual(aborted.abort("codes differ").first, MessageType.pairAbort.rawValue)
        XCTAssertEqual(aborted.state, .rejected("cancelled"))
    }

    func testMalformedMessagesFail() {
        var session = PairingClientSession(macName: "Mac", fingerprint: fingerprint, nonce: macNonce)
        _ = session.start()
        _ = session.receive(frame(0x41, ["nonce": "abc"]))
        XCTAssertEqual(session.state, .failed("The Linux machine sent an invalid pairing message."))
    }

    func testStepTracker() {
        XCTAssertEqual(SetupStep.allCases.map(\.title), ["Welcome", "Install on Linux", "Pair", "Keyboard"])
        XCTAssertEqual(SetupStep.allCases.map { $0.state(current: .pair) }, [.done, .done, .current, .upcoming])
    }

    /// An attacker may send NONCE and ACCEPT back to back: the Mac must never accept before the user confirms.
    func testAcceptBeforeTheUserConfirmsIsRefused() {
        var session = PairingClientSession(macName: "Mac", fingerprint: fingerprint, nonce: macNonce)
        _ = session.start()
        _ = session.receive(frame(0x41, ["nonce": String(repeating: "22", count: 32)]))
        _ = session.receive(
            frame(0x45, ["token": "token-token-token-1", "port": 7300, "hosts": ["192.168.1.20"], "name": "evil"]))
        guard case .failed = session.state else { return XCTFail("accepted without confirmation: \(session.state)") }
    }

    func testAcceptBeforeTheNonceIsRefused() {
        var session = PairingClientSession(macName: "Mac", fingerprint: fingerprint, nonce: macNonce)
        _ = session.start()
        _ = session.receive(
            frame(0x45, ["token": "token-token-token-1", "port": 7300, "hosts": ["192.168.1.20"], "name": "evil"]))
        guard case .failed = session.state else { return XCTFail("accepted without a code: \(session.state)") }
    }
}
