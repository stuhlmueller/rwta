import SwiftUI

struct NewGameView: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var address: String = ""
    @State private var hasInitialized = false

    var body: some View {
        AdventurePanel {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Set your starting point")
                            .font(.system(size: 32, weight: .bold, design: .serif))
                            .foregroundStyle(GameTheme.ink)
                        Text("Type any real address, landmark, city, or place name.")
                            .foregroundStyle(GameTheme.ink.opacity(0.65))
                    }
                    Spacer()
                    Image(systemName: "mappin.and.ellipse")
                        .font(.system(size: 38))
                        .foregroundStyle(GameTheme.ember)
                }

                if let detected = vm.detectedLocation {
                    Label("Detected nearby: \(detected.displayName)", systemImage: "location.circle")
                        .font(.callout)
                        .foregroundStyle(GameTheme.ink.opacity(0.7))
                } else {
                    Label("Detecting location…", systemImage: "location.circle")
                        .foregroundStyle(GameTheme.ink.opacity(0.7))
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("Start at")
                        .font(.headline)
                        .foregroundStyle(GameTheme.ink)
                    TextField("e.g. Miami Beach, FL or Golden Gate Park, San Francisco", text: $address)
                        .textFieldStyle(.plain)
                        .font(.system(.title3, design: .serif))
                        .foregroundStyle(GameTheme.ink)
                        .padding(14)
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(Color.white.opacity(0.55))
                                .overlay(RoundedRectangle(cornerRadius: 12).stroke(GameTheme.brass.opacity(0.55)))
                        )
                    Text("If you replace the detected location with a new city like “Miami,” the backend geocodes that text and starts there.")
                        .font(.caption)
                        .foregroundStyle(GameTheme.ink.opacity(0.6))
                }

                HStack {
                    Button("Back") {
                        Task { await vm.backToMenu() }
                    }
                    .buttonStyle(.bordered)
                    .tint(GameTheme.ink)
                    Spacer()
                    Button {
                        Task { await vm.startNewGame(address: address) }
                    } label: {
                        Label("Begin", systemImage: "play.fill")
                            .font(.headline)
                            .padding(.horizontal, 14)
                    }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .tint(GameTheme.ember)
                    .disabled(vm.detectedLocation == nil)
                }
            }
            .padding(32)
        }
        .frame(maxWidth: 720, maxHeight: 430)
        .onChange(of: vm.detectedLocation) { _, new in
            if !hasInitialized, let new {
                address = new.displayName
                hasInitialized = true
            }
        }
        .task {
            if vm.detectedLocation != nil, !hasInitialized {
                address = vm.detectedLocation?.displayName ?? ""
                hasInitialized = true
            }
        }
    }
}
