import SwiftUI

@main
struct SellerHubApp: App {
    var body: some Scene {
        WindowGroup { SellerHubScreen() }
    }
}

@MainActor
final class HubState: ObservableObject {
    @Published var loading = true
    @Published var error: String?
    @Published var notice: String?
    var retry: (() -> Void)?
}

struct SellerHubScreen: View {
    @StateObject private var state = HubState()

    var body: some View {
        ZStack {
            Color(red: 0.98, green: 0.97, blue: 0.94).ignoresSafeArea()
            HubWebView(state: state)
                .ignoresSafeArea(.container, edges: .bottom)
            if let error = state.error {
                VStack(spacing: 20) {
                    Image(systemName: "wifi.exclamationmark").font(.system(size: 38))
                    Text("Let’s get you back in").font(.title2.bold())
                    Text(error).multilineTextAlignment(.center)
                    Button("Try again") { state.retry?() }.buttonStyle(.borderedProminent)
                }
                .padding(32)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(red: 0.98, green: 0.97, blue: 0.94))
            } else if state.loading {
                VStack(spacing: 16) {
                    ProgressView()
                    Text("Opening Drop Rate…").font(.headline)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(red: 0.98, green: 0.97, blue: 0.94))
            }
        }
        .tint(Color(red: 0.06, green: 0.35, blue: 0.45))
        .alert("Drop Rate", isPresented: Binding(
            get: { state.notice != nil }, set: { if !$0 { state.notice = nil } }
        )) { Button("OK") { state.notice = nil } } message: { Text(state.notice ?? "") }
    }
}
