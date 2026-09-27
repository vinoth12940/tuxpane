import Foundation

/// Linux evdev key codes (linux/input-event-codes.h). The agent adds 8 to get X keycodes.
public enum Evdev {
    public static let backspace: UInt16 = 14, tab: UInt16 = 15, leftCtrl: UInt16 = 29, leftShift: UInt16 = 42
    public static let rightShift: UInt16 = 54, leftAlt: UInt16 = 56, capsLock: UInt16 = 58, rightCtrl: UInt16 = 97
    public static let rightAlt: UInt16 = 100, home: UInt16 = 102, left: UInt16 = 105, right: UInt16 = 106
    public static let end: UInt16 = 107, leftMeta: UInt16 = 125, rightMeta: UInt16 = 126
}

/// macOS virtual key codes (Carbon kVK_*).
public enum MacKey {
    public static let tab: UInt16 = 48, space: UInt16 = 49, backspace: UInt16 = 51, escape: UInt16 = 53
    public static let capsLock: UInt16 = 57, left: UInt16 = 123, right: UInt16 = 124, down: UInt16 = 125,
        up: UInt16 = 126
}

/// Non-modifier keys, by physical position (the Linux keyboard layout decides the character).
public let macToEvdev: [UInt16: UInt16] = [
    0: 30, 1: 31, 2: 32, 3: 33, 4: 35, 5: 34, 6: 44, 7: 45, 8: 46, 9: 47,  // A S D F H G Z X C V
    10: 86, 11: 48, 12: 16, 13: 17, 14: 18, 15: 19, 16: 21, 17: 20,  // § B Q W E R Y T
    18: 2, 19: 3, 20: 4, 21: 5, 22: 7, 23: 6, 24: 13, 25: 10, 26: 8, 27: 12, 28: 9, 29: 11,  // 1 2 3 4 6 5 = 9 7 - 8 0
    30: 27, 31: 24, 32: 22, 33: 26, 34: 23, 35: 25, 36: 28, 37: 38, 38: 36, 39: 40,  // ] O U [ I P Return L J '
    40: 37, 41: 39, 42: 43, 43: 51, 44: 53, 45: 49, 46: 50, 47: 52,  // K ; \ , / N M .
    48: 15, 49: 57, 50: 41, 51: 14, 53: 1,  // Tab Space ` Backspace Esc
    65: 83, 67: 55, 69: 78, 71: 69, 75: 98, 76: 96, 78: 74, 81: 117,  // keypad . * + Clear / Enter - =
    82: 82, 83: 79, 84: 80, 85: 81, 86: 75, 87: 76, 88: 77, 89: 71, 91: 72, 92: 73,  // keypad 0-9
    122: 59, 120: 60, 99: 61, 118: 62, 96: 63, 97: 64, 98: 65, 100: 66,  // F1-F8
    101: 67, 109: 68, 103: 87, 111: 88,  // F9-F12
    105: 183, 107: 184, 113: 185, 106: 186, 64: 187, 79: 188, 80: 189, 90: 190,  // F13-F20
    114: 110, 115: 102, 116: 104, 117: 111, 119: 107, 121: 109,  // Help=Insert Home PgUp Del End PgDn
    123: 105, 124: 106, 125: 108, 126: 103,  // arrows
    72: 115, 73: 114, 74: 113,  // volume up / down, mute
]

public struct KeyEvent: Equatable {
    public let code: UInt16
    public let down: Bool

    public init(code: UInt16, down: Bool) {
        self.code = code
        self.down = down
    }
}

/// Physically held modifier keys, left and right distinguished.
public struct HeldModifiers: OptionSet, Equatable {
    public let rawValue: UInt16
    public init(rawValue: UInt16) { self.rawValue = rawValue }

    public static let leftCtrl = HeldModifiers(rawValue: 1 << 0)
    public static let leftShift = HeldModifiers(rawValue: 1 << 1)
    public static let rightShift = HeldModifiers(rawValue: 1 << 2)
    public static let leftCmd = HeldModifiers(rawValue: 1 << 3)
    public static let rightCmd = HeldModifiers(rawValue: 1 << 4)
    public static let leftOption = HeldModifiers(rawValue: 1 << 5)
    public static let rightOption = HeldModifiers(rawValue: 1 << 6)
    public static let rightCtrl = HeldModifiers(rawValue: 1 << 7)

    /// Parses CGEventFlags / NSEvent.ModifierFlags raw values. The NX_DEVICE* bits give left/right;
    /// the generic bits (shift 17, control 18, option 19, command 20) are authoritative for up/down.
    public init(cgFlags flags: UInt64) {
        var held: HeldModifiers = []
        let device: [(UInt64, HeldModifiers)] = [
            (0x1, .leftCtrl), (0x2, .leftShift), (0x4, .rightShift), (0x8, .leftCmd),
            (0x10, .rightCmd), (0x20, .leftOption), (0x40, .rightOption), (0x2000, .rightCtrl),
        ]
        for (bit, modifier) in device where flags & bit != 0 { held.insert(modifier) }
        let generic: [(UInt64, HeldModifiers, HeldModifiers)] = [
            (1 << 17, [.leftShift, .rightShift], .leftShift),
            (1 << 18, [.leftCtrl, .rightCtrl], .leftCtrl),
            (1 << 19, [.leftOption, .rightOption], .leftOption),
            (1 << 20, [.leftCmd, .rightCmd], .leftCmd),
        ]
        for (bit, pair, fallback) in generic {
            if flags & bit == 0 {
                held.subtract(pair)
            } else if held.isDisjoint(with: pair) {
                held.insert(fallback)
            }
        }
        self = held
    }

    public var hasCmd: Bool { !isDisjoint(with: [.leftCmd, .rightCmd]) }
    public var hasOption: Bool { !isDisjoint(with: [.leftOption, .rightOption]) }
    public var hasCtrl: Bool { !isDisjoint(with: [.leftCtrl, .rightCtrl]) }
}

/// Turns Mac key events into Linux evdev events. In Mac-style mode Cmd acts as Ctrl, Ctrl as Super,
/// and a few Mac shortcuts (Cmd+Tab, Cmd+Space, Cmd/Option+arrows) become their Linux equivalents.
public final class KeyTranslator {
    public var macStyle: Bool

    private struct Override {
        let key: UInt16
        let modifiers: [UInt16]
        var startsCmdTab = false
    }

    private static let modifierCodes: Set<UInt16> = [
        Evdev.leftCtrl, Evdev.rightCtrl, Evdev.leftShift, Evdev.rightShift,
        Evdev.leftAlt, Evdev.rightAlt, Evdev.leftMeta, Evdev.rightMeta,
    ]

    private var held: HeldModifiers = []
    private var remoteDown: [UInt16] = []
    private var overrides: [(macKey: UInt16, override: Override)] = []
    private var cmdTabActive = false

    public init(macStyle: Bool = true) { self.macStyle = macStyle }

    /// Ctrl+Option (without Cmd) + Esc gives the keyboard back to the Mac.
    public static func isReleaseChord(flags: UInt64) -> Bool {
        flags & (1 << 18) != 0 && flags & (1 << 19) != 0 && flags & (1 << 20) == 0
    }

    public func modifiersChanged(_ newHeld: HeldModifiers) -> [KeyEvent] {
        held = newHeld
        if cmdTabActive && !held.hasCmd { cmdTabActive = false }
        return syncModifiers()
    }

    /// Re-reads the physical modifiers carried by any key event, releasing (never pressing) remote
    /// modifiers that are no longer held. Recovers from a missed flagsChanged without a stray tap.
    public func noteModifiers(_ newHeld: HeldModifiers) -> [KeyEvent] {
        held = newHeld
        if cmdTabActive && !held.hasCmd { cmdTabActive = false }
        return releaseUnwantedModifiers()
    }

    /// Presses the held modifiers before a click, so Cmd+click still arrives as Ctrl+click.
    public func prepareForPointer() -> [KeyEvent] { syncModifiers() }

    public func key(macKeycode: UInt16, down: Bool) -> [KeyEvent] {
        if macKeycode == MacKey.capsLock {
            return [KeyEvent(code: Evdev.capsLock, down: true), KeyEvent(code: Evdev.capsLock, down: false)]
        }
        if !down {
            if let index = overrides.firstIndex(where: { $0.macKey == macKeycode }) {
                let finished = overrides.remove(at: index).override
                // Base modifiers come back lazily at the next key: re-pressing them now would send a
                // bare Alt/Ctrl tap when the user lets go, which focuses the menu bar in many Linux apps.
                return release(finished.key) + releaseUnwantedModifiers()
            }
            guard let code = macToEvdev[macKeycode] else { return [] }
            return release(code)
        }
        if macStyle, let active = override(for: macKeycode) {
            overrides.append((macKeycode, active))
            if active.startsCmdTab { cmdTabActive = true }
            return syncModifiers() + press(active.key)
        }
        guard let code = macToEvdev[macKeycode] else { return [] }
        return syncModifiers() + press(code)
    }

    public func releaseAll() -> [KeyEvent] {
        let events = remoteDown.reversed().map { KeyEvent(code: $0, down: false) }
        remoteDown = []
        overrides = []
        cmdTabActive = false
        held = []
        return events
    }

    private func shiftCodes() -> [UInt16] {
        var codes = [UInt16]()
        if held.contains(.leftShift) { codes.append(Evdev.leftShift) }
        if held.contains(.rightShift) { codes.append(Evdev.rightShift) }
        return codes
    }

    private func baseModifiers() -> [UInt16] {
        var codes = shiftCodes()
        if held.contains(.leftOption) { codes.append(Evdev.leftAlt) }
        if held.contains(.rightOption) { codes.append(Evdev.rightAlt) }
        let (cmdLeft, cmdRight, ctrlLeft, ctrlRight) =
            macStyle
            ? (Evdev.leftCtrl, Evdev.rightCtrl, Evdev.leftMeta, Evdev.rightMeta)
            : (Evdev.leftMeta, Evdev.rightMeta, Evdev.leftCtrl, Evdev.rightCtrl)
        if held.contains(.leftCmd) { codes.append(cmdLeft) }
        if held.contains(.rightCmd) { codes.append(cmdRight) }
        if held.contains(.leftCtrl) { codes.append(ctrlLeft) }
        if held.contains(.rightCtrl) { codes.append(ctrlRight) }
        return codes
    }

    private func desiredModifiers() -> [UInt16] {
        if let latest = overrides.last { return latest.override.modifiers }
        if cmdTabActive { return shiftCodes() + [Evdev.leftAlt] }
        return baseModifiers()
    }

    private func syncModifiers() -> [KeyEvent] {
        var events = releaseUnwantedModifiers()
        for code in desiredModifiers() where !remoteDown.contains(code) {
            events += press(code)
        }
        return events
    }

    private func releaseUnwantedModifiers() -> [KeyEvent] {
        let target = desiredModifiers()
        let overrideKeys = Set(overrides.map { $0.override.key })
        var events = [KeyEvent]()
        for code in remoteDown
        where Self.modifierCodes.contains(code) && !overrideKeys.contains(code) && !target.contains(code) {
            events += release(code)
        }
        return events
    }

    private func press(_ code: UInt16) -> [KeyEvent] {
        guard !remoteDown.contains(code) else { return [] }
        remoteDown.append(code)
        return [KeyEvent(code: code, down: true)]
    }

    private func release(_ code: UInt16) -> [KeyEvent] {
        guard let index = remoteDown.firstIndex(of: code) else { return [] }
        remoteDown.remove(at: index)
        return [KeyEvent(code: code, down: false)]
    }

    private func override(for key: UInt16) -> Override? {
        guard !held.hasCtrl else { return nil }
        let shifts = shiftCodes()
        if held.hasCmd && !held.hasOption {
            switch key {
            case MacKey.tab: return Override(key: Evdev.tab, modifiers: shifts + [Evdev.leftAlt], startsCmdTab: true)
            case MacKey.space where shifts.isEmpty: return Override(key: Evdev.leftMeta, modifiers: [])
            case MacKey.left: return Override(key: Evdev.home, modifiers: shifts)
            case MacKey.right: return Override(key: Evdev.end, modifiers: shifts)
            case MacKey.up: return Override(key: Evdev.home, modifiers: shifts + [Evdev.leftCtrl])
            case MacKey.down: return Override(key: Evdev.end, modifiers: shifts + [Evdev.leftCtrl])
            default: return nil
            }
        }
        if held.hasOption && !held.hasCmd {
            switch key {
            case MacKey.left: return Override(key: Evdev.left, modifiers: shifts + [Evdev.leftCtrl])
            case MacKey.right: return Override(key: Evdev.right, modifiers: shifts + [Evdev.leftCtrl])
            case MacKey.backspace: return Override(key: Evdev.backspace, modifiers: [Evdev.leftCtrl])
            default: return nil
            }
        }
        return nil
    }
}
