import Foundation

enum NavigationPolicy {
    static let entry = URL(string: "https://app.droprate.co.uk/app")!
    enum Destination { case hub, browser, blocked }
    static func destination(_ url: URL) -> Destination {
        guard url.scheme?.lowercased() == "https", url.user == nil, url.password == nil else { return .blocked }
        if url.host?.lowercased() == "app.droprate.co.uk", url.port == nil || url.port == 443 { return .hub }
        return .browser
    }
}
