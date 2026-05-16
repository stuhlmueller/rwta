import Foundation

/// Manages the Python `rwta.gui_server` subprocess and provides a typed
/// async interface to it. All public callbacks are dispatched to the main
/// actor so SwiftUI views can mutate state safely.
@MainActor
final class BackendBridge: ObservableObject {

    @Published var isReady = false
    @Published var hasOpenAIKey = false
    @Published var imageStyles: [ImageStyleChoice] = []
    @Published var defaultImageStyleID = "photo"
    @Published var lastError: String?

    /// Closures fired for streamed events (the backend pushes notifications
    /// that aren't tied to a request, e.g. narrative chunks).
    var onEvent: (String, [String: AnyCodable]) -> Void = { _, _ in }

    private let process = Process()
    private let stdinPipe = Pipe()
    private let stdoutPipe = Pipe()
    private let stderrPipe = Pipe()

    private var nextID: Int = 1
    private var pending: [Int: CheckedContinuation<[String: AnyCodable], Error>] = [:]
    private var stdoutBuffer = Data()

    enum BridgeError: LocalizedError {
        case backendError(String)
        case spawnFailed(String)
        case decodeFailed(String)

        var errorDescription: String? {
            switch self {
            case .backendError(let m): return m
            case .spawnFailed(let m): return "Failed to start backend: \(m)"
            case .decodeFailed(let m): return "Bad backend response: \(m)"
            }
        }
    }

    /// Locate the Python interpreter and project root. Allows env overrides
    /// so the app can be launched against a different rwta checkout.
    private struct LaunchPlan {
        var executable: URL
        var arguments: [String]
        var workingDirectory: URL
        var environment: [String: String]
    }

    private func makeLaunchPlan() throws -> LaunchPlan {
        let env = ProcessInfo.processInfo.environment

        // Allow user override.
        let projectDir: URL
        if let override = env["RWTA_PROJECT_DIR"] {
            projectDir = URL(fileURLWithPath: override)
        } else {
            // Walk up from this executable's location to find the rwta repo.
            // In dev (`swift run`) the binary lives in
            // .../mac/.build/<config>/RWTA. The repo root is two levels up
            // from .build, i.e. parent of `mac/`.
            let exeURL = URL(fileURLWithPath: CommandLine.arguments[0])
                .resolvingSymlinksInPath()
            var dir = exeURL.deletingLastPathComponent()
            var found: URL?
            for _ in 0..<8 {
                let candidate = dir.appendingPathComponent("pyproject.toml")
                if FileManager.default.fileExists(atPath: candidate.path) {
                    found = dir
                    break
                }
                dir = dir.deletingLastPathComponent()
            }
            if let found {
                projectDir = found
            } else {
                projectDir = URL(fileURLWithPath: NSHomeDirectory())
                    .appendingPathComponent("Projects/personal/rwta")
            }
        }

        // Prefer `uv run` since the rwta project uses uv. Fall back to a venv
        // python if the project has a `.venv/bin/python`.
        var processEnv = env
        // PATH augmentation: GUI apps on macOS don't inherit shell PATH, so
        // explicitly add common Homebrew + user-local bin dirs where uv lives.
        let extraPaths = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "\(NSHomeDirectory())/.local/bin",
            "\(NSHomeDirectory())/.cargo/bin",
        ]
        let existingPath = processEnv["PATH"] ?? ""
        let mergedPath = (extraPaths + [existingPath]).filter { !$0.isEmpty }.joined(separator: ":")
        processEnv["PATH"] = mergedPath
        // Force unbuffered stdout so we get events as they happen.
        processEnv["PYTHONUNBUFFERED"] = "1"

        if let cmdOverride = env["RWTA_PYTHON_CMD"] {
            // User passed a full command string.
            let parts = cmdOverride.split(separator: " ").map(String.init)
            guard let first = parts.first else {
                throw BridgeError.spawnFailed("Empty RWTA_PYTHON_CMD")
            }
            return LaunchPlan(
                executable: URL(fileURLWithPath: first),
                arguments: Array(parts.dropFirst()) + ["-m", "rwta.gui_server"],
                workingDirectory: projectDir,
                environment: processEnv
            )
        }

        let venvPython = projectDir.appendingPathComponent(".venv/bin/python")
        if FileManager.default.fileExists(atPath: venvPython.path) {
            return LaunchPlan(
                executable: venvPython,
                arguments: ["-m", "rwta.gui_server"],
                workingDirectory: projectDir,
                environment: processEnv
            )
        }

        // Try /usr/bin/env to find uv via PATH.
        return LaunchPlan(
            executable: URL(fileURLWithPath: "/usr/bin/env"),
            arguments: ["uv", "run", "--directory", projectDir.path, "python", "-m", "rwta.gui_server"],
            workingDirectory: projectDir,
            environment: processEnv
        )
    }

    /// Launch the Python subprocess. Resolves once we receive the `ready` event.
    func start() async throws {
        let plan = try makeLaunchPlan()

        process.executableURL = plan.executable
        process.arguments = plan.arguments
        process.currentDirectoryURL = plan.workingDirectory
        process.environment = plan.environment
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        // Stdout reader: accumulate into a buffer and emit per-line.
        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            Task { @MainActor [weak self] in
                self?.handleStdout(chunk: data)
            }
        }

        // Stderr reader: surface backend logging into the host process's stderr
        // so it shows up in `swift run` output for debugging.
        stderrPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            FileHandle.standardError.write(data)
        }

        process.terminationHandler = { [weak self] proc in
            Task { @MainActor [weak self] in
                self?.handleTermination(status: proc.terminationStatus)
            }
        }

        do {
            try process.run()
        } catch {
            throw BridgeError.spawnFailed(error.localizedDescription)
        }

        // Wait for the `ready` event. The server emits it before reading any
        // request from stdin so this should arrive within ~100ms.
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            self.readyContinuation = cont
        }
    }

    private var readyContinuation: CheckedContinuation<Void, Error>?

    private func handleStdout(chunk: Data) {
        stdoutBuffer.append(chunk)
        while let nl = stdoutBuffer.firstIndex(of: 0x0A) {
            let lineData = stdoutBuffer.subdata(in: 0..<nl)
            stdoutBuffer.removeSubrange(0...nl)
            guard !lineData.isEmpty else { continue }
            handleLine(lineData)
        }
    }

    private func handleLine(_ data: Data) {
        guard
            let dict = try? JSONDecoder().decode([String: AnyCodable].self, from: data)
        else {
            if let s = String(data: data, encoding: .utf8) {
                FileHandle.standardError.write(Data("rwta: skipping bad JSON: \(s)\n".utf8))
            }
            return
        }

        // Ready event: special-cased to resolve start().
        if let event = dict["event"]?.value as? String {
            if event == "ready" {
                isReady = true
                hasOpenAIKey = (dict["has_openai_key"]?.value as? Bool) ?? false
                defaultImageStyleID = (dict["default_image_style"]?.value as? String) ?? "photo"
                if let rawStyles = dict["image_styles"]?.value as? [Any] {
                    imageStyles = rawStyles.compactMap { item in
                        guard let style = item as? [String: Any],
                              let id = style["id"] as? String,
                              let name = style["name"] as? String else { return nil }
                        return ImageStyleChoice(id: id, name: name)
                    }
                }
                readyContinuation?.resume()
                readyContinuation = nil
                return
            } else if event == "fatal" {
                let msg = (dict["message"]?.value as? String) ?? "fatal"
                lastError = msg
                readyContinuation?.resume(throwing: BridgeError.backendError(msg))
                readyContinuation = nil
                return
            } else {
                onEvent(event, dict)
                return
            }
        }

        // Response to a request.
        if let id = dict["id"]?.value as? Int {
            if let cont = pending.removeValue(forKey: id) {
                if let err = dict["error"]?.value as? String {
                    cont.resume(throwing: BridgeError.backendError(err))
                } else if let result = dict["result"]?.value as? [String: Any] {
                    cont.resume(returning: result.mapValues { AnyCodable($0) })
                } else {
                    cont.resume(returning: [:])
                }
            }
        }
    }

    private func handleTermination(status: Int32) {
        isReady = false
        if status != 0, lastError == nil {
            lastError = "Backend exited with code \(status)"
        }
        // Fail any in-flight requests.
        for (_, cont) in pending {
            cont.resume(throwing: BridgeError.backendError("Backend terminated"))
        }
        pending.removeAll()
        readyContinuation?.resume(throwing: BridgeError.backendError("Backend terminated"))
        readyContinuation = nil
    }

    /// Fire-and-forget JSON line. Used for `quit` etc.
    func sendRaw(_ object: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: []) else {
            return
        }
        var line = data
        line.append(0x0A)
        try? stdinPipe.fileHandleForWriting.write(contentsOf: line)
    }

    /// Send a request and await the response.
    func request(_ method: String, _ params: [String: Any] = [:]) async throws -> [String: AnyCodable] {
        let id = nextID
        nextID += 1
        let payload: [String: Any] = [
            "id": id,
            "method": method,
            "params": params
        ]
        return try await withCheckedThrowingContinuation { cont in
            pending[id] = cont
            sendRaw(payload)
        }
    }

    func shutdown() {
        sendRaw(["id": 0, "method": "quit"])
        // Give it a moment to drain.
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.5) { [process] in
            if process.isRunning { process.terminate() }
        }
    }
}
