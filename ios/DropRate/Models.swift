import Foundation

enum ScanMode: String, CaseIterable, Identifiable {
    case raw = "Raw card", slab = "Slab", comic = "Comic", gradedComic = "Graded comic"
    var id: String { rawValue }
    var isGraded: Bool { self == .slab || self == .gradedComic }
    var isComic: Bool { self == .comic || self == .gradedComic }
}

enum Money {
    static func display(_ minor: Int?) -> String {
        guard let minor else { return "Not valued" }
        return (Decimal(minor) / 100).formatted(.currency(code: "GBP"))
    }
}

struct InventoryPage: Decodable { let total: Int; let items: [InventoryItem] }
struct InventoryItem: Decodable, Identifiable {
    var id: String { inventoryCode }
    let inventoryCode: String
    let name: String
    let game: String
    let setName: String?
    let cardNumber: String?
    let variant: String?
    let language: String?
    let condition: String?
    let gradingCompany: String?
    let grade: String?
    let status: String
    let marketValueMinor: Int?
    let storePriceMinor: Int?
    let recommendedRetailMinor: Int?
    let pricingUpdatedAt: String?
    let imageUrl: String?
    var storeValue: Int? { storePriceMinor ?? recommendedRetailMinor }
}
struct Overview: Decodable {
    let owner: Owner
    let summary: Summary
    struct Owner: Decodable { let displayName: String }
    struct Summary: Decodable {
        let totalInventoryCount: Int
        let activeMarketValueMinor: Int
        let activeStoreValueMinor: Int
    }
}
struct CataloguePage: Decodable { let items: [CatalogueItem]; let hasMore: Bool? }
struct CatalogueItem: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let game: String?
    let setName: String?
    let cardNumber: String?
    let variant: String?
    let language: String?
    let imageUrl: String?
    let marketValueMinor: Int?
    let recommendedRetailMinor: Int?
}
struct GamePage: Decodable { let items: [Game] }
struct Game: Decodable, Identifiable {
    var id: String { game }
    let game: String
    let cardCount: Int
}
struct RecognitionResult: Decodable {
    let run: Run
    let candidates: [Candidate]
    struct Run: Decodable { let id: String; let status: String }
    struct Candidate: Decodable, Identifiable {
        let id: String
        let catalogueId: String?
        let hardRejected: Bool
        let candidateSnapshot: Snapshot
        let marketValueMinor: Int?
        struct Snapshot: Decodable {
            let name: String?
            let game: String?
            let setName: String?
            let cardNumber: String?
            let language: String?
            let variant: String?
        }
    }
}
struct ProfileResponse: Decodable {
    let profile: Profile
    let email: String?
    struct Profile: Decodable {
        let displayName: String
        let username: String?
        let ownerType: String
        let commissionBps: Int?
    }
}
struct PublicConfig: Decodable { let supabaseUrl: String; let publishableKey: String }
struct Session: Codable {
    let accessToken: String
    let refreshToken: String
    let expiresAt: Double?
    let user: User?
    struct User: Codable { let id: String }
}

struct PendingIntake: Codable {
    let key: String
    let payload: [String: String]
}

/// OCR is evidence to review, never a certificate verification response.
struct LabelReading: Equatable {
    let company: String?
    let certificate: String?
    let lines: [String]
    static func certificateFromBarcode(_ payload: String) -> String? {
        let clean = payload.trimmingCharacters(in: .whitespacesAndNewlines)
        if clean.range(of: "^[0-9]{6,12}$", options: .regularExpression) != nil { return clean }
        // Read only known grader URLs. Never navigate to or execute scanned content.
        guard let url = URL(string: clean), url.scheme == "https", let host = url.host?.lowercased(),
              ["psacard.com", "beckett.com", "acegrading.com", "cgccomics.com", "cgccards.com"].contains(where: { host == $0 || host.hasSuffix("." + $0) }) else { return nil }
        let parts = url.pathComponents + (URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.compactMap(\.value) ?? [])
        let numbers = Set(parts.filter { $0.range(of: "^[0-9]{6,12}$", options: .regularExpression) != nil })
        return numbers.count == 1 ? numbers.first : nil
    }
    static func parse(lines: [String]) -> LabelReading {
        let upper = lines.map { $0.uppercased() }
        let text = upper.joined(separator: " ")
        let companies = ["PSA", "BGS", "ACE", "CGC"].filter {
            text.range(of: "\\b\($0)\\b", options: .regularExpression) != nil
        }
        let company = companies.count == 1 ? companies[0] : (companies.isEmpty && text.contains("BECKETT") ? "BGS" : nil)
        // Preserve leading zeroes. Do not turn a grade, year or arbitrary URL into a cert.
        let expression = try! NSRegularExpression(pattern: "(?<![A-Z0-9])[0-9]{6,12}(?![A-Z0-9])")
        let numbers = Set(upper.flatMap { line in
            expression.matches(in: line, range: NSRange(line.startIndex..., in: line)).compactMap {
                Range($0.range, in: line).map { String(line[$0]) }
            }
        })
        return LabelReading(company: company, certificate: company != nil && numbers.count == 1 ? numbers.first : nil, lines: lines)
    }
}
