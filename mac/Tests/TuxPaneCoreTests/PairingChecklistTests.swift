import XCTest
@testable import TuxPaneCore

final class PairingChecklistTests: XCTestCase {
    private func states(_ list: PairingChecklist) -> [PairingChecklist.State] {
        PairingChecklist.Step.allCases.map { list.state($0) }
    }

    func testHappyPathTicksEachCheckInOrder() {
        var list = PairingChecklist()
        list.start()
        XCTAssertEqual(states(list), [.running, .pending, .pending, .pending])
        list.secured()
        XCTAssertEqual(states(list), [.done, .done, .running, .pending])
        list.signedIn()
        XCTAssertEqual(states(list), [.done, .done, .done, .running])
        list.receivedVideo()
        XCTAssertEqual(states(list), [.done, .done, .done, .done])
    }

    func testEachFailureLandsOnItsOwnCheck() {
        var list = PairingChecklist()
        list.start()
        list.failed(.unreachable)
        XCTAssertEqual(states(list), [.failed, .pending, .pending, .pending])

        list.start()
        list.failed(.certificateMismatch)
        XCTAssertEqual(states(list), [.done, .failed, .pending, .pending])

        list.start()
        list.secured()
        list.failed(.authenticationFailed)
        XCTAssertEqual(states(list), [.done, .done, .failed, .pending])

        list.start()
        list.secured()
        list.signedIn()
        list.failed(.captureFailed("capture failed: x"))
        XCTAssertEqual(states(list), [.done, .done, .done, .failed])
    }

    func testUnexpectedDropFailsTheCheckInProgress() {
        var list = PairingChecklist()
        list.start()
        list.secured()
        list.failed(.connectionLost("closed"))
        XCTAssertEqual(states(list), [.done, .done, .failed, .pending])
    }

    func testStepsHaveTitles() {
        XCTAssertEqual(
            PairingChecklist.Step.allCases.map(\.title),
            ["Reaching the machine", "Checking its security certificate", "Signing in", "Receiving the picture"])
    }
}
