import XCTest
@testable import TuxPaneCore

final class WireTests: XCTestCase {
    func testHelloBytesMatchPythonAgent() {
        XCTAssertEqual(
            [UInt8](Wire.hello(token: "abc", width: 2560, height: 1600)),
            [0x01, 0, 0, 0, 9, 0, 2, 0x0A, 0x00, 0x06, 0x40, 0x61, 0x62, 0x63])
    }

    func testInputMessages() {
        XCTAssertEqual([UInt8](Wire.key(evdev: 30, down: true)), [0x10, 0, 0, 0, 3, 0, 30, 1])
        XCTAssertEqual([UInt8](Wire.mouseMove(x: 258, y: 1)), [0x11, 0, 0, 0, 4, 1, 2, 0, 1])
        XCTAssertEqual([UInt8](Wire.mouseButton(3, down: false)), [0x12, 0, 0, 0, 2, 3, 0])
        XCTAssertEqual([UInt8](Wire.releaseAll()), [0x14, 0, 0, 0, 0])
    }

    func testScrollClampsToInt8() {
        XCTAssertEqual([UInt8](Wire.scroll(dx: 500, dy: -500)), [0x13, 0, 0, 0, 2, 0x7F, 0x80])
    }

    func testParserHandlesSplitAndMultipleFrames() throws {
        var parser = FrameParser()
        let bytes = Wire.ping(5) + Wire.releaseAll()
        XCTAssertEqual(try parser.append(bytes.prefix(7)), [])
        XCTAssertEqual(
            try parser.append(bytes.dropFirst(7)),
            [
                Frame(type: 0x20, payload: Data([0, 0, 0, 0, 0, 0, 0, 5])),
                Frame(type: 0x14, payload: Data()),
            ])
    }

    func testParserRejectsHugeFrames() {
        var parser = FrameParser()
        XCTAssertThrowsError(try parser.append(Data([0x03, 0x7F, 0xFF, 0xFF, 0xFF])))
    }

    func testParsesServerMessages() throws {
        var welcome = Data([0x0A, 0x00, 0x06, 0x40, 1])
        welcome.append(Data("1.0.0".utf8))
        XCTAssertEqual(
            try ServerMessage.parse(Frame(type: 0x02, payload: welcome)),
            .welcome(width: 2560, height: 1600, codec: 1, agentVersion: "1.0.0"))
        let video = Data([0, 0, 0, 0, 0, 0, 0, 7, 1, 0, 0, 0, 3, 0x26, 0x01, 0xAA])
        XCTAssertEqual(
            try ServerMessage.parse(Frame(type: 0x03, payload: video)),
            .video(pts: 7, keyframe: true, nals: [Data([0x26, 0x01, 0xAA])]))
        XCTAssertEqual(
            try ServerMessage.parse(Frame(type: 0x31, payload: Data([0, 1, 0, 2, 0, 1, 0, 1, 9, 8, 7, 6]))),
            .cursor(hotX: 1, hotY: 2, width: 1, height: 1, rgba: Data([9, 8, 7, 6])))
        XCTAssertEqual(try ServerMessage.parse(Frame(type: 0x30, payload: Data("hé".utf8))), .clipboard("hé"))
        XCTAssertEqual(try ServerMessage.parse(Frame(type: 0x21, payload: Data([0, 0, 0, 0, 0, 0, 1, 0]))), .pong(256))
        XCTAssertEqual(try ServerMessage.parse(Frame(type: 0x7F, payload: Data("no".utf8))), .error("no"))
        XCTAssertEqual(try ServerMessage.parse(Frame(type: 0x55, payload: Data())), .unknown(0x55))
    }

    func testTruncatedVideoThrows() {
        let video = Data([0, 0, 0, 0, 0, 0, 0, 7, 1, 0, 0, 0, 10, 0x26])
        XCTAssertThrowsError(try ServerMessage.parse(Frame(type: 0x03, payload: video)))
    }
}
