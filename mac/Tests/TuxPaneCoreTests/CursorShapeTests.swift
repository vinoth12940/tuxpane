import XCTest
@testable import TuxPaneCore

final class CursorShapeTests: XCTestCase {
    func testLayoutScalesSizeAndHotspotToViewPoints() {
        let shape = CursorShape(hotX: 4, hotY: 2, width: 24, height: 24, rgba: Data(count: 24 * 24 * 4))
        let layout = shape.layout(scale: 0.675)
        XCTAssertEqual(layout.size.width, 16.2, accuracy: 1e-9)
        XCTAssertEqual(layout.size.height, 16.2, accuracy: 1e-9)
        XCTAssertEqual(layout.hotSpot.x, 2.7, accuracy: 1e-9)
        XCTAssertEqual(layout.hotSpot.y, 1.35, accuracy: 1e-9)
    }

    func testEmptyOrTruncatedShapeIsInvalid() {
        XCTAssertFalse(CursorShape(hotX: 0, hotY: 0, width: 0, height: 0, rgba: Data()).isValid)
        XCTAssertFalse(CursorShape(hotX: 0, hotY: 0, width: 2, height: 2, rgba: Data(count: 3)).isValid)
        XCTAssertTrue(CursorShape(hotX: 0, hotY: 0, width: 1, height: 1, rgba: Data(count: 4)).isValid)
    }
}
