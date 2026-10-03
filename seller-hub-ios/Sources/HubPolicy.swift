import Foundation

enum HubPolicy {
    static let host = "drop-rate-api-live-production.up.railway.app"
    static let origin = "https://" + host
    static let entry = URL(string: origin + "/app")!
    static let sessionKey = "drop_rate_hub_session"

    static func isHub(_ url: URL?) -> Bool {
        guard let url else { return false }
        return url.scheme?.lowercased() == "https" && url.host?.lowercased() == host
            && (url.port == nil || url.port == 443) && url.user == nil && url.password == nil
    }

    static func isExternalHTTPS(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && url.host != nil && url.user == nil && url.password == nil
    }

    static func isHubBlob(_ url: URL) -> Bool {
        guard url.scheme == "blob" else { return false }
        return isHub(URL(string: String(url.absoluteString.dropFirst(5))))
    }

    // Keep only credentials needed for the hub to revalidate the account. Never
    // persist client roles or infer authorization from a JWT or profile field.
    static func session(_ raw: String) -> String? {
        guard raw.utf8.count <= 32768, let data = raw.data(using: .utf8),
              let input = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let access = input["access_token"] as? String, !access.isEmpty,
              let refresh = input["refresh_token"] as? String, !refresh.isEmpty else { return nil }
        var result: [String: Any] = ["access_token": access, "refresh_token": refresh, "token_type": "bearer"]
        for key in ["expires_in", "expires_at"] {
            if let value = input[key] as? NSNumber { result[key] = value }
        }
        guard let encoded = try? JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]),
              let output = String(data: encoded, encoding: .utf8) else { return nil }
        return output
    }

    static func downloadName(_ value: String) -> String {
        let name = (value as NSString).lastPathComponent
            .replacingOccurrences(of: "\u{0}", with: "")
        return name.isEmpty || name == "." || name == ".." ? "Drop-Rate-export" : String(name.prefix(180))
    }
}
