import SwiftUI

struct StartMenuView: View {
    @EnvironmentObject var vm: GameViewModel

    var body: some View {
        HStack(spacing: 24) {
            heroPanel
                .frame(width: 460)
            storiesPanel
        }
        .padding(28)
    }

    private var heroPanel: some View {
        ZStack(alignment: .leading) {
            RoundedRectangle(cornerRadius: 26, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [GameTheme.ink, Color(red: 0.21, green: 0.12, blue: 0.07)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 26, style: .continuous)
                        .stroke(GameTheme.brass.opacity(0.7), lineWidth: 2)
                )
                .shadow(color: .black.opacity(0.45), radius: 28, x: 0, y: 18)

            VStack(alignment: .leading, spacing: 18) {
                Text("REAL WORLD")
                    .font(.system(size: 55, weight: .heavy, design: .serif))
                    .foregroundStyle(GameTheme.parchmentLight)
                    .kerning(3)
                    .shadow(color: .black, radius: 0, x: 2, y: 2)
                Text("Text Adventure")
                    .font(.system(size: 34, weight: .regular, design: .serif))
                    .foregroundStyle(GameTheme.brass)
                Text("A living atlas, narrated turn by turn.")
                    .font(.system(.title3, design: .serif).italic())
                    .foregroundStyle(GameTheme.parchment.opacity(0.9))
                    .padding(.top, 8)

                Spacer()

                VStack(alignment: .leading, spacing: 10) {
                    Label("Claude Opus 4.7 narration", systemImage: "sparkles")
                    Label("MapKit live location tracking", systemImage: "map")
                    Label("Cached gpt-image-2 scene art", systemImage: "photo.on.rectangle")
                }
                .font(.callout.weight(.medium))
                .foregroundStyle(GameTheme.parchmentLight.opacity(0.92))

                Text("Explore from any real address. Keep your story, map, and illustrated scenes together like a playable travel journal.")
                    .font(.callout)
                    .lineSpacing(3)
                    .foregroundStyle(GameTheme.parchment.opacity(0.82))
                    .frame(maxWidth: 360, alignment: .leading)

                if !vm.hasOpenAIKey {
                    Label("OPENAI_API_KEY not set — scene images disabled.",
                          systemImage: "exclamationmark.circle")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }
            .padding(38)
        }
    }

    private var storiesPanel: some View {
        AdventurePanel {
            VStack(alignment: .leading, spacing: 20) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Choose your run")
                            .font(.system(size: 30, weight: .bold, design: .serif))
                            .foregroundStyle(GameTheme.ink)
                        Text("Saved expeditions")
                            .font(.caption.weight(.semibold))
                            .textCase(.uppercase)
                            .tracking(1.8)
                            .foregroundStyle(GameTheme.ember)
                    }
                    Spacer()
                    Button {
                        Task { await vm.detectLocation() }
                    } label: {
                        Label("New Game", systemImage: "plus.circle.fill")
                            .font(.headline)
                            .padding(.horizontal, 8)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(GameTheme.ember)
                    .keyboardShortcut("n")
                }

                if vm.saves.isEmpty {
                    emptyState
                } else {
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            ForEach(vm.saves) { entry in
                                SaveCard(entry: entry) {
                                    Task { await vm.loadGame(entry) }
                                }
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }

                if let msg = vm.statusMessage {
                    Text(msg)
                        .font(.caption)
                        .foregroundStyle(GameTheme.ink.opacity(0.65))
                }
            }
            .padding(28)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "map.fill")
                .font(.system(size: 52))
                .foregroundStyle(GameTheme.brass)
            Text("No saves yet")
                .font(.system(.title2, design: .serif).bold())
                .foregroundStyle(GameTheme.ink)
            Text("Start anywhere in the real world and the first page of your expedition will appear here.")
                .multilineTextAlignment(.center)
                .foregroundStyle(GameTheme.ink.opacity(0.65))
                .frame(maxWidth: 360)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct SaveCard: View {
    let entry: SaveEntry
    let onLoad: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            preview

            VStack(alignment: .leading, spacing: 3) {
                Text(entry.name)
                    .font(.system(.body, design: .monospaced).weight(.semibold))
                    .foregroundStyle(GameTheme.ink)
                Text(formattedDate(entry.updated_at))
                    .font(.caption)
                    .foregroundStyle(GameTheme.ink.opacity(0.58))
            }
            Spacer()
            Button("Continue") { onLoad() }
                .buttonStyle(.bordered)
                .tint(GameTheme.ember)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(GameTheme.parchment.opacity(0.55))
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .stroke(GameTheme.ink.opacity(0.12))
                )
        )
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { onLoad() }
    }

    private var preview: some View {
        ZStack {
            if let path = entry.previewImagePath,
               let image = NSImage(contentsOfFile: path) {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .frame(width: 92, height: 58)
                    .clipped()
            } else {
                RoundedRectangle(cornerRadius: 10)
                    .fill(GameTheme.ink)
                Image(systemName: "location.north.line.fill")
                    .foregroundStyle(GameTheme.brass)
            }
            LinearGradient(
                colors: [.black.opacity(0.25), .clear],
                startPoint: .bottom,
                endPoint: .top
            )
            .allowsHitTesting(false)
        }
        .frame(width: 92, height: 58)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(GameTheme.ink.opacity(0.18)))
        .help(entry.previewStyleName ?? "Latest scene render")
    }

    private func formattedDate(_ raw: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = formatter.date(from: raw) ?? ISO8601DateFormatter().date(from: raw) {
            let f = DateFormatter()
            f.dateStyle = .medium
            f.timeStyle = .short
            return f.string(from: d)
        }
        return String(raw.prefix(19))
    }
}
