import Foundation

/// Wire protocol shared with the Python agent. Frame = type:u8 | len:u32 BE | payload.
public enum MessageType: UInt8 {
    case hello = 0x01, welcome = 0x02, video = 0x03
    case key = 0x10, mouseMove = 0x11, mouseButton = 0x12, scroll = 0x13, releaseAll = 0x14, requestKeyframe = 0x15
    case ping = 0x20, pong = 0x21
    case clipboard = 0x30, cursor = 0x31
    case error = 0x7F
    case pairHello = 0x40, pairNonce = 0x41, pairReveal = 0x42, pairConfirm = 0x43
    case pairAbort = 0x44, pairAccept = 0x45, pairReject = 0x46
}

public enum WireError: Error, Equatable {
    case truncated
    case payloadTooLarge(Int)
    case badText
}

public struct Frame: Equatable {
    public let type: UInt8
    public let payload: Data

    public init(type: UInt8, payload: Data) {
        self.type = type
        self.payload = payload
    }
}

public enum Wire {
    public static let version: UInt16 = 2
    public static let maxPayload = 16 * 1024 * 1024

    public static func frame(_ type: MessageType, _ payload: Data = Data()) -> Data {
        var out = Data(capacity: 5 + payload.count)
        out.append(type.rawValue)
        out.appendBigEndian(UInt32(payload.count))
        out.append(payload)
        return out
    }

    public static func hello(token: String, width: UInt16, height: UInt16) -> Data {
        var payload = Data()
        payload.appendBigEndian(version)
        payload.appendBigEndian(width)
        payload.appendBigEndian(height)
        payload.append(Data(token.utf8))
        return frame(.hello, payload)
    }

    public static func key(evdev: UInt16, down: Bool) -> Data {
        var payload = Data()
        payload.appendBigEndian(evdev)
        payload.append(down ? 1 : 0)
        return frame(.key, payload)
    }

    public static func mouseMove(x: UInt16, y: UInt16) -> Data {
        var payload = Data()
        payload.appendBigEndian(x)
        payload.appendBigEndian(y)
        return frame(.mouseMove, payload)
    }

    public static func mouseButton(_ button: UInt8, down: Bool) -> Data {
        frame(.mouseButton, Data([button, down ? 1 : 0]))
    }

    public static func scroll(dx: Int, dy: Int) -> Data {
        frame(.scroll, Data([UInt8(bitPattern: Int8(clamping: dx)), UInt8(bitPattern: Int8(clamping: dy))]))
    }

    public static func releaseAll() -> Data { frame(.releaseAll) }

    public static func requestKeyframe() -> Data { frame(.requestKeyframe) }

    public static func ping(_ micros: UInt64) -> Data {
        var payload = Data()
        payload.appendBigEndian(micros)
        return frame(.ping, payload)
    }

    public static func clipboard(_ text: String) -> Data { frame(.clipboard, Data(text.utf8)) }
}

/// Reassembles frames from arbitrary TCP chunks.
public struct FrameParser {
    private var buffer = [UInt8]()

    public init() {}

    public mutating func append(_ data: Data) throws -> [Frame] {
        buffer.append(contentsOf: data)
        var frames = [Frame]()
        var start = 0
        while buffer.count - start >= 5 {
            let length =
                Int(buffer[start + 1]) << 24 | Int(buffer[start + 2]) << 16
                | Int(buffer[start + 3]) << 8 | Int(buffer[start + 4])
            guard length <= Wire.maxPayload else { throw WireError.payloadTooLarge(length) }
            guard buffer.count - start - 5 >= length else { break }
            frames.append(Frame(type: buffer[start], payload: Data(buffer[(start + 5)..<(start + 5 + length)])))
            start += 5 + length
        }
        buffer.removeFirst(start)
        return frames
    }
}

public enum ServerMessage: Equatable {
    case welcome(width: Int, height: Int, codec: UInt8, agentVersion: String)
    case video(pts: UInt64, keyframe: Bool, nals: [Data])
    case pong(UInt64)
    case clipboard(String)
    case cursor(hotX: Int, hotY: Int, width: Int, height: Int, rgba: Data)
    case error(String)
    case unknown(UInt8)

    public static func parse(_ frame: Frame) throws -> ServerMessage {
        var reader = ByteReader(frame.payload)
        switch MessageType(rawValue: frame.type) {
        case .welcome:
            let width = Int(try reader.uint(UInt16.self))
            let height = Int(try reader.uint(UInt16.self))
            let codec = try reader.uint(UInt8.self)
            return .welcome(
                width: width, height: height, codec: codec,
                agentVersion: String(decoding: reader.rest(), as: UTF8.self))
        case .video:
            let pts = try reader.uint(UInt64.self)
            let keyframe = try reader.uint(UInt8.self) != 0
            var nals = [Data]()
            while reader.remaining > 0 {
                let length = Int(try reader.uint(UInt32.self))
                nals.append(try reader.bytes(length))
            }
            return .video(pts: pts, keyframe: keyframe, nals: nals)
        case .pong:
            return .pong(try reader.uint(UInt64.self))
        case .clipboard:
            guard let text = String(data: reader.rest(), encoding: .utf8) else { throw WireError.badText }
            return .clipboard(text)
        case .cursor:
            let hotX = Int(try reader.uint(UInt16.self))
            let hotY = Int(try reader.uint(UInt16.self))
            let width = Int(try reader.uint(UInt16.self))
            let height = Int(try reader.uint(UInt16.self))
            let rgba = try reader.bytes(width * height * 4)
            return .cursor(hotX: hotX, hotY: hotY, width: width, height: height, rgba: rgba)
        case .error:
            return .error(String(decoding: reader.rest(), as: UTF8.self))
        default:
            return .unknown(frame.type)
        }
    }
}

struct ByteReader {
    private let storage: [UInt8]
    private var offset = 0

    init(_ data: Data) { storage = [UInt8](data) }

    var remaining: Int { storage.count - offset }

    mutating func uint<T: FixedWidthInteger & UnsignedInteger>(_: T.Type) throws -> T {
        let size = MemoryLayout<T>.size
        guard remaining >= size else { throw WireError.truncated }
        var value: T = 0
        for byte in storage[offset..<(offset + size)] { value = value << 8 | T(byte) }
        offset += size
        return value
    }

    mutating func bytes(_ count: Int) throws -> Data {
        guard count >= 0, remaining >= count else { throw WireError.truncated }
        defer { offset += count }
        return Data(storage[offset..<(offset + count)])
    }

    mutating func rest() -> Data {
        defer { offset = storage.count }
        return Data(storage[offset...])
    }
}

extension Data {
    mutating func appendBigEndian<T: FixedWidthInteger>(_ value: T) {
        Swift.withUnsafeBytes(of: value.bigEndian) { append(contentsOf: $0) }
    }
}
