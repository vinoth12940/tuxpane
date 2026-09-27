// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "TuxPane",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "TuxPaneCore"),
        .executableTarget(name: "TuxPane", dependencies: ["TuxPaneCore"]),
        .testTarget(name: "TuxPaneCoreTests", dependencies: ["TuxPaneCore"]),
    ]
)
