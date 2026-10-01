import SwiftUI

enum DR {
    static let navy = Color(red: 7/255, green: 27/255, blue: 63/255)
    static let blue = Color(red: 31/255, green: 123/255, blue: 242/255)
    static let cyan = Color(red: 40/255, green: 215/255, blue: 235/255)
    static let background = Color(uiColor: .systemGroupedBackground)
}

@main
struct DropRateApp: App {
    @State private var signedIn = false
    @State private var restoring = true
    var body: some Scene {
        WindowGroup {
            Group {
                if restoring { ProgressView("Opening Drop Rate…") }
                else if signedIn { MainView(onSignOut: { signedIn = false }) }
                else { SignInView(onSignIn: { signedIn = true }) }
            }.tint(DR.blue).task {
                signedIn = await API.shared.hasSession(); restoring = false
            }
        }
    }
}

struct Wordmark: View {
    var body: some View {
        Image("SellerHub").resizable().scaledToFit().frame(width: 200, height: 66)
            .padding(.horizontal, 16).background(DR.navy, in: RoundedRectangle(cornerRadius: 14))
            .accessibilityLabel("Drop Rate Seller Hub")
    }
}

struct SignInView: View {
    let onSignIn: () -> Void
    @State private var identifier = ""
    @State private var password = ""
    @State private var busy = false
    @State private var error: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Wordmark().padding(.top, 60)
                Image(systemName: "rectangle.stack.fill").font(.system(size: 64)).foregroundStyle(DR.blue).padding(.top, 48)
                Text("Your collection.\nYour next move.").font(.system(size: 38, weight: .bold, design: .rounded))
                Text("Scan, track and manage your cards with Drop Rate.").foregroundStyle(.secondary)
                VStack(spacing: 14) {
                    TextField("Email or username", text: $identifier).textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField("Password", text: $password).textContentType(.password)
                }.textFieldStyle(.roundedBorder)
                if let error { Text(error).foregroundStyle(.red).font(.callout) }
                Button {
                    busy = true; error = nil
                    Task {
                        do { try await API.shared.login(identifier: identifier, password: password); password = ""; onSignIn() }
                        catch { self.error = error.localizedDescription }
                        busy = false
                    }
                } label: { HStack { Spacer(); if busy { ProgressView().tint(.white) } else { Text("Sign in").bold() }; Spacer() }.padding(8) }
                    .buttonStyle(.borderedProminent).disabled(busy || identifier.isEmpty || password.isEmpty)
                Link("Create an account or recover access", destination: API.base.appendingPathComponent("owner/join"))
                    .font(.callout)
                Text("Use your existing Seller Hub account.").font(.caption).foregroundStyle(.secondary)
            }.padding(28)
        }.background(DR.background)
    }
}

struct MainView: View {
    let onSignOut: () -> Void
    @State private var tab = 0
    @State private var scanner = false
    @State private var portfolioRevision = 0
    @State private var pendingSave = false
    @State private var recoveryError: String?
    var body: some View {
        TabView(selection: $tab) {
            PortfolioView().id(portfolioRevision).tabItem { Label("Portfolio", systemImage: "square.grid.2x2") }.tag(0)
            SearchView().tabItem { Label("Search", systemImage: "magnifyingglass") }.tag(1)
            Color.clear.tabItem { Label("Scan", systemImage: "camera.viewfinder") }.tag(2)
            AccountView(onSignOut: onSignOut).tabItem { Label("Account", systemImage: "person.crop.circle") }.tag(3)
        }
        .onChange(of: tab) { old, new in
            if new == 2 {
                tab = old
                Task {
                    if await API.shared.hasPendingIntake() { pendingSave = true }
                    else { scanner = true }
                }
            }
        }
        .fullScreenCover(isPresented: $scanner, onDismiss: {
            portfolioRevision += 1
            Task { pendingSave = await API.shared.hasPendingIntake() }
        }) { ScannerView() }
        .task { pendingSave = await API.shared.hasPendingIntake() }
        .alert("Finish your card save", isPresented: $pendingSave) {
            Button("Retry save") {
                Task {
                    do { try await API.shared.resumeIntake(); portfolioRevision += 1 }
                    catch { recoveryError = error.localizedDescription }
                }
            }
            Button("Later", role: .cancel) {}
        } message: { Text("An earlier save was interrupted. Retry the same request to check or finish it without creating a duplicate.") }
        .alert("Save needs attention", isPresented: Binding(get: { recoveryError != nil }, set: { if !$0 { recoveryError = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(recoveryError ?? "") }
    }
}

struct ErrorNotice: View {
    let message: String
    let retry: () -> Void
    var body: some View {
        VStack(spacing: 12) { Text(message).font(.callout).multilineTextAlignment(.center); Button("Try again", action: retry).buttonStyle(.bordered) }.padding()
    }
}

struct CardImage: View {
    let url: String?
    var body: some View {
        AsyncImage(url: url.flatMap(URL.init(string:))) { phase in
            if let image = phase.image { image.resizable().scaledToFit() }
            else { VStack(spacing: 8) { Image(systemName: "rectangle.portrait").font(.largeTitle); Text("Image unavailable").font(.caption2) }.foregroundStyle(.secondary).frame(maxWidth: .infinity, maxHeight: .infinity) }
        }.frame(height: 180).frame(maxWidth: .infinity).padding(12).background(DR.background, in: RoundedRectangle(cornerRadius: 14))
    }
}

struct PortfolioView: View {
    @State private var overview: Overview?
    @State private var items: [InventoryItem] = []
    @State private var total = 0
    @State private var query = ""
    @State private var status = ""
    @State private var error: String?
    @State private var busy = false
    @State private var requestID = UUID()
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Wordmark()
                    VStack(alignment: .leading, spacing: 20) {
                        Text("YOUR PORTFOLIO").font(.caption.weight(.bold)).tracking(2).foregroundStyle(.white.opacity(0.7))
                        Text(Money.display(overview?.summary.activeMarketValueMinor)).font(.system(size: 38, weight: .bold, design: .rounded))
                        HStack {
                            Label("Market value", systemImage: "chart.line.uptrend.xyaxis")
                            Spacer()
                            VStack(alignment: .trailing) { Text("Store value").foregroundStyle(.white.opacity(0.7)); Text(Money.display(overview?.summary.activeStoreValueMinor)).bold() }
                        }.font(.subheadline)
                        Text("Active stock · store value includes suggested prices where no store price is set.").font(.caption2).foregroundStyle(.white.opacity(0.75))
                    }.padding(24).foregroundStyle(.white).background(LinearGradient(colors: [DR.navy, DR.blue.opacity(0.85)], startPoint: .topLeading, endPoint: .bottomTrailing), in: RoundedRectangle(cornerRadius: 24))
                    HStack { Text("Your collection").font(.title2.bold()); Spacer(); Text("\(total) items").foregroundStyle(.secondary) }
                    Picker("Inventory status", selection: $status) {
                        Text("All items").tag(""); Text("Draft").tag("DRAFT"); Text("Available").tag("APPROVED"); Text("Reserved").tag("RESERVED"); Text("Sold").tag("SOLD")
                    }.pickerStyle(.menu)
                    if let error { ErrorNotice(message: error) { Task { await load(reset: true) } } }
                    if items.isEmpty && !busy && error == nil {
                        ContentUnavailableView("Your collection starts here", systemImage: "rectangle.stack.badge.plus", description: Text("Tap Scan to add your first card, or change your search."))
                    }
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
                        ForEach(items) { item in
                            NavigationLink { InventoryDetail(item: item) } label: {
                                VStack(alignment: .leading, spacing: 8) {
                                    CardImage(url: item.imageUrl)
                                    Text(item.game.uppercased()).font(.system(size: 9, weight: .bold)).foregroundStyle(DR.blue)
                                    Text(item.name).font(.subheadline.bold()).lineLimit(2).foregroundStyle(.primary)
                                    Text([item.cardNumber, item.language, item.gradingCompany, item.grade].compactMap { $0 }.joined(separator: " · ")).font(.caption2).foregroundStyle(.secondary)
                                    Text(Money.display(item.marketValueMinor)).font(.headline).foregroundStyle(.primary)
                                    Text("Store \(Money.display(item.storeValue))").font(.caption).foregroundStyle(.secondary)
                                }.frame(maxWidth: .infinity, alignment: .leading)
                            }.buttonStyle(.plain)
                        }
                    }
                    if busy { ProgressView().frame(maxWidth: .infinity) }
                    if items.count < total && !busy { Button("Load more") { Task { await load(reset: false) } }.frame(maxWidth: .infinity) }
                }.padding(20)
            }.background(DR.background).navigationTitle("Portfolio").navigationBarTitleDisplayMode(.inline)
                .searchable(text: $query, prompt: "Search your collection")
                .task(id: query + "|" + status) {
                    do { try await Task.sleep(for: .milliseconds(300)); await load(reset: true) } catch {}
                }.refreshable { await load(reset: true) }
        }
    }
    private func load(reset: Bool) async {
        let id = UUID(); requestID = id; busy = true; error = nil
        if reset { items = []; total = 0 }
        do {
            let summary: Overview = try await API.shared.get("/api/v1/owner/overview")
            let page: InventoryPage = try await API.shared.get("/api/v1/owner/inventory", query: ["search": query, "status": status, "limit": "40", "offset": "\(items.count)"])
            guard requestID == id, !Task.isCancelled else { return }
            overview = summary; total = page.total
            if reset { items = page.items } else { items += page.items.filter { new in !items.contains { $0.id == new.id } } }
        } catch { if requestID == id && !Task.isCancelled { self.error = error.localizedDescription } }
        if requestID == id { busy = false }
    }
}

struct InventoryDetail: View {
    let item: InventoryItem
    var body: some View {
        List {
            CardImage(url: item.imageUrl)
            Section(item.name) {
                LabeledContent("TCG", value: item.game)
                LabeledContent("Set", value: item.setName ?? "Unknown")
                LabeledContent("Number", value: item.cardNumber ?? "Unknown")
                LabeledContent("Language", value: item.language ?? "Unconfirmed")
                LabeledContent("Variant", value: item.variant ?? "Unconfirmed")
                LabeledContent("Condition / grade", value: [item.condition, item.gradingCompany, item.grade].compactMap { $0 }.joined(separator: " "))
                LabeledContent("Status", value: item.status.capitalized)
            }
            Section("Valuation") {
                LabeledContent("Market", value: Money.display(item.marketValueMinor))
                LabeledContent("Store", value: Money.display(item.storeValue))
                Text("Updated: \(item.pricingUpdatedAt ?? "No valuation yet")").font(.caption).foregroundStyle(.secondary)
            }
            Text(item.inventoryCode).font(.caption.monospaced()).textSelection(.enabled)
        }.navigationTitle("Item details")
    }
}
