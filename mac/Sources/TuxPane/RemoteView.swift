import AppKit
import TuxPaneCore

/// Shows the video, forwards the mouse, and draws the Linux cursor shape as a native (zero-lag) cursor.
final class RemoteView: NSView {
    let renderer: VideoRenderer
    var mapper = CoordinateMapper(remoteWidth: 0, remoteHeight: 0) {
        didSet { window?.invalidateCursorRects(for: self) }
    }
    var onMouseMove: ((UInt16, UInt16) -> Void)?
    var onMouseButton: ((UInt8, Bool) -> Void)?
    var onScroll: ((Int, Int) -> Void)?
    var onClick: (() -> Void)?
    var onKeyEvent: ((NSEvent) -> Void)?
    var onKeyEquivalent: ((NSEvent) -> Bool)?

    private var scroll = ScrollAccumulator()
    private var remoteCursor = NSCursor.arrow
    private var cursorShape: CursorShape?
    private var cursorScale: CGFloat = 0
    private let statsLabel = NSTextField(labelWithString: "")

    init(renderer: VideoRenderer) {
        self.renderer = renderer
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = NSColor.black.cgColor
        layer?.addSublayer(renderer.layer)
        statsLabel.textColor = .white
        statsLabel.drawsBackground = true
        statsLabel.backgroundColor = NSColor.black.withAlphaComponent(0.6)
        statsLabel.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        statsLabel.isHidden = true
        addSubview(statsLabel)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func layout() {
        super.layout()
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        renderer.layer.frame = bounds
        CATransaction.commit()
        statsLabel.sizeToFit()
        statsLabel.setFrameOrigin(NSPoint(x: 8, y: 8))
        // The first cursor usually arrives mid full-screen animation; resize it once the view settles.
        if let cursorShape, mapper.pointsPerRemotePixel(in: bounds.size) != cursorScale { applyCursor(cursorShape) }
    }

    func showStats(_ text: String?) {
        statsLabel.stringValue = text ?? ""
        statsLabel.isHidden = text == nil
        needsLayout = true
    }

    // MARK: Mouse

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(
            NSTrackingArea(
                rect: .zero, options: [.mouseMoved, .activeInKeyWindow, .inVisibleRect, .cursorUpdate],
                owner: self))
    }

    private func sendPosition(_ event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        if let remote = mapper.remotePoint(for: point, in: bounds.size) { onMouseMove?(remote.x, remote.y) }
    }

    private static func xButton(_ number: Int) -> UInt8? {
        switch number {
        case 2: return 2
        case 3: return 8
        case 4: return 9
        default: return nil
        }
    }

    override func mouseMoved(with event: NSEvent) { sendPosition(event) }
    override func mouseDragged(with event: NSEvent) { sendPosition(event) }
    override func rightMouseDragged(with event: NSEvent) { sendPosition(event) }
    override func otherMouseDragged(with event: NSEvent) { sendPosition(event) }

    override func mouseDown(with event: NSEvent) {
        onClick?()
        sendPosition(event)
        onMouseButton?(1, true)
    }

    override func mouseUp(with event: NSEvent) {
        sendPosition(event)
        onMouseButton?(1, false)
    }

    override func rightMouseDown(with event: NSEvent) {
        sendPosition(event)
        onMouseButton?(3, true)
    }

    override func rightMouseUp(with event: NSEvent) {
        sendPosition(event)
        onMouseButton?(3, false)
    }

    override func otherMouseDown(with event: NSEvent) {
        sendPosition(event)
        if let button = Self.xButton(event.buttonNumber) { onMouseButton?(button, true) }
    }

    override func otherMouseUp(with event: NSEvent) {
        sendPosition(event)
        if let button = Self.xButton(event.buttonNumber) { onMouseButton?(button, false) }
    }

    override func scrollWheel(with event: NSEvent) {
        let steps = scroll.add(
            dx: event.scrollingDeltaX, dy: event.scrollingDeltaY, precise: event.hasPreciseScrollingDeltas)
        if steps.dx != 0 || steps.dy != 0 { onScroll?(steps.dx, steps.dy) }
    }

    // MARK: Keyboard fallback (only used when the event tap is unavailable)

    override func keyDown(with event: NSEvent) { onKeyEvent?(event) }
    override func keyUp(with event: NSEvent) { onKeyEvent?(event) }
    override func flagsChanged(with event: NSEvent) { onKeyEvent?(event) }

    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        onKeyEquivalent?(event) ?? super.performKeyEquivalent(with: event)
    }

    // MARK: Cursor

    func setRemoteCursor(_ shape: CursorShape) {
        cursorShape = shape
        applyCursor(shape)
    }

    private func applyCursor(_ shape: CursorShape) {
        let scale = mapper.pointsPerRemotePixel(in: bounds.size)
        cursorScale = scale
        guard shape.isValid, scale > 0,
            let rep = NSBitmapImageRep(
                bitmapDataPlanes: nil, pixelsWide: shape.width, pixelsHigh: shape.height,
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: shape.width * 4, bitsPerPixel: 32),
            let pixels = rep.bitmapData
        else { return }
        shape.rgba.copyBytes(to: pixels, count: shape.width * shape.height * 4)
        let layout = shape.layout(scale: scale)
        let image = NSImage(size: layout.size)
        image.addRepresentation(rep)
        remoteCursor = NSCursor(image: image, hotSpot: layout.hotSpot)
        window?.invalidateCursorRects(for: self)
        if let window, window.isKeyWindow, bounds.contains(convert(window.mouseLocationOutsideOfEventStream, from: nil))
        {
            remoteCursor.set()
        }
    }

    override func resetCursorRects() { addCursorRect(bounds, cursor: remoteCursor) }
    override func cursorUpdate(with event: NSEvent) { remoteCursor.set() }
}
