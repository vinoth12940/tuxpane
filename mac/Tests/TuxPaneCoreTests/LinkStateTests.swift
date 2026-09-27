import XCTest
@testable import TuxPaneCore

final class LinkStateTests: XCTestCase {
    func testOnlyHelloIsSentBeforeWelcome() {
        var link = LinkState()
        link.connecting(now: 0)
        XCTAssertTrue(link.allowsSending(Wire.hello(token: "t", width: 1, height: 1)))
        XCTAssertFalse(link.allowsSending(Wire.mouseMove(x: 1, y: 1)))
        link.received(.welcome(width: 1, height: 1, codec: 1, agentVersion: "1.0.0"), now: 0)
        XCTAssertTrue(link.allowsSending(Wire.mouseMove(x: 1, y: 1)))
    }

    func testBackoffGrowsAndResetsOnWelcome() {
        var link = LinkState()
        XCTAssertEqual(
            [link.disconnected(), link.disconnected(), link.disconnected(), link.disconnected()], [1, 2, 4, 5])
        link.received(.welcome(width: 1, height: 1, codec: 1, agentVersion: "1.0.0"), now: 0)
        XCTAssertEqual(link.disconnected(), 1)
    }

    func testServerErrorIsStickyAndWaitsLongest() {
        var link = LinkState()
        link.received(.error("authentication failed"), now: 0)
        XCTAssertEqual(link.disconnected(), 5)
        XCTAssertEqual(link.serverError, "authentication failed")
        link.received(.welcome(width: 1, height: 1, codec: 1, agentVersion: "1.0.0"), now: 0)
        XCTAssertNil(link.serverError)
    }

    func testSilentLinkBecomesStale() {
        var link = LinkState()
        link.connecting(now: 0)
        XCTAssertFalse(link.isStale(now: 100))
        link.received(.welcome(width: 1, height: 1, codec: 1, agentVersion: "1.0.0"), now: 0)
        XCTAssertFalse(link.isStale(now: 4.9))
        XCTAssertTrue(link.isStale(now: 5.1))
        link.received(.pong(1), now: 5)
        XCTAssertFalse(link.isStale(now: 9))
    }

    func testNewAttemptForgetsTheOldServerError() {
        var link = LinkState()
        link.received(.error("capture failed: no desktop"), now: 0)
        XCTAssertEqual(link.disconnected(), 5)
        link.connecting(now: 1)
        XCTAssertNil(link.serverError, "a later certificate change must not be reported as the old capture error")
        XCTAssertEqual(link.disconnected(), 2)
    }
}
