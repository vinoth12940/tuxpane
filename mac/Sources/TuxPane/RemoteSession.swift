import AppKit
import TuxPaneCore

final class RemoteSession: NSObject, NSWindowDelegate {
    var onClose: (() -> Void)?
    /// The saved pairing no longer works (keys were reset); the app offers to pair again.
    var onNeedsPairing: ((ConnectOutcome) -> Void)?
    private var offeredRepair = false
    var statsVisible: Bool { didSet { tick() } }
    let machine: Machine
    private let window: NSWindow
    private let view: RemoteView
    private let renderer: VideoRenderer
    private let connection: Connection
    private let capture: InputCapture
    private let clipboard: ClipboardSync
    private var statsTimer: Timer?
    private var connected = false, closed = false
    private var status = "Connecting…", frames = 0, bytes = 0
    private var rttMs: Double?

    init(machine: Machine, token: String, capture: InputCapture, statsVisible: Bool) {
        self.machine = machine
        self.capture = capture
        self.statsVisible = statsVisible
        let size = machine.preset.size(forScreenPixels: Self.fullScreenPixels())
        let connection = Connection(machine: machine, token: token, requestedSize: size, reconnect: true)
        self.connection = connection
        clipboard = ClipboardSync(send: { [weak connection] in connection?.send($0) })
        let renderer = VideoRenderer()
        self.renderer = renderer
        view = RemoteView(renderer: renderer)
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
            styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        super.init()
        window.title = machine.name
        window.contentView = view
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.fullScreenPrimary]
        wire()
    }
    static func fullScreenPixels() -> CGSize {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return CGSize(width: 2560, height: 1600) }
        let height = screen.frame.height - screen.safeAreaInsets.top
        return CGSize(width: screen.frame.width * screen.backingScaleFactor, height: height * screen.backingScaleFactor)
    }
    private func wire() {
        let send: (Data) -> Void = { [weak connection] in connection?.send($0) }
        view.onMouseMove = { send(Wire.mouseMove(x: $0, y: $1)) }
        view.onMouseButton = { [weak self] button, down in
            if down { self?.capture.prepareForPointer() }
            send(Wire.mouseButton(button, down: down))
        }
        view.onScroll = { send(Wire.scroll(dx: $0, dy: $1)) }
        view.onClick = { [weak self] in
            guard let self, self.connected else { return }
            self.capture.setCaptured(true)
        }
        view.onKeyEvent = { [weak self] in self?.capture.handle($0) }
        view.onKeyEquivalent = { [weak self] in self?.capture.handleKeyEquivalent($0) ?? false }
        renderer.onNeedKeyframe = { send(Wire.requestKeyframe()) }
        connection.onMessage = { [weak self] in self?.handle($0) }
        connection.onStatus = { [weak self] in self?.status = $0 }
        connection.onDisconnect = { [weak self] in
            guard let self else { return }
            self.connected = false
            self.view.mapper = CoordinateMapper(remoteWidth: 0, remoteHeight: 0)
            self.capture.setCaptured(false)
            self.clipboard.stop()
            self.renderer.reset()
        }
        connection.onOutcome = { [weak self] outcome in
            guard let self, outcome != .connected else { return }
            self.status = "\(outcome.title). \(outcome.help)"
            if outcome == .certificateMismatch || outcome == .authenticationFailed, !self.offeredRepair {
                self.offeredRepair = true  // once per window, not on every reconnect attempt
                self.onNeedsPairing?(outcome)
            }
        }
    }
    func start() {
        capture.send = { [weak connection] in connection?.send($0) }
        window.center()
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(view)
        connection.start()
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer, forMode: .common)
        statsTimer = timer
        window.toggleFullScreen(nil)
    }
    /// True when a new pairing is for this same machine (same certificate, or same name and a shared address).
    func matches(_ info: PairingInfo) -> Bool {
        machine.fingerprint == info.fingerprint
            || (machine.name == info.name && !Set(machine.hosts).isDisjoint(with: info.hosts))
    }

    func close() { window.close() }
    func releaseKeyboard() { capture.setCaptured(false) }
    func toggleFullScreen() { window.toggleFullScreen(nil) }
    func updateCapture() { capture.setCaptured(connected && NSApp.isActive && window.isKeyWindow) }
    func windowDidBecomeKey(_ notification: Notification) { updateCapture() }
    func windowDidResignKey(_ notification: Notification) { updateCapture() }
    func windowWillClose(_ notification: Notification) {
        guard !closed else { return }
        closed = true
        statsTimer?.invalidate()
        capture.setCaptured(false)
        capture.send = { _ in }
        connection.stop()
        clipboard.stop()
        onClose?()
    }
    private func handle(_ message: ServerMessage) {
        switch message {
        case let .welcome(width, height, _, _):
            connected = true
            view.mapper = CoordinateMapper(remoteWidth: width, remoteHeight: height)
            renderer.reset()
            clipboard.start()
            status = "Connected \(width)×\(height)"
            updateCapture()
        case let .video(_, keyframe, nals):
            frames += 1
            bytes += nals.reduce(0) { $0 + $1.count }
            renderer.enqueue(nals: nals, keyframe: keyframe)
        case let .pong(sent): rttMs = Double(Self.nowMicros() &- sent) / 1000
        case let .clipboard(text): clipboard.receive(text)
        case let .cursor(hotX, hotY, width, height, rgba):
            view.setRemoteCursor(CursorShape(hotX: hotX, hotY: hotY, width: width, height: height, rgba: rgba))
        case let .error(text): appLog.error("server error: \(text, privacy: .public)")
        case .unknown: break
        }
    }
    private static func nowMicros() -> UInt64 { DispatchTime.now().uptimeNanoseconds / 1000 }
    private func tick() {
        if connected { connection.send(Wire.ping(Self.nowMicros())) }
        let rtt = rttMs.map { String(format: "%.1f ms", $0) } ?? "–"
        let warnings =
            (capture.tapInstalled
                ? []
                : [
                    "Allow TuxPane in System Settings › Privacy & Security › Accessibility so ⌘Tab and ⌘Space reach Linux"
                ])
            + (connected && !capture.captured ? ["Keyboard released: click the picture to capture it"] : [])
        let line =
            connected
            ? "\(frames) fps · \(String(format: "%.1f", Double(bytes) * 8 / 1e6)) Mbit/s · RTT \(rtt)" : status
        let shown = (statsVisible || !connected ? [line] : []) + warnings
        view.showStats(shown.isEmpty ? nil : shown.joined(separator: "\n"))
        frames = 0
        bytes = 0
    }
}
