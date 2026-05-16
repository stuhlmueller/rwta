import SwiftUI
import AppKit

@main
struct RWTAApp: App {
    @StateObject private var vm = GameViewModel()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup("Real World Text Adventure") {
            RootView()
                .environmentObject(vm)
                .frame(minWidth: 1100, minHeight: 720)
                .task {
                    await vm.boot()
                }
                .onDisappear {
                    vm.shutdown()
                }
        }
        .windowResizability(.contentSize)
        .commands {
            CommandGroup(after: .newItem) {
                Button("Save Game") {
                    Task { await vm.saveGame() }
                }
                .keyboardShortcut("s")
                .disabled(!vm.isPlaying)
                Button("Look Around") {
                    Task { await vm.look() }
                }
                .keyboardShortcut("l")
                .disabled(!vm.isPlaying)
                Button("Regenerate Last") {
                    Task { await vm.regenerate() }
                }
                .keyboardShortcut("r")
                .disabled(!vm.isPlaying)
                Divider()
                Button("Back to Menu") {
                    Task { await vm.backToMenu() }
                }
                .disabled(!vm.isPlaying)
            }
        }
    }
}

extension GameViewModel {
    var isPlaying: Bool {
        if case .playing = phase { return true }
        return false
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Force regular activation policy so the app shows in the Dock and
        // gets keyboard focus, even when launched via `swift run`.
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate(ignoringOtherApps: true)
        hideWindowTitles()
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        hideWindowTitles()
    }

    private func hideWindowTitles() {
        for window in NSApplication.shared.windows {
            window.titleVisibility = .hidden
            window.titlebarAppearsTransparent = true
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}
