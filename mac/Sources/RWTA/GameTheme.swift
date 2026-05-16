import SwiftUI

struct GameTheme {
    static let ink = Color(red: 0.10, green: 0.08, blue: 0.06)
    static let parchment = Color(red: 0.92, green: 0.84, blue: 0.68)
    static let parchmentLight = Color(red: 0.98, green: 0.91, blue: 0.76)
    static let brass = Color(red: 0.86, green: 0.58, blue: 0.22)
    static let ember = Color(red: 0.74, green: 0.25, blue: 0.13)
    static let forest = Color(red: 0.10, green: 0.19, blue: 0.14)
    static let night = Color(red: 0.04, green: 0.05, blue: 0.06)
    static let panel = Color(red: 0.13, green: 0.10, blue: 0.08)
}

struct AdventureBackdrop: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [GameTheme.night, GameTheme.forest, Color(red: 0.22, green: 0.13, blue: 0.08)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            RadialGradient(
                colors: [GameTheme.brass.opacity(0.30), .clear],
                center: .topLeading,
                startRadius: 10,
                endRadius: 850
            )
            Canvas { context, size in
                for x in stride(from: 0.0, through: size.width, by: 18) {
                    for y in stride(from: 0.0, through: size.height, by: 18) {
                        let rect = CGRect(x: x, y: y, width: 1, height: 1)
                        context.fill(Path(ellipseIn: rect), with: .color(.white.opacity(0.035)))
                    }
                }
            }
        }
        .ignoresSafeArea()
    }
}

struct AdventurePanel<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(GameTheme.parchmentLight.opacity(0.94))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(GameTheme.brass.opacity(0.65), lineWidth: 1.5)
                    )
                    .shadow(color: .black.opacity(0.35), radius: 22, x: 0, y: 12)
            )
    }
}
