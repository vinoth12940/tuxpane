import CoreGraphics

/// Maps view coordinates (top-left origin) to remote screen pixels for an aspect-fit video.
public struct CoordinateMapper {
    public var remoteWidth: Int
    public var remoteHeight: Int

    public init(remoteWidth: Int, remoteHeight: Int) {
        self.remoteWidth = remoteWidth
        self.remoteHeight = remoteHeight
    }

    public func videoRect(in view: CGSize) -> CGRect {
        guard remoteWidth > 0, remoteHeight > 0, view.width > 0, view.height > 0 else { return .zero }
        let scale = min(view.width / CGFloat(remoteWidth), view.height / CGFloat(remoteHeight))
        let size = CGSize(width: CGFloat(remoteWidth) * scale, height: CGFloat(remoteHeight) * scale)
        return CGRect(
            x: (view.width - size.width) / 2, y: (view.height - size.height) / 2,
            width: size.width, height: size.height)
    }

    public func remotePoint(for point: CGPoint, in view: CGSize) -> (x: UInt16, y: UInt16)? {
        let rect = videoRect(in: view)
        guard rect.width > 0, rect.height > 0 else { return nil }
        let x = Int(((point.x - rect.minX) / rect.width * CGFloat(remoteWidth)).rounded(.down))
        let y = Int(((point.y - rect.minY) / rect.height * CGFloat(remoteHeight)).rounded(.down))
        return (UInt16(clamping: min(max(x, 0), remoteWidth - 1)), UInt16(clamping: min(max(y, 0), remoteHeight - 1)))
    }

    public func pointsPerRemotePixel(in view: CGSize) -> CGFloat {
        guard remoteWidth > 0 else { return 0 }
        return videoRect(in: view).width / CGFloat(remoteWidth)
    }
}

/// Converts NSEvent scroll deltas (positive = up/left) into whole X wheel clicks.
public struct ScrollAccumulator {
    public var pointsPerStep: Double = 12
    private var x = 0.0
    private var y = 0.0

    public init() {}

    public mutating func add(dx: Double, dy: Double, precise: Bool) -> (dx: Int, dy: Int) {
        let unit = precise ? pointsPerStep : 1
        x += dx / unit
        y += dy / unit
        let stepX = Int(x.rounded(.towardZero))
        let stepY = Int(y.rounded(.towardZero))
        x -= Double(stepX)
        y -= Double(stepY)
        return (stepX, stepY)
    }

    public mutating func reset() {
        x = 0
        y = 0
    }
}
