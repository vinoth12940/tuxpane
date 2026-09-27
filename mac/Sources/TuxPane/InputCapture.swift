import AppKit
import ApplicationServices
import TuxPaneCore
import os

/// Lifecycle events only; keystrokes are never logged.
let appLog = Logger(subsystem: "io.github.vinoth12940.tuxpane", category: "app")

/// Routes the Mac keyboard to Linux while the remote window is focused. A CGEventTap (Accessibility
/// permission) also catches system shortcuts like Cmd+Tab and Cmd+Space; without it, falls back to NSEvents.
final class InputCapture {
    let translator: KeyTranslator
    var send: (Data) -> Void = { _ in }
    var onCaptureChange: ((Bool) -> Void)?
    private(set) var captured = false
    private(set) var tapInstalled = false
    private var tap: CFMachPort?

    init(macStyle: Bool) { translator = KeyTranslator(macStyle: macStyle) }

    func setCaptured(_ on: Bool) {
        guard on != captured else { return }
        captured = on
        // The tap only runs while captured, so the rest of the Mac never waits on this app.
        if let tap { CGEvent.tapEnable(tap: tap, enable: on) }
        resetRemoteKeys()
        onCaptureChange?(on)
    }

    /// Releases every key/button on Linux and forgets local key state.
    func resetRemoteKeys() {
        _ = translator.releaseAll()
        send(Wire.releaseAll())
    }

    @discardableResult
    func installEventTap(prompt: Bool) -> Bool {
        if tapInstalled { return true }
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: prompt] as CFDictionary
        guard AXIsProcessTrustedWithOptions(options) else { return false }
        let types: [CGEventType] = [.keyDown, .keyUp, .flagsChanged]
        let mask = types.reduce(CGEventMask(0)) { $0 | (CGEventMask(1) << CGEventMask($1.rawValue)) }
        guard
            let tap = CGEvent.tapCreate(
                tap: .cghidEventTap, place: .headInsertEventTap, options: .defaultTap, eventsOfInterest: mask,
                callback: { _, type, event, refcon in
                    let capture = Unmanaged<InputCapture>.fromOpaque(refcon!).takeUnretainedValue()
                    return capture.handleTap(type: type, event: event)
                },
                userInfo: Unmanaged.passUnretained(self).toOpaque()
            )
        else {
            appLog.error("CGEvent.tapCreate failed")
            return false
        }
        appLog.notice("keyboard event tap installed")
        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: captured)
        self.tap = tap
        tapInstalled = true
        return true
    }

    private func handleTap(type: CGEventType, event: CGEvent) -> Unmanaged<CGEvent>? {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            appLog.error("event tap disabled by the system; re-enabling")
            if let tap, captured { CGEvent.tapEnable(tap: tap, enable: true) }
            return Unmanaged.passUnretained(event)
        }
        guard captured else { return Unmanaged.passUnretained(event) }
        let keycode = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
        if type == .keyDown || type == .keyUp {
            // Recover from a flagsChanged lost while the tap was disabled.
            emit(translator.noteModifiers(HeldModifiers(cgFlags: event.flags.rawValue)))
        }
        switch type {
        case .keyDown:
            if keycode == MacKey.escape && KeyTranslator.isReleaseChord(flags: event.flags.rawValue) {
                setCaptured(false)
                return nil
            }
            // Linux autorepeats held keys itself, so macOS repeats are dropped.
            if event.getIntegerValueField(.keyboardEventAutorepeat) == 0 {
                emit(translator.key(macKeycode: keycode, down: true))
            }
        case .keyUp:
            emit(translator.key(macKeycode: keycode, down: false))
        case .flagsChanged:
            flagsChanged(keycode: keycode, flags: event.flags.rawValue)
        default:
            return Unmanaged.passUnretained(event)
        }
        return nil
    }

    private func flagsChanged(keycode: UInt16, flags: UInt64) {
        if keycode == MacKey.capsLock {
            emit(translator.key(macKeycode: keycode, down: true))
        } else {
            emit(translator.modifiersChanged(HeldModifiers(cgFlags: flags)))
        }
    }

    /// Fallback path: NSEvents delivered to the focused view (no Cmd+Tab / Cmd+Space).
    func handle(_ event: NSEvent) {
        guard captured, !tapInstalled else { return }
        switch event.type {
        case .keyDown:
            if event.keyCode == MacKey.escape
                && KeyTranslator.isReleaseChord(flags: UInt64(event.modifierFlags.rawValue))
            {
                setCaptured(false)
            } else if !event.isARepeat {
                emit(translator.key(macKeycode: event.keyCode, down: true))
            }
        case .keyUp:
            emit(translator.key(macKeycode: event.keyCode, down: false))
        case .flagsChanged:
            flagsChanged(keycode: event.keyCode, flags: UInt64(event.modifierFlags.rawValue))
        default:
            break
        }
    }

    /// AppKit never delivers keyUp for Cmd shortcuts, so on the fallback path they are sent as a tap.
    func handleKeyEquivalent(_ event: NSEvent) -> Bool {
        guard captured, !tapInstalled else { return false }
        if !event.isARepeat {
            emit(translator.key(macKeycode: event.keyCode, down: true))
            emit(translator.key(macKeycode: event.keyCode, down: false))
        }
        return true
    }

    /// Called before a mouse button goes down so Cmd+click arrives as Ctrl+click.
    func prepareForPointer() {
        if captured { emit(translator.prepareForPointer()) }
    }

    private func emit(_ events: [KeyEvent]) {
        for event in events { send(Wire.key(evdev: event.code, down: event.down)) }
    }
}
