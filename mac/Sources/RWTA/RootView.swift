import SwiftUI

struct RootView: View {
    @EnvironmentObject var vm: GameViewModel

    var body: some View {
        ZStack {
            AdventureBackdrop()
            switch vm.phase {
            case .launching:
                LaunchingView()
            case .menu:
                StartMenuView()
            case .configuringNewGame:
                NewGameView()
            case .playing:
                PlayView()
            case .error(let message):
                ErrorView(message: message)
            }
        }
        .background(GameTheme.night)
    }
}

private struct LaunchingView: View {
    var body: some View {
        VStack(spacing: 16) {
            ProgressView()
            Text("Booting backend…")
                .foregroundStyle(.secondary)
        }
    }
}

private struct ErrorView: View {
    let message: String
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Backend error", systemImage: "exclamationmark.triangle.fill")
                .font(.title2)
                .foregroundStyle(.red)
            Text(message)
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
            Text("""
            Make sure ANTHROPIC_API_KEY is exported in your shell, and that uv is installed (or that the project has a `.venv/bin/python`). \
            Set RWTA_PROJECT_DIR if the rwta repo lives somewhere unusual.
            """)
                .foregroundStyle(.secondary)
        }
        .padding(40)
        .frame(maxWidth: 700)
    }
}
