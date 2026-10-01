import SwiftUI

struct ScanReview: View {
    let data: Data
    let mode: ScanMode
    @Environment(\.dismiss) private var dismiss
    @State private var result: RecognitionResult?
    @State private var reading: LabelReading?
    @State private var selectedID = ""
    @State private var selectedFromSearch = false
    @State private var language = ""
    @State private var condition = ""
    @State private var company = ""
    @State private var grade = ""
    @State private var certificate = ""
    @State private var query = ""
    @State private var matches: [CatalogueItem] = []
    @State private var busy = false
    @State private var saving = false
    @State private var saved = false
    @State private var message: String?
    @State private var saveKey = UUID().uuidString
    @State private var pendingPayload: [String: String]?
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if let image = UIImage(data: data) { Image(uiImage: image).resizable().scaledToFit().frame(maxWidth: .infinity, maxHeight: 220) }
                    Text(mode.rawValue).font(.headline)
                }
                if busy { Section { ProgressView("Finding the exact match…") } }
                if let message { Section { Text(message).font(.callout) } }
                if mode.isComic {
                    Section("Comic scan") {
                        Text("Text has been read from this cover. Comic catalogue matching and comic inventory intake are not yet supported by Seller Hub.")
                        if let reading { ForEach(Array(reading.lines.enumerated()), id: \.offset) { Text($0.element).textSelection(.enabled) } }
                    }
                } else {
                    Section("Check the exact printing") {
                        if let result {
                            ForEach(result.candidates.filter { !$0.hardRejected && $0.catalogueId != nil }) { candidate in
                                Button {
                                    selectedID = candidate.catalogueId ?? ""; selectedFromSearch = false
                                    language = candidate.candidateSnapshot.language ?? ""
                                } label: {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(candidate.candidateSnapshot.name ?? "Unknown card").bold()
                                            Text([candidate.candidateSnapshot.setName, candidate.candidateSnapshot.cardNumber, candidate.candidateSnapshot.variant, candidate.candidateSnapshot.language].compactMap { $0 }.joined(separator: " · ")).font(.caption)
                                            Text(Money.display(candidate.marketValueMinor)).font(.caption)
                                        }
                                        Spacer()
                                        if selectedID == candidate.catalogueId { Image(systemName: "checkmark.circle.fill") }
                                    }
                                }.disabled(pendingPayload != nil)
                            }
                            if result.candidates.isEmpty { Text("No exact match yet. Search below to identify the card.") }
                        } else if !busy { Button("Retry recognition") { Task { await recognize() } } }
                    }
                    Section("Find another card") {
                        TextField("Name, set or card number", text: $query)
                        ForEach(matches) { item in
                            Button {
                                selectedID = item.id; selectedFromSearch = true; language = item.language ?? ""
                            } label: {
                                HStack { VStack(alignment: .leading) { Text(item.name); Text([item.setName, item.cardNumber, item.variant, item.language].compactMap { $0 }.joined(separator: " · ")).font(.caption) }; Spacer(); if selectedID == item.id { Image(systemName: "checkmark.circle.fill") } }
                            }.disabled(pendingPayload != nil)
                        }
                    }
                    Section("Physical card") {
                        Picker("Language", selection: $language) { Text("Choose language").tag(""); Text("English").tag("English"); Text("Japanese").tag("Japanese") }
                        if !mode.isGraded {
                            Picker("Condition", selection: $condition) {
                                Text("Choose condition").tag("")
                                ForEach(["Near Mint", "Lightly Played", "Moderately Played", "Heavily Played", "Damaged"], id: \.self) { Text($0).tag($0) }
                            }
                        }
                    }.disabled(pendingPayload != nil)
                }
                if mode.isGraded {
                    Section("Slab label — review before saving") {
                        Picker("Grader", selection: $company) { Text("Choose grader").tag(""); ForEach(["PSA", "BGS", "ACE", "CGC"], id: \.self) { Text($0).tag($0) } }
                        TextField("Grade", text: $grade).keyboardType(.decimalPad)
                        TextField("Certificate number", text: $certificate).textInputAutocapitalization(.never).autocorrectionDisabled()
                        Text("Label text is read on your iPhone. Reading a number does not authenticate the slab or verify the certificate with the grader.").font(.caption).foregroundStyle(.secondary)
                        if let reading, reading.certificate == nil { Text("No unique certificate number found. Read the label and enter it above.").font(.caption) }
                    }.disabled(pendingPayload != nil)
                }
                if !mode.isComic {
                    Section {
                        Button(saved ? "Added to your portfolio" : pendingPayload != nil ? "Retry saving this card" : "Confirm & add to portfolio") { Task { await save() } }
                            .disabled(!canSave || saving || saved)
                        if saving { ProgressView("Saving…") }
                        Text("Creates one draft item for your account. Drop Rate verification is still required before sale.").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }.navigationTitle(saved ? "Card added" : "Review scan").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(saved ? "Scan next" : "Close") { dismiss() }.disabled(saving) } }
                .interactiveDismissDisabled(saving)
                .task { await recognize() }
                .task(id: query) {
                    guard query.trimmingCharacters(in: .whitespaces).count >= 2 else { matches = []; return }
                    do {
                        try await Task.sleep(for: .milliseconds(350))
                        let page: CataloguePage = try await API.shared.get("/api/v1/owner/catalogue-search", query: ["q": query, "limit": "12"])
                        try Task.checkCancellation(); matches = page.items
                    } catch { if !Task.isCancelled { message = error.localizedDescription } }
                }
        }
    }
    private var canSave: Bool {
        result != nil && !selectedID.isEmpty && ["English", "Japanese"].contains(language)
        && (mode.isGraded ? !company.isEmpty && !grade.isEmpty && !certificate.isEmpty : !condition.isEmpty)
    }
    private func recognize() async {
        busy = true; message = nil
        do {
            let label = try await TextReader.read(data); reading = label
            if mode.isGraded { company = label.company ?? ""; certificate = label.certificate ?? "" }
        } catch { message = "Could not read the label. You can enter its details manually." }
        if !mode.isComic {
            do {
                result = try await API.shared.post("/api/v1/recognition/resolve", body: ["image_data_url": "data:image/jpeg;base64," + data.base64EncodedString()])
            } catch { message = error.localizedDescription }
        }
        busy = false
    }
    private func save() async {
        guard let result, canSave, !saving else { return }
        saving = true; message = nil
        defer { saving = false }
        do {
            if pendingPayload == nil {
                let outcome = selectedFromSearch ? "CORRECTED_BY_SEARCH" : "CORRECTED_TO_CANDIDATE"
                try await API.shared.mutate("/api/v1/recognition/runs/\(result.run.id)/feedback", body: ["outcome": outcome, "selected_catalogue_id": selectedID, "notes": "Confirmed in iPhone app; slab label is unverified OCR."])
                var payload = ["recognition_run_id": result.run.id, "selected_catalogue_id": selectedID, "language": language]
                if mode.isGraded { payload["grading_company"] = company; payload["grade"] = grade; payload["certificate_number"] = certificate }
                else { payload["condition"] = condition }
                pendingPayload = payload
            }
            try await API.shared.mutate("/api/v1/owner/recognition-intake", body: pendingPayload!, key: saveKey)
            saved = true; message = "Saved as a draft. Your portfolio will refresh when you close the scanner."
        } catch { message = error.localizedDescription }
    }
}
