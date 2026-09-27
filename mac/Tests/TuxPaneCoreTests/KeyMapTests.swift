import XCTest
@testable import TuxPaneCore

private func ev(_ pairs: (UInt16, Bool)...) -> [KeyEvent] { pairs.map { KeyEvent(code: $0.0, down: $0.1) } }

final class KeyMapTests: XCTestCase {
    let t = KeyTranslator(macStyle: true)

    func testTableHasNoDuplicatesAndCoversLetters() {
        XCTAssertEqual(macToEvdev[0], 30)  // A
        XCTAssertEqual(macToEvdev[8], 46)  // C
        XCTAssertEqual(macToEvdev[36], 28)  // Return
        XCTAssertEqual(macToEvdev[122], 59)  // F1
        XCTAssertEqual(macToEvdev[126], 103)  // Up
    }

    func testPlainKey() {
        XCTAssertEqual(t.key(macKeycode: 0, down: true), ev((30, true)))
        XCTAssertEqual(t.key(macKeycode: 0, down: false), ev((30, false)))
        XCTAssertEqual(t.key(macKeycode: 0x3F_FF, down: true), [])
    }

    func testCmdCBecomesCtrlC() {
        XCTAssertEqual(t.modifiersChanged([.leftCmd]), ev((29, true)))
        XCTAssertEqual(t.key(macKeycode: 8, down: true), ev((46, true)))
        XCTAssertEqual(t.key(macKeycode: 8, down: false), ev((46, false)))
        XCTAssertEqual(t.modifiersChanged([]), ev((29, false)))
    }

    func testCtrlBecomesSuperInMacStyleAndCtrlInRaw() {
        XCTAssertEqual(t.modifiersChanged([.leftCtrl]), ev((125, true)))
        let raw = KeyTranslator(macStyle: false)
        XCTAssertEqual(raw.modifiersChanged([.leftCmd]), ev((125, true)))
        XCTAssertEqual(raw.modifiersChanged([.leftCtrl]), ev((125, false), (29, true)))
        XCTAssertEqual(raw.key(macKeycode: MacKey.tab, down: true), ev((15, true)))
    }

    func testCmdTabHoldsAltUntilCmdReleased() {
        XCTAssertEqual(t.modifiersChanged([.leftCmd]), ev((29, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.tab, down: true), ev((29, false), (56, true), (15, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.tab, down: false), ev((15, false)))
        XCTAssertEqual(t.key(macKeycode: MacKey.tab, down: true), ev((15, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.tab, down: false), ev((15, false)))
        XCTAssertEqual(t.modifiersChanged([]), ev((56, false)))
    }

    func testShiftCmdTabKeepsShift() {
        XCTAssertEqual(t.modifiersChanged([.leftCmd, .leftShift]), ev((42, true), (29, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.tab, down: true), ev((29, false), (56, true), (15, true)))
    }

    func testCmdSpaceTapsSuper() {
        _ = t.modifiersChanged([.leftCmd])
        XCTAssertEqual(t.key(macKeycode: MacKey.space, down: true), ev((29, false), (125, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.space, down: false), ev((125, false)))
    }

    func testCmdArrowsAreLineAndDocumentNavigation() {
        _ = t.modifiersChanged([.leftCmd])
        XCTAssertEqual(t.key(macKeycode: MacKey.left, down: true), ev((29, false), (102, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.left, down: false), ev((102, false)))
        XCTAssertEqual(t.key(macKeycode: MacKey.down, down: true), ev((29, true), (107, true)))
    }

    func testShiftCmdLeftSelectsToLineStart() {
        XCTAssertEqual(t.modifiersChanged([.leftCmd, .leftShift]), ev((42, true), (29, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.left, down: true), ev((29, false), (102, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.left, down: false), ev((102, false)))
    }

    func testOptionArrowJumpsWords() {
        XCTAssertEqual(t.modifiersChanged([.leftOption]), ev((56, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.left, down: true), ev((56, false), (29, true), (105, true)))
        XCTAssertEqual(t.key(macKeycode: MacKey.left, down: false), ev((105, false), (29, false)))
    }

    func testNoBareAltTapAfterOptionArrow() {
        _ = t.modifiersChanged([.leftOption])
        _ = t.key(macKeycode: MacKey.left, down: true)
        _ = t.key(macKeycode: MacKey.left, down: false)
        XCTAssertEqual(t.modifiersChanged([]), [])
    }

    func testModifiersComeBackLazilyForTheNextKey() {
        _ = t.modifiersChanged([.leftOption])
        _ = t.key(macKeycode: MacKey.left, down: true)
        _ = t.key(macKeycode: MacKey.left, down: false)
        XCTAssertEqual(t.key(macKeycode: 0, down: true), ev((56, true), (30, true)))
    }

    func testPrepareForPointerPressesHeldModifiers() {
        _ = t.modifiersChanged([.leftCmd])
        _ = t.key(macKeycode: MacKey.left, down: true)
        _ = t.key(macKeycode: MacKey.left, down: false)
        XCTAssertEqual(t.prepareForPointer(), ev((29, true)))
    }

    func testNoteModifiersReleasesAMissedCmdUp() {
        _ = t.modifiersChanged([.leftCmd])
        XCTAssertEqual(t.noteModifiers([]), ev((29, false)))
        XCTAssertEqual(t.key(macKeycode: 0, down: true), ev((30, true)))
    }

    func testCapsLockIsAToggleTap() {
        XCTAssertEqual(t.key(macKeycode: MacKey.capsLock, down: true), ev((58, true), (58, false)))
    }

    func testReleaseAllReleasesInReverseOrder() {
        _ = t.modifiersChanged([.leftCmd])
        _ = t.key(macKeycode: 0, down: true)
        XCTAssertEqual(t.releaseAll(), ev((30, false), (29, false)))
        XCTAssertEqual(t.releaseAll(), [])
    }

    func testHeldModifiersFromFlags() {
        XCTAssertEqual(HeldModifiers(cgFlags: 0x100108), [.leftCmd])
        XCTAssertEqual(HeldModifiers(cgFlags: 0x100110), [.rightCmd])
        XCTAssertEqual(HeldModifiers(cgFlags: 0x100000), [.leftCmd])  // no device bits: assume left
        XCTAssertEqual(HeldModifiers(cgFlags: 0x20004), [.rightShift])
        XCTAssertEqual(HeldModifiers(cgFlags: 0x0008), [])  // stale device bit without the generic one
    }

    func testReleaseChordIsCtrlOptionWithoutCmd() {
        XCTAssertTrue(KeyTranslator.isReleaseChord(flags: (1 << 18) | (1 << 19)))
        XCTAssertFalse(KeyTranslator.isReleaseChord(flags: (1 << 18) | (1 << 19) | (1 << 20)))
        XCTAssertFalse(KeyTranslator.isReleaseChord(flags: 1 << 18))
    }
}
