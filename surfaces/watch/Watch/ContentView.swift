import SwiftUI

/// Root screen: paired -> Henry chat (the landing screen, owner decree
/// mirrored from the Wear OS build - "chat first, board one tap away");
/// unpaired -> the pairing flow. See PairingView.swift/ChatView.swift for
/// the actual screens; project.yml's own README documents why this target
/// carries real network/crypto code while iOSHost carries none.
struct ContentView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        NavigationStack {
            if app.device == nil {
                PairingView()
            } else {
                ChatView()
            }
        }
    }
}
