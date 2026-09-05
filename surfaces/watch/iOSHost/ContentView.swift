import SwiftUI

// This screen is the whole app. The companion exists only so App Store
// Connect has an iOS container to hang the watch app off of - see
// project.yml's comment on HelmDeckWatchCompanion.
struct ContentView: View {
    var body: some View {
        VStack(spacing: 12) {
            Text("HelmDeck")
                .font(.title)
            Text("This app only carries the HelmDeck Watch app to your wrist. Open the Watch app on your Apple Watch.")
                .font(.footnote)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 32)
        }
    }
}
