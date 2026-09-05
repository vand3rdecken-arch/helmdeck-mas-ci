import SwiftUI

@main
struct HelmDeckWatchApp: App {
    // App-root scope, per AppState.swift's own doc: exactly one owner for
    // pairing state and the voice toggle, shared by every screen.
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
        }
    }
}
