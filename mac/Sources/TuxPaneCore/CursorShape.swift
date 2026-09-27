import CoreGraphics
import Foundation

/// The Linux cursor image (premultiplied RGBA) as sent by the agent.
public struct CursorShape: Equatable {
    public let hotX: Int
    public let hotY: Int
    public let width: Int
    public let height: Int
    public let rgba: Data

    public init(hotX: Int, hotY: Int, width: Int, height: Int, rgba: Data) {
        self.hotX = hotX
        self.hotY = hotY
        self.width = width
        self.height = height
        self.rgba = rgba
    }

    public var isValid: Bool { width > 0 && height > 0 && rgba.count >= width * height * 4 }

    /// Size and hotspot in view points when one remote pixel is `scale` points wide.
    public func layout(scale: CGFloat) -> (size: CGSize, hotSpot: CGPoint) {
        (
            CGSize(width: CGFloat(width) * scale, height: CGFloat(height) * scale),
            CGPoint(x: CGFloat(hotX) * scale, y: CGFloat(hotY) * scale)
        )
    }
}
