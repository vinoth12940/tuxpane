import XCTest
@testable import TuxPaneCore

private let fixture =
    "tuxpane1:eyJuIjoiZXhhbXBsZS1saW51eC1kZXNrdG9wLTAxIiwiaCI6WyIxOTIuMTY4LjEuMjAiLCIxMDAuNjQuMTAwLjI3Il0"
    + "sInAiOjczMDAsInQiOiJhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejAxMjM0NSIsImYiOiJhYWFhYWFhYWFhYWFhYWFhYWFhYWF"
    + "hYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhIn0"

private func code(_ json: String) -> String {
    "tuxpane1:"
        + Data(json.utf8).base64EncodedString()
        .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

final class PairingCodeTests: XCTestCase {
    func testParsesTheAgentFixture() throws {
        XCTAssertEqual(
            try PairingCode.parse(fixture),
            PairingInfo(
                name: "example-linux-desktop-01", hosts: ["192.168.1.20", "100.64.100.27"], port: 7300,
                token: "abcdefghijklmnopqrstuvwxyz012345", fingerprint: String(repeating: "a", count: 64)))
    }
    func testToleratesSurroundingWhitespace() throws {
        XCTAssertEqual(try PairingCode.parse("\n \(fixture) \n").port, 7300)
    }
    func testRejectsBadInput() {
        let fp = String(repeating: "b", count: 64)
        let cases: [(String, PairingError)] = [
            ("hello", .notAPairingCode), ("tuxpane1:@@@", .damaged),
            (String(fixture.dropLast(20)), .damaged),
            (code(#"{"h":["10.0.0.1"],"p":7300,"t":"abcdefghijklmnopqrstu","f":"\#(fp)"}"#), .incomplete),
            (code(#"{"n":"x","h":[],"p":7300,"t":"abcdefghijklmnopqrstu","f":"\#(fp)"}"#), .incomplete),
            (code(#"{"n":"x","h":["10.0.0.1"],"p":7300,"t":"abcdefghijklmnopqrstu","f":"abc"}"#), .badFingerprint),
            (
                code(#"{"n":"x","h":["8.8.8.8"],"p":7300,"t":"abcdefghijklmnopqrstu","f":"\#(fp)"}"#),
                .publicAddress("8.8.8.8")
            ),
        ]
        for (input, expected) in cases {
            XCTAssertThrowsError(try PairingCode.parse(input), input) { XCTAssertEqual($0 as? PairingError, expected) }
        }
    }
    func testErrorsExplainWhatToDo() {
        XCTAssertTrue(PairingError.notAPairingCode.localizedDescription.contains("tuxpane pair"))
    }
    /// Same lists as agent/tests/test_pairing.py: both sides must agree on what a Mac may dial.
    func testPairableAddressPolicyMatchesTheAgent() {
        let pairable = ["10.1.2.3", "172.16.0.1", "172.31.255.1", "192.168.0.9", "100.64.0.1", "100.127.1.1"]
        let notPairable = [
            "8.8.8.8", "172.32.0.1", "100.128.0.1", "198.18.0.1", "192.0.0.1", "240.0.0.1",
            "203.0.113.9", "169.254.1.1", "127.0.0.1", "1.2.3", "a.b.c.d", "300.1.1.1",
        ]
        for host in pairable { XCTAssertTrue(PrivateAddress.isAllowed(host), host) }
        for host in notPairable { XCTAssertFalse(PrivateAddress.isAllowed(host), host) }
    }

    func testUnusableAddressesAreSkippedWhenAnotherWorks() throws {
        let fp = String(repeating: "b", count: 64)
        let info = try PairingCode.parse(
            code(#"{"n":"x","h":["198.18.0.1","192.168.1.5"],"p":7300,"t":"abcdefghijklmnopqrstu","f":"\#(fp)"}"#))
        XCTAssertEqual(info.hosts, ["192.168.1.5"])
    }

    func testCodeWrappedByATerminalStillParses() throws {
        let chars = Array(fixture)
        let wrapped = String(chars[..<70]) + "\n  " + String(chars[70..<150]) + " \r\n" + String(chars[150...])
        XCTAssertEqual(try PairingCode.parse(wrapped).port, 7300)
    }

    func testFingerprint() {
        let hash = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        XCTAssertEqual(Fingerprint.sha256Hex(Data("abc".utf8)), hash)
        XCTAssertTrue(Fingerprint.matches(der: Data("abc".utf8), pinned: hash.uppercased()))
        XCTAssertFalse(Fingerprint.matches(der: Data("abd".utf8), pinned: hash))
    }
}
