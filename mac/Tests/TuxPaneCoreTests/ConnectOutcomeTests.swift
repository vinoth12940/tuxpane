import XCTest
@testable import TuxPaneCore

final class ConnectOutcomeTests: XCTestCase {
    func testServerErrorsMapToOutcomes() {
        XCTAssertEqual(ConnectOutcome.fromServerError("authentication failed"), .authenticationFailed)
        XCTAssertEqual(
            ConnectOutcome.fromServerError("unsupported protocol version 1 (agent speaks 2); update"),
            .versionMismatch("unsupported protocol version 1 (agent speaks 2); update"))
        XCTAssertEqual(ConnectOutcome.fromServerError("capture failed: vaapi"), .captureFailed("capture failed: vaapi"))
        XCTAssertEqual(
            ConnectOutcome.fromServerError("agent cannot start capture: x"),
            .captureFailed("agent cannot start capture: x"))
        XCTAssertEqual(ConnectOutcome.fromServerError("weird"), .serverError("weird"))
    }
    func testCertificateMismatchHelp() {
        XCTAssertTrue(ConnectOutcome.certificateMismatch.help.contains("tuxpane pair"))
        XCTAssertTrue(ConnectOutcome.certificateMismatch.title.contains("certificate"))
    }
    func testEveryFailureNamesAConcreteNextStep() {
        let failures: [ConnectOutcome] = [
            .unreachable, .certificateMismatch, .authenticationFailed,
            .versionMismatch("v"), .captureFailed("c"), .serverError("s"), .connectionLost("x"),
        ]
        for outcome in failures { XCTAssertTrue(outcome.help.contains("tuxpane"), "\(outcome)") }
        XCTAssertTrue(ConnectOutcome.unreachable.help.contains("Tailscale"))
    }
    func testUpdateComparison() {
        XCTAssertTrue(UpdateChecker.isNewer(latestTag: "v1.0.1", current: "1.0.0"))
        XCTAssertTrue(UpdateChecker.isNewer(latestTag: "v1.10.0", current: "1.9.9"))
        XCTAssertFalse(UpdateChecker.isNewer(latestTag: "v1.0.0", current: "1.0.0"))
        XCTAssertFalse(UpdateChecker.isNewer(latestTag: "v0.9", current: "1.0.0"))
        XCTAssertFalse(UpdateChecker.isNewer(latestTag: "nightly", current: "1.0.0"))
    }

    func testConnectionLostMentionsAnotherOpenWindow() {
        XCTAssertTrue(ConnectOutcome.connectionLost("closed").help.contains("already connected"))
    }

    func testBeingReplacedByAnotherDeviceStopsReconnecting() {
        XCTAssertEqual(ConnectOutcome.fromServerError("replaced by another connection"), .replaced)
        XCTAssertFalse(ConnectOutcome.replaced.shouldReconnect)
        XCTAssertTrue(ConnectOutcome.unreachable.shouldReconnect)
        XCTAssertTrue(ConnectOutcome.replaced.help.contains("Connect"))
    }
}
