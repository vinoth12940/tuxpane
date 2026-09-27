import CoreGraphics
import Foundation

public enum ResolutionPreset: String, Codable, CaseIterable {
    case balanced, sharp, fast
    public var title: String {
        switch self {
        case .balanced: return "Balanced"
        case .sharp: return "Sharp (native)"
        case .fast: return "Fast"
        }
    }
    public func size(forScreenPixels pixels: CGSize) -> (width: Int, height: Int) {
        let target: CGFloat
        switch self {
        case .balanced: target = 2560
        case .fast: target = 1920
        case .sharp: target = pixels.width
        }
        let width = Int(min(target, pixels.width)) & ~1
        let height = Int((CGFloat(width) * pixels.height / pixels.width).rounded()) & ~1
        return (width, height)
    }
}

public struct Machine: Codable, Equatable, Identifiable {
    public var id: UUID
    public var name: String
    public var hosts: [String]
    public var port: UInt16
    public var fingerprint: String
    public var preset: ResolutionPreset

    public init(id: UUID = UUID(), pairing: PairingInfo, preset: ResolutionPreset = .balanced) {
        self.id = id
        name = pairing.name
        hosts = pairing.hosts
        port = pairing.port
        fingerprint = pairing.fingerprint
        self.preset = preset
    }
}
