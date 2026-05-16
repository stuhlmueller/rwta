import SwiftUI
import MapKit
import CoreLocation

struct PlayView: View {
    @EnvironmentObject var vm: GameViewModel

    var body: some View {
        GeometryReader { geo in
            let leftWidth = min(max(430, geo.size.width * 0.42), min(560, geo.size.width - 260))
            HStack(spacing: 0) {
                VStack(spacing: 12) {
                    MapPanel()
                        .frame(height: 210)
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 18).stroke(GameTheme.brass.opacity(0.45)))
                    ChatPanel()
                }
                .padding(14)
                .background(GameTheme.panel.opacity(0.94))
                .frame(width: leftWidth, height: geo.size.height)
                .clipped()
                .zIndex(1)

                ScenePanel()
                    .frame(width: max(0, geo.size.width - leftWidth), height: geo.size.height)
                    .clipped()
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .leading)
        }
        .background(GameTheme.night)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button { Task { await vm.look() } } label: {
                    Label("Look", systemImage: "eye")
                }
                Button { Task { await vm.regenerate() } } label: {
                    Label("Regenerate", systemImage: "arrow.clockwise")
                }
                Button { Task { await vm.saveGame() } } label: {
                    Label("Save", systemImage: "square.and.arrow.down")
                }
                Button { Task { await vm.backToMenu() } } label: {
                    Label("Menu", systemImage: "house")
                }
            }
        }
    }
}

// MARK: - Chat panel

private struct ChatPanel: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var input = ""
    @FocusState private var inputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(GameTheme.brass.opacity(0.45))

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        ForEach(vm.turns) { turn in
                            TurnView(turn: turn)
                                .id(turn.id)
                        }
                        if let loading = vm.loadingMessage {
                            HStack(spacing: 8) {
                                ProgressView().controlSize(.small)
                                Text(loading)
                                    .italic()
                                    .foregroundStyle(GameTheme.ink.opacity(0.65))
                            }
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .id("loading")
                        }
                    }
                    .padding(16)
                }
                .background(GameTheme.parchmentLight.opacity(0.94))
                .onChange(of: vm.turns.count) { _, _ in
                    if let last = vm.turns.last {
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
                .onChange(of: vm.loadingMessage) { _, msg in
                    if msg != nil {
                        withAnimation { proxy.scrollTo("loading", anchor: .bottom) }
                    }
                }
            }

            if !vm.suggestions.isEmpty {
                SuggestionsBar(suggestions: vm.suggestions) { picked in
                    input = picked
                    Task { await submit() }
                }
            }

            Divider().overlay(GameTheme.brass.opacity(0.45))
            inputBar

            if let status = vm.statusMessage {
                HStack(spacing: 10) {
                    Text(status)
                        .font(.caption)
                        .foregroundStyle(GameTheme.parchment.opacity(0.78))
                        .lineLimit(3)
                    Spacer()
                    if vm.canRetryNarrator {
                        Button {
                            Task { await vm.retryNarratorWithFallback() }
                        } label: {
                            Label("Retry GPT", systemImage: "arrow.clockwise.circle.fill")
                                .font(.caption.bold())
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(GameTheme.ember)
                        .disabled(vm.isThinking)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(GameTheme.panel)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(GameTheme.brass.opacity(0.55), lineWidth: 1.2))
        .shadow(color: .black.opacity(0.28), radius: 18, x: 0, y: 8)
        .onAppear { inputFocused = true }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("ADVENTURE LOG")
                .font(.caption.weight(.black))
                .tracking(2.2)
                .foregroundStyle(GameTheme.brass)
            if let loc = vm.location {
                Text(loc.displayName)
                    .font(.system(.callout, design: .serif).weight(.semibold))
                    .foregroundStyle(GameTheme.parchmentLight)
                    .lineLimit(2)
            } else {
                Text("Awaiting coordinates")
                    .font(.system(.callout, design: .serif).weight(.semibold))
                    .foregroundStyle(GameTheme.parchmentLight.opacity(0.7))
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GameTheme.ink)
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 8) {
            ZStack(alignment: .topLeading) {
                if input.isEmpty {
                    Text(vm.isThinking ? "Waiting for narrator…" : "What do you do?")
                        .foregroundStyle(GameTheme.ink.opacity(0.38))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 10)
                }
                TextEditor(text: $input)
                    .font(.system(.body, design: .serif))
                    .frame(minHeight: 42, maxHeight: 96)
                    .scrollContentBackground(.hidden)
                    .focused($inputFocused)
            }
            .background(GameTheme.parchmentLight.opacity(0.92))
            .overlay(RoundedRectangle(cornerRadius: 10)
                .strokeBorder(GameTheme.brass.opacity(0.55)))

            Button { Task { await submit() } } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(GameTheme.brass)
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.return)
            .disabled(vm.isThinking || input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(12)
        .background(GameTheme.panel)
    }

    private func submit() async {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        input = ""
        await vm.sendInput(trimmed)
    }
}

private struct TurnView: View {
    let turn: ChatTurn

    var body: some View {
        switch turn.role {
        case .user:
            HStack(alignment: .top, spacing: 9) {
                Image(systemName: "person.fill")
                    .foregroundStyle(GameTheme.ember)
                    .frame(width: 16)
                Text(turn.text)
                    .font(.system(.body, design: .serif).weight(.semibold))
                    .foregroundStyle(GameTheme.ink)
                    .textSelection(.enabled)
            }
            .padding(11)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(GameTheme.brass.opacity(0.18))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(GameTheme.brass.opacity(0.35)))
            )
        case .narrator:
            VStack(alignment: .leading, spacing: 9) {
                ForEach(turn.text.components(separatedBy: "\n\n"), id: \.self) { para in
                    Text(para)
                        .font(.system(.body, design: .serif))
                        .foregroundStyle(GameTheme.ink.opacity(0.92))
                        .lineSpacing(3)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        case .system:
            Text(turn.text)
                .font(.caption)
                .foregroundStyle(GameTheme.ink.opacity(0.58))
        }
    }
}

private struct SuggestionsBar: View {
    let suggestions: [String]
    let onPick: (String) -> Void

    var body: some View {
        VStack(spacing: 7) {
            ForEach(Array(suggestions.enumerated()), id: \.offset) { idx, item in
                Button { onPick(item) } label: {
                    HStack(spacing: 8) {
                        Text("\(idx + 1)")
                            .font(.caption.bold())
                            .foregroundStyle(GameTheme.parchmentLight)
                            .frame(width: 22, height: 22)
                            .background(Circle().fill(GameTheme.ember))
                        Text(item)
                            .font(.caption.weight(.semibold))
                            .lineLimit(2)
                            .foregroundStyle(GameTheme.ink)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                }
                .buttonStyle(.plain)
                .background(RoundedRectangle(cornerRadius: 10).fill(GameTheme.parchment.opacity(0.75)))
                .keyboardShortcut(KeyEquivalent(Character("\(idx + 1)")), modifiers: [.command])
            }
        }
        .padding(10)
        .background(GameTheme.ink.opacity(0.92))
    }
}

// MARK: - Map panel

private struct MapPanel: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var camera: MapCameraPosition = .automatic

    var body: some View {
        ZStack(alignment: .topLeading) {
            if let coord = vm.location?.coordinate {
                Map(position: $camera) {
                    Annotation(vm.location?.displayName ?? "You", coordinate: coord) {
                        ZStack {
                            Circle().fill(GameTheme.ember).frame(width: 20, height: 20)
                            Circle().stroke(GameTheme.parchmentLight, lineWidth: 3).frame(width: 20, height: 20)
                        }
                        .shadow(radius: 3)
                    }
                }
                .mapStyle(.standard(elevation: .realistic))
                .onChange(of: vm.location?.coordinate?.latitude) { _, _ in recenter(coord) }
                .onAppear { recenter(coord) }
            } else {
                ZStack {
                    GameTheme.ink
                    VStack(spacing: 8) {
                        Image(systemName: "map")
                            .font(.system(size: 32))
                            .foregroundStyle(GameTheme.brass)
                        Text("No location yet")
                            .foregroundStyle(GameTheme.parchment.opacity(0.75))
                    }
                }
            }

            if let loc = vm.location {
                LocationBadge(location: loc).padding(10)
            }
        }
    }

    private func recenter(_ coord: CLLocationCoordinate2D) {
        withAnimation(.easeInOut(duration: 0.8)) {
            camera = .region(MKCoordinateRegion(
                center: coord,
                latitudinalMeters: 1500,
                longitudinalMeters: 1500
            ))
        }
    }
}

private struct LocationBadge: View {
    let location: GameLocation

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(location.displayName)
                .font(.caption.bold())
                .lineLimit(2)
            if let time = location.gameTime {
                Label(time, systemImage: "clock")
                    .font(.caption2)
            }
            if let weather = location.weather {
                Label(weather, systemImage: "cloud.sun")
                    .font(.caption2)
                    .lineLimit(1)
            }
        }
        .foregroundStyle(GameTheme.parchmentLight)
        .padding(9)
        .background(GameTheme.ink.opacity(0.82), in: RoundedRectangle(cornerRadius: 10))
    }
}

// MARK: - Scene panel

private struct ScenePanel: View {
    @EnvironmentObject var vm: GameViewModel

    var body: some View {
        ZStack {
            GameTheme.night
            imageStage
            VStack(alignment: .leading) {
                topControls
                    .frame(maxWidth: .infinity, alignment: .leading)
                Spacer()
                bottomControls
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(18)
        }
    }

    private var imageStage: some View {
        ZStack {
            if let img = vm.sceneImage {
                Image(nsImage: img)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .clipped()
                    .transition(.opacity)
            } else {
                VStack(spacing: 16) {
                    Image(systemName: "photo.artframe")
                        .font(.system(size: 56))
                        .foregroundStyle(GameTheme.brass)
                    Text(vm.hasOpenAIKey
                         ? "Scene art will appear here"
                         : "Set OPENAI_API_KEY to enable scene art")
                        .font(.system(.title3, design: .serif).weight(.semibold))
                        .foregroundStyle(GameTheme.parchmentLight)
                    Text("Choose a visual style above; generated images are cached with the save.")
                        .font(.callout)
                        .foregroundStyle(GameTheme.parchment.opacity(0.75))
                }
            }

            LinearGradient(
                colors: [.black.opacity(0.58), .clear, .black.opacity(0.62)],
                startPoint: .top,
                endPoint: .bottom
            )
            .allowsHitTesting(false)

            if vm.imageLoading {
                Label("Generating scene…", systemImage: "wand.and.stars")
                    .font(.headline)
                    .padding(14)
                    .background(.ultraThinMaterial, in: Capsule())
                    .foregroundStyle(GameTheme.parchmentLight)
            }
        }
        .animation(.easeInOut(duration: 0.35), value: vm.sceneImage)
        .help(vm.lastImagePrompt ?? "")
    }

    private var topControls: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text("SCENE RENDER")
                    .font(.caption.weight(.black))
                    .tracking(2)
                    .foregroundStyle(GameTheme.brass)
                Text(currentImageSubtitle)
                    .font(.caption)
                    .foregroundStyle(GameTheme.parchment.opacity(0.85))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .layoutPriority(1)
            Spacer(minLength: 8)
            Menu {
                ForEach(vm.imageStyles) { style in
                    Button {
                        Task { await vm.selectImageStyle(style.id) }
                    } label: {
                        if style.id == vm.selectedStyleID {
                            Label(style.name, systemImage: "checkmark")
                        } else {
                            Text(style.name)
                        }
                    }
                }
            } label: {
                HStack(spacing: 8) {
                    Text("Style")
                        .font(.caption.weight(.black))
                        .tracking(1.3)
                        .foregroundStyle(GameTheme.brass)
                    Text(selectedStyleName)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(GameTheme.parchmentLight)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Image(systemName: "chevron.down")
                        .font(.caption2.bold())
                        .foregroundStyle(GameTheme.brass)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(GameTheme.night.opacity(0.85), in: Capsule())
                .overlay(Capsule().stroke(GameTheme.brass.opacity(0.45)))
            }
            .menuStyle(.borderlessButton)
            .frame(maxWidth: 220, alignment: .trailing)
            .layoutPriority(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(GameTheme.ink.opacity(0.88), in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(GameTheme.brass.opacity(0.35)))
    }

    private var bottomControls: some View {
        HStack(spacing: 12) {
            Button { vm.showPreviousImage() } label: {
                Image(systemName: "chevron.left.circle.fill")
                    .font(.title2)
            }
            .buttonStyle(.plain)
            .disabled(vm.currentImageIndex <= 0)

            Text(historyLabel)
                .font(.caption.weight(.semibold))
                .foregroundStyle(GameTheme.parchmentLight)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(GameTheme.ink.opacity(0.75), in: Capsule())

            Button { vm.showNextImage() } label: {
                Image(systemName: "chevron.right.circle.fill")
                    .font(.title2)
            }
            .buttonStyle(.plain)
            .disabled(vm.currentImageIndex >= vm.imageHistory.count - 1)

            Button("Latest") { vm.showLatestImage() }
                .buttonStyle(.bordered)
                .tint(GameTheme.brass)
                .disabled(vm.imageHistory.isEmpty || vm.currentImageIndex == vm.imageHistory.count - 1)
                .fixedSize()

            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .foregroundStyle(GameTheme.brass)
    }

    private var historyLabel: String {
        guard !vm.imageHistory.isEmpty, vm.currentImageIndex >= 0 else { return "No renders" }
        return "\(vm.currentImageIndex + 1) / \(vm.imageHistory.count)"
    }

    private var currentImageSubtitle: String {
        guard vm.imageHistory.indices.contains(vm.currentImageIndex) else {
            return "Photorealistic by default"
        }
        let entry = vm.imageHistory[vm.currentImageIndex]
        return "\(entry.styleName) · turn \(entry.turnIndex)"
    }

    private var selectedStyleName: String {
        vm.imageStyles.first(where: { $0.id == vm.selectedStyleID })?.name ?? "Photorealistic"
    }
}
