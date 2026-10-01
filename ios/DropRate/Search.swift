import SwiftUI

struct SearchView: View {
    @State private var query = ""
    @State private var game = ""
    @State private var language = ""
    @State private var games: [Game] = []
    @State private var items: [CatalogueItem] = []
    @State private var more = false
    @State private var busy = false
    @State private var error: String?
    @State private var requestID = UUID()
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("Find your next favourite.").font(.title.bold())
                    Text("Explore by TCG, or search cards, numbers and sets.").foregroundStyle(.secondary)
                    HStack {
                        Picker("TCG", selection: $game) { Text("All TCGs").tag(""); ForEach(games) { Text($0.game).tag($0.game) } }
                        Picker("Language", selection: $language) { Text("All languages").tag(""); Text("English").tag("English"); Text("Japanese").tag("Japanese") }
                    }.pickerStyle(.menu)
                    if query.isEmpty && game.isEmpty {
                        Text("Browse TCGs").font(.title2.bold())
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                            ForEach(games) { item in
                                Button { game = item.game } label: {
                                    VStack(alignment: .leading, spacing: 22) {
                                        Image(systemName: "suit.diamond.fill").foregroundStyle(DR.cyan)
                                        Text(item.game).font(.headline).multilineTextAlignment(.leading)
                                        Text("\(item.cardCount.formatted()) cards").font(.caption).foregroundStyle(.white.opacity(0.7))
                                    }.frame(maxWidth: .infinity, minHeight: 130, alignment: .leading).padding(18)
                                        .foregroundStyle(.white).background(DR.navy, in: RoundedRectangle(cornerRadius: 18))
                                }
                            }
                        }
                    }
                    if let error { ErrorNotice(message: error) { Task { await load(reset: true) } } }
                    if !items.isEmpty {
                        Text(game.isEmpty ? "Search results" : game).font(.title2.bold())
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
                            ForEach(items) { item in NavigationLink { CatalogueDetail(item: item) } label: { CatalogueTile(item: item) }.buttonStyle(.plain) }
                        }
                    } else if !busy && error == nil && (!query.isEmpty || !game.isEmpty) {
                        ContentUnavailableView.search(text: query.isEmpty ? game : query)
                    }
                    if busy { ProgressView().frame(maxWidth: .infinity) }
                    if more && !busy { Button("Load more") { Task { await load(reset: false) } }.frame(maxWidth: .infinity) }
                }.padding(20)
            }.background(DR.background).navigationTitle("Search").searchable(text: $query, prompt: "Cards, numbers, sets…")
                .task {
                    do { let page: GamePage = try await API.shared.get("/api/v1/owner/mobile/games"); games = page.items }
                    catch { self.error = error.localizedDescription }
                }
                .task(id: query + "|" + game + "|" + language) {
                    do { try await Task.sleep(for: .milliseconds(350)); await load(reset: true) } catch {}
                }
        }
    }
    private func load(reset: Bool) async {
        let id = UUID(); requestID = id; busy = true; error = nil
        if reset { items = []; more = false }
        if query.trimmingCharacters(in: .whitespaces).count < 2 && game.isEmpty { busy = false; return }
        do {
            let page: CataloguePage = try await API.shared.get("/api/v1/owner/mobile/catalogue", query: ["q": query, "game": game, "language": language, "offset": "\(items.count)", "limit": "30"])
            guard requestID == id, !Task.isCancelled else { return }
            if reset { items = page.items } else { items += page.items.filter { new in !items.contains { $0.id == new.id } } }
            more = page.hasMore ?? false
        } catch { if requestID == id && !Task.isCancelled { self.error = error.localizedDescription } }
        if requestID == id { busy = false }
    }
}

struct CatalogueTile: View {
    let item: CatalogueItem
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            CardImage(url: item.imageUrl)
            Text(item.name).font(.subheadline.bold()).lineLimit(2)
            Text([item.setName, item.cardNumber, item.language].compactMap { $0 }.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary).lineLimit(3)
            Text(Money.display(item.marketValueMinor)).font(.headline)
        }.frame(maxWidth: .infinity, alignment: .leading).foregroundStyle(.primary)
    }
}
struct CatalogueDetail: View {
    let item: CatalogueItem
    var body: some View {
        List {
            CardImage(url: item.imageUrl)
            Section(item.name) {
                LabeledContent("TCG", value: item.game ?? "Unknown")
                LabeledContent("Set", value: item.setName ?? "Unknown")
                LabeledContent("Card number", value: item.cardNumber ?? "Unknown")
                LabeledContent("Language", value: item.language ?? "Unconfirmed")
                LabeledContent("Variant", value: item.variant ?? "Unconfirmed")
            }
            Section("Reference value") {
                LabeledContent("Market", value: Money.display(item.marketValueMinor))
                Text("Reference values are not a valuation of a particular slab or physical copy. Condition, language and exact printing matter.").font(.caption).foregroundStyle(.secondary)
            }
        }.navigationTitle("Card details")
    }
}

struct AccountView: View {
    let onSignOut: () -> Void
    @State private var profile: ProfileResponse?
    @State private var name = ""
    @State private var username = ""
    @State private var message: String?
    @State private var busy = false
    var body: some View {
        NavigationStack {
            Form {
                Section { Wordmark() }
                Section("Your profile") {
                    TextField("Display name", text: $name)
                    TextField("Username", text: $username).textInputAutocapitalization(.never).autocorrectionDisabled()
                    if let profile {
                        LabeledContent("Email", value: profile.email ?? "")
                        LabeledContent("Seller type", value: profile.profile.ownerType.capitalized)
                    }
                    Button("Save profile") {
                        busy = true
                        Task {
                            do { try await API.shared.mutate("/api/v1/owner/profile", method: "PATCH", body: ["display_name": name, "username": username]); message = "Profile saved." }
                            catch { message = error.localizedDescription }
                            busy = false
                        }
                    }.disabled(busy || profile == nil || name.isEmpty)
                }
                if let message { Section { Text(message).font(.callout) } }
                Section("Seller Hub") {
                    Link("Sales, payouts and account security", destination: API.base.appendingPathComponent("owner"))
                    Text("Opens the secure Seller Hub in your browser. You may need to sign in there.").font(.caption).foregroundStyle(.secondary)
                }
                Section {
                    Button("Sign out", role: .destructive) { Task { await API.shared.logout(); onSignOut() } }
                }
            }.navigationTitle("Account").task {
                do { let value: ProfileResponse = try await API.shared.get("/api/v1/owner/profile"); profile = value; name = value.profile.displayName; username = value.profile.username ?? "" }
                catch { message = error.localizedDescription }
            }
        }
    }
}
