import XCTest
@testable import TuxPaneCore

final class GeometryTests: XCTestCase {
    let mapper = CoordinateMapper(remoteWidth: 2560, remoteHeight: 1600)

    func testSameAspectFillsView() {
        XCTAssertEqual(
            mapper.videoRect(in: CGSize(width: 1728, height: 1080)), CGRect(x: 0, y: 0, width: 1728, height: 1080))
    }

    func testLetterboxedRectIsCentered() {
        XCTAssertEqual(
            mapper.videoRect(in: CGSize(width: 2000, height: 1000)), CGRect(x: 200, y: 0, width: 1600, height: 1000))
    }

    func testRemotePointMapsAndClamps() {
        let view = CGSize(width: 2000, height: 1000)
        XCTAssertTrue(mapper.remotePoint(for: CGPoint(x: 1000, y: 500), in: view)! == (1280, 800))
        XCTAssertTrue(mapper.remotePoint(for: CGPoint(x: 10, y: -5), in: view)! == (0, 0))
        XCTAssertTrue(mapper.remotePoint(for: CGPoint(x: 1999, y: 1200), in: view)! == (2559, 1599))
        XCTAssertNil(CoordinateMapper(remoteWidth: 0, remoteHeight: 0).remotePoint(for: .zero, in: view))
    }

    func testPointsPerRemotePixel() {
        XCTAssertEqual(mapper.pointsPerRemotePixel(in: CGSize(width: 1728, height: 1080)), 0.675, accuracy: 1e-9)
    }

    func testScrollAccumulatesTrackpadDeltas() {
        var scroll = ScrollAccumulator()
        XCTAssertTrue(scroll.add(dx: 0, dy: 5, precise: true) == (0, 0))
        XCTAssertTrue(scroll.add(dx: 0, dy: 5, precise: true) == (0, 0))
        XCTAssertTrue(scroll.add(dx: 0, dy: 5, precise: true) == (0, 1))
        XCTAssertTrue(scroll.add(dx: -30, dy: 0, precise: true) == (-2, 0))
        var wheel = ScrollAccumulator()
        XCTAssertTrue(wheel.add(dx: 0, dy: -1, precise: false) == (0, -1))
    }

    func testHEVCSplitSeparatesParameterSets() {
        let vps = Data([32 << 1, 1, 0xA])
        let sps = Data([33 << 1, 1, 0xB])
        let pps = Data([34 << 1, 1, 0xC])
        let aud = Data([35 << 1, 1, 0x50])
        let idr = Data([19 << 1, 1, 0xD])
        let parts = HEVC.split([aud, vps, sps, pps, idr])
        XCTAssertEqual(parts, HEVC.Parts(vps: vps, sps: sps, pps: pps, frame: [idr]))
        XCTAssertEqual(HEVC.lengthPrefixed([Data([1, 2]), Data([3])]), Data([0, 0, 0, 2, 1, 2, 0, 0, 0, 1, 3]))
    }

}
