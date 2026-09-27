import Foundation

public enum HEVC {
    public struct Parts: Equatable {
        public var vps: Data?
        public var sps: Data?
        public var pps: Data?
        public var frame: [Data]
    }

    public static func nalType(_ nal: Data) -> UInt8 {
        nal.isEmpty ? 0xFF : (nal[nal.startIndex] >> 1) & 0x3F
    }

    /// Separates parameter sets (needed for the format description) from the frame's slice NALs.
    public static func split(_ nals: [Data]) -> Parts {
        var parts = Parts(vps: nil, sps: nil, pps: nil, frame: [])
        for nal in nals {
            switch nalType(nal) {
            case 32: parts.vps = nal
            case 33: parts.sps = nal
            case 34: parts.pps = nal
            case 35, 0xFF: continue  // access unit delimiter / empty
            default: parts.frame.append(nal)
            }
        }
        return parts
    }

    /// 4-byte big-endian length before each NAL: the layout VideoToolbox expects.
    public static func lengthPrefixed(_ nals: [Data]) -> Data {
        var out = Data()
        for nal in nals {
            out.appendBigEndian(UInt32(nal.count))
            out.append(nal)
        }
        return out
    }
}
