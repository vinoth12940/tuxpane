import AppKit
import TuxPaneCore

/// Two-way text clipboard sync; remembers the last value to avoid echo loops.
final class ClipboardSync {
    private let send: (Data) -> Void
    private var lastChangeCount = NSPasteboard.general.changeCount
    private var lastText: String?
    private var timer: Timer?

    init(send: @escaping (Data) -> Void) { self.send = send }

    func start() {
        stop()
        lastChangeCount = NSPasteboard.general.changeCount
        let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in self?.poll() }
        RunLoop.main.add(timer, forMode: .common)  // keep syncing while a menu is open
        self.timer = timer
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    func receive(_ text: String) {
        lastText = text
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        lastChangeCount = pasteboard.changeCount
    }

    private func poll() {
        let pasteboard = NSPasteboard.general
        guard pasteboard.changeCount != lastChangeCount else { return }
        lastChangeCount = pasteboard.changeCount
        guard let text = pasteboard.string(forType: .string), text != lastText, text.utf8.count <= 1 << 20 else {
            return
        }
        lastText = text
        send(Wire.clipboard(text))
    }
}
