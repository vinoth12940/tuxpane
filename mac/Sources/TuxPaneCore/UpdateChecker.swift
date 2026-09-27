import Foundation

public enum UpdateChecker {
    public static func isNewer(latestTag: String, current: String) -> Bool {
        func parts(_ text: String) -> [Int]? {
            let trimmed = text.hasPrefix("v") ? String(text.dropFirst()) : text
            let numbers = trimmed.split(separator: ".").map { Int($0) }
            return numbers.contains(nil) || numbers.isEmpty ? nil : numbers.compactMap { $0 }
        }
        guard let latest = parts(latestTag), let installed = parts(current) else { return false }
        for index in 0..<max(latest.count, installed.count) {
            let a = index < latest.count ? latest[index] : 0
            let b = index < installed.count ? installed[index] : 0
            if a != b { return a > b }
        }
        return false
    }
}
