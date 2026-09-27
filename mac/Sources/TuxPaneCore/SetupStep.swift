import Foundation

/// The steps shown in the setup window's brand panel.
public enum SetupStep: Int, CaseIterable {
    case welcome, install, pair, keyboard

    public enum Progress: Equatable { case done, current, upcoming }

    public var title: String {
        switch self {
        case .welcome: return "Welcome"
        case .install: return "Install on Linux"
        case .pair: return "Pair"
        case .keyboard: return "Keyboard"
        }
    }

    public func state(current: SetupStep) -> Progress {
        rawValue < current.rawValue ? .done : rawValue == current.rawValue ? .current : .upcoming
    }
}
