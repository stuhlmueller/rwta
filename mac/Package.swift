// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "RWTA",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "RWTA", targets: ["RWTA"])
    ],
    targets: [
        .executableTarget(
            name: "RWTA",
            path: "Sources/RWTA"
        )
    ]
)
