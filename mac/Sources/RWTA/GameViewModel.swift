import Foundation
import SwiftUI
import CoreLocation

@MainActor
final class GameViewModel: ObservableObject {
    enum Phase {
        case launching
        case menu                 // pick load vs new
        case configuringNewGame   // detected city, awaiting address confirmation
        case playing
        case error(String)
    }

    @Published var phase: Phase = .launching
    @Published var saves: [SaveEntry] = []
    @Published var detectedLocation: GameLocation?
    @Published var location: GameLocation?
    @Published var turns: [ChatTurn] = []
    @Published var suggestions: [String] = []
    @Published var loadingMessage: String?
    @Published var isThinking = false
    @Published var imageLoading = false
    @Published var sceneImage: NSImage?
    @Published var imageHistory: [SceneImageEntry] = []
    @Published var currentImageIndex: Int = -1
    @Published var imageStyles: [ImageStyleChoice] = [ImageStyleChoice(id: "photo", name: "Photorealistic")]
    @Published var selectedStyleID = "photo"
    @Published var lastImagePrompt: String?
    @Published var sessionCost: Double = 0
    @Published var statusMessage: String?
    @Published var canRetryNarrator = false
    @Published var hasOpenAIKey = true

    let bridge = BackendBridge()

    init() {
        bridge.onEvent = { [weak self] event, payload in
            self?.handleEvent(event, payload: payload)
        }
    }

    func boot() async {
        do {
            try await bridge.start()
            hasOpenAIKey = bridge.hasOpenAIKey
            if !bridge.imageStyles.isEmpty {
                imageStyles = bridge.imageStyles
            }
            selectedStyleID = bridge.defaultImageStyleID
            await refreshSaves()
            phase = .menu
        } catch {
            phase = .error(error.localizedDescription)
        }
    }

    func refreshSaves() async {
        do {
            let result = try await bridge.request("list_saves")
            if let raw = result["saves"]?.value as? [Any] {
                let entries: [SaveEntry] = raw.compactMap { item in
                    guard let dict = item as? [String: Any] else { return nil }
                    let name = (dict["name"] as? String) ?? "?"
                    let updated = (dict["updated_at"] as? String) ?? ""
                    let path = (dict["path"] as? String) ?? ""
                    let previewImagePath = dict["preview_image_path"] as? String
                    let previewStyleName = dict["preview_style_name"] as? String
                    return SaveEntry(
                        name: name,
                        updated_at: updated,
                        path: path,
                        previewImagePath: previewImagePath,
                        previewStyleName: previewStyleName
                    )
                }
                self.saves = entries
            }
        } catch {
            statusMessage = "Failed to list saves: \(error.localizedDescription)"
        }
    }

    func detectLocation() async {
        do {
            let result = try await bridge.request("detect_location")
            self.detectedLocation = GameLocation(
                city: (result["city"]?.value as? String) ?? "",
                region: (result["region"]?.value as? String) ?? "",
                country: (result["country"]?.value as? String) ?? "",
                address: result["address"]?.value as? String,
                coordinate: makeCoord(result),
                gameTime: nil,
                weather: nil,
                saveName: nil
            )
            self.phase = .configuringNewGame
        } catch {
            self.phase = .error(error.localizedDescription)
        }
    }

    func startNewGame(address: String) async {
        guard let detected = detectedLocation else { return }
        isThinking = true
        loadingMessage = "Starting your story…"
        phase = .playing
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        let params: [String: Any] = [
            "city": detected.city,
            "region": detected.region,
            "country": detected.country,
            "address": trimmed.isEmpty ? NSNull() : trimmed,
            "latitude": detected.coordinate?.latitude ?? NSNull(),
            "longitude": detected.coordinate?.longitude ?? NSNull(),
            "style": selectedStyleID
        ]
        do {
            _ = try await bridge.request("new_game", params)
        } catch {
            statusMessage = "Failed to start: \(error.localizedDescription)"
        }
        isThinking = false
        loadingMessage = nil
    }

    func loadGame(_ entry: SaveEntry) async {
        isThinking = true
        loadingMessage = "Loading your story…"
        phase = .playing
        do {
            _ = try await bridge.request("load_game", ["name": entry.name])
        } catch {
            statusMessage = "Load failed: \(error.localizedDescription)"
        }
        isThinking = false
        loadingMessage = nil
    }

    func sendInput(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        // If the user typed 1/2/3 and we have suggestions, expand it.
        var actual = trimmed
        if let n = Int(trimmed), (1...suggestions.count).contains(n) {
            actual = suggestions[n - 1]
        }
        turns.append(ChatTurn(role: .user, text: actual))
        suggestions = []
        isThinking = true
        do {
            _ = try await bridge.request("input", ["text": actual])
        } catch {
            statusMessage = "Action failed: \(error.localizedDescription)"
            isThinking = false
        }
    }

    func look() async {
        isThinking = true
        do {
            _ = try await bridge.request("look")
        } catch {
            statusMessage = error.localizedDescription
        }
        isThinking = false
    }

    func regenerate() async {
        // Drop the most recent narrator turn from the visible history first
        // so the user sees the re-roll happening.
        if let lastNarratorIdx = turns.lastIndex(where: { $0.role == .narrator }) {
            turns.remove(at: lastNarratorIdx)
        }
        isThinking = true
        do {
            _ = try await bridge.request("regenerate")
        } catch {
            statusMessage = error.localizedDescription
        }
        isThinking = false
    }

    func retryNarratorWithFallback() async {
        canRetryNarrator = false
        isThinking = true
        loadingMessage = "Retrying with fallback model…"
        do {
            _ = try await bridge.request("retry_fallback", ["model": "gpt-5.5"])
            statusMessage = nil
        } catch {
            statusMessage = "Retry failed: \(error.localizedDescription)"
            canRetryNarrator = true
            isThinking = false
            loadingMessage = nil
        }
    }

    func saveGame() async {
        do {
            let r = try await bridge.request("save", [:])
            if let name = r["name"]?.value as? String {
                statusMessage = "Saved as \(name)"
            } else {
                statusMessage = "Saved"
            }
            await refreshSaves()
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    func selectImageStyle(_ styleID: String) async {
        selectedStyleID = styleID
        imageLoading = true
        do {
            _ = try await bridge.request("render_image", ["style": styleID])
        } catch {
            statusMessage = "Image render failed: \(error.localizedDescription)"
            imageLoading = false
        }
    }

    func showPreviousImage() {
        guard !imageHistory.isEmpty else { return }
        currentImageIndex = max(0, currentImageIndex - 1)
        applyCurrentImage()
    }

    func showNextImage() {
        guard !imageHistory.isEmpty else { return }
        currentImageIndex = min(imageHistory.count - 1, currentImageIndex + 1)
        applyCurrentImage()
    }

    func showLatestImage() {
        guard !imageHistory.isEmpty else { return }
        currentImageIndex = imageHistory.count - 1
        applyCurrentImage()
    }

    private func applyCurrentImage() {
        guard imageHistory.indices.contains(currentImageIndex) else { return }
        let entry = imageHistory[currentImageIndex]
        sceneImage = entry.image ?? NSImage(contentsOfFile: entry.path)
        lastImagePrompt = entry.prompt
        selectedStyleID = entry.styleID
    }

    func backToMenu() async {
        // Just return to the menu without quitting the backend; the player
        // can pick a different save.
        await refreshSaves()
        turns = []
        suggestions = []
        sceneImage = nil
        imageHistory = []
        currentImageIndex = -1
        lastImagePrompt = nil
        location = nil
        phase = .menu
    }

    func shutdown() {
        bridge.shutdown()
    }

    private func upsertImageEntry(_ incoming: SceneImageEntry) {
        if let idx = imageHistory.firstIndex(where: { $0.id == incoming.id }) {
            var merged = incoming
            if merged.image == nil { merged.image = imageHistory[idx].image }
            imageHistory[idx] = merged
        } else {
            imageHistory.append(incoming)
        }
    }

    private func parseImageEntry(_ payload: [String: AnyCodable]) -> SceneImageEntry? {
        guard let id = payload.string("id") else { return nil }
        let path = payload.string("path") ?? ""
        var image: NSImage?
        if let b64 = payload.string("data"), let data = Data(base64Encoded: b64) {
            image = NSImage(data: data)
        }
        if image == nil, !path.isEmpty {
            image = NSImage(contentsOfFile: path)
        }
        return SceneImageEntry(
            id: id,
            turnIndex: payload.int("turn_index") ?? 0,
            styleID: payload.string("style_id") ?? "photo",
            styleName: payload.string("style_name") ?? "Photorealistic",
            path: path,
            prompt: payload.string("prompt") ?? "",
            createdAt: payload.string("created_at") ?? "",
            image: image
        )
    }

    // MARK: - Event handling

    private func handleEvent(_ event: String, payload: [String: AnyCodable]) {
        switch event {
        case "loading":
            loadingMessage = payload.string("message")
        case "narrative":
            if let t = payload.string("text"), !t.isEmpty {
                turns.append(ChatTurn(role: .narrator, text: t))
            }
            loadingMessage = nil
            isThinking = false
            canRetryNarrator = false
        case "suggestions":
            if let items = payload.array("items") {
                suggestions = items.compactMap { $0.value as? String }
            } else {
                suggestions = []
            }
        case "location":
            self.location = GameLocation(
                city: payload.string("city") ?? "",
                region: payload.string("region") ?? "",
                country: payload.string("country") ?? "",
                address: payload.string("address"),
                coordinate: makeCoord(payload.mapValues { $0.value }),
                gameTime: payload.string("game_time"),
                weather: payload.string("weather"),
                saveName: payload.string("save_name")
            )
        case "image":
            let entry = parseImageEntry(payload)
            if let entry {
                upsertImageEntry(entry)
                if let idx = imageHistory.firstIndex(where: { $0.id == entry.id }) {
                    currentImageIndex = idx
                }
                applyCurrentImage()
            } else if let b64 = payload.string("data"), let data = Data(base64Encoded: b64),
                      let img = NSImage(data: data) {
                sceneImage = img
                lastImagePrompt = payload.string("prompt")
            }
            imageLoading = false
        case "image_history":
            if let rawEntries = payload.array("entries") {
                imageHistory = rawEntries.compactMap { item in
                    guard let dict = item.value as? [String: Any] else { return nil }
                    return parseImageEntry(dict.mapValues { AnyCodable($0) })
                }
            }
            currentImageIndex = payload.int("selected_index") ?? (imageHistory.isEmpty ? -1 : imageHistory.count - 1)
            if currentImageIndex >= imageHistory.count {
                currentImageIndex = imageHistory.count - 1
            }
            applyCurrentImage()
        case "image_loading":
            imageLoading = (payload.bool("loading") ?? false)
        case "image_error":
            imageLoading = false
            // Don't surface as a hard error — image is optional.
            if let m = payload.string("message") {
                FileHandle.standardError.write(Data("image error: \(m)\n".utf8))
            }
        case "history":
            if let msgs = payload.array("messages") {
                self.turns = msgs.compactMap { ac in
                    guard let dict = ac.value as? [String: Any] else { return nil }
                    let role = (dict["role"] as? String) ?? "assistant"
                    let text = (dict["text"] as? String) ?? ""
                    return ChatTurn(role: role == "user" ? .user : .narrator, text: text)
                }
            }
            if let s = payload.array("suggestions") {
                suggestions = s.compactMap { $0.value as? String }
            }
            isThinking = false
            loadingMessage = nil
        case "error":
            statusMessage = payload.string("message")
            canRetryNarrator = payload.bool("can_retry") ?? false
            isThinking = false
            loadingMessage = nil
        case "cost":
            sessionCost = payload.double("usd") ?? 0
        default:
            break
        }
    }
}

private func makeCoord(_ payload: [String: Any]) -> CLLocationCoordinate2D? {
    guard
        let lat = payload["latitude"] as? Double ?? (payload["latitude"] as? Int).map(Double.init),
        let lon = payload["longitude"] as? Double ?? (payload["longitude"] as? Int).map(Double.init)
    else { return nil }
    return CLLocationCoordinate2D(latitude: lat, longitude: lon)
}

private func makeCoord(_ payload: [String: AnyCodable]) -> CLLocationCoordinate2D? {
    let dict = payload.mapValues { $0.value }
    return makeCoord(dict)
}
