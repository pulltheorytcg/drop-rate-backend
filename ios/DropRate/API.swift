import Foundation
import Security

enum APIError: LocalizedError {
    case response(Int, String), signedOut, invalidConfiguration, storage
    var errorDescription: String? {
        switch self {
        case .response(_, let message): return message
        case .signedOut: return "Please sign in again."
        case .invalidConfiguration: return "The server configuration could not be verified."
        case .storage: return "Your session could not be saved securely. Please try again."
        }
    }
}

enum SessionVault {
    static let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "DropRate.SellerHub", kSecAttrAccount as String: "session"]
    static func read(account: String = "session") -> Data? {
        var q = query; q[kSecAttrAccount as String] = account; q[kSecReturnData as String] = true
        var value: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &value) == errSecSuccess else { return nil }
        return value as? Data
    }
    static func write(_ data: Data, account: String = "session") throws {
        var query = self.query; query[kSecAttrAccount as String] = account
        let attrs = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, attrs as CFDictionary)
        if status == errSecItemNotFound {
            var q = query; q[kSecValueData as String] = data
            q[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            guard SecItemAdd(q as CFDictionary, nil) == errSecSuccess else { throw APIError.storage }
        } else if status != errSecSuccess { throw APIError.storage }
    }
    static func clear(account: String = "session") {
        var q = query; q[kSecAttrAccount as String] = account; SecItemDelete(q as CFDictionary)
    }
}

actor API {
    static let base = URL(string: "https://drop-rate-api-live-production.up.railway.app")!
    static let shared = API()
    private let transport: URLSession
    private var session: Session?
    private var refreshTask: Task<Session, Error>?
    private var generation = 0
    private var config: PublicConfig?
    static func decoder() -> JSONDecoder {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }
    init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 90
        config.timeoutIntervalForResource = 120
        transport = URLSession(configuration: config)
        if let data = SessionVault.read() { session = try? JSONDecoder().decode(Session.self, from: data) }
    }
    func hasSession() -> Bool { session != nil }
    private func intakeAccount() throws -> String {
        guard let id = session?.user?.id else { throw APIError.signedOut }
        return "pending-intake:" + id
    }
    func hasPendingIntake() -> Bool {
        guard let account = try? intakeAccount() else { return false }
        return SessionVault.read(account: account) != nil
    }
    func saveIntake(payload: [String: String], key: String) async throws {
        let account = try intakeAccount()
        if let data = SessionVault.read(account: account) {
            let pending = try JSONDecoder().decode(PendingIntake.self, from: data)
            guard pending.key == key, pending.payload == payload else {
                throw APIError.response(409, "Finish your previous card save from Portfolio before adding another card.")
            }
        } else {
            try SessionVault.write(JSONEncoder().encode(PendingIntake(key: key, payload: payload)), account: account)
        }
        try await resumeIntake()
    }
    func resumeIntake() async throws {
        let account = try intakeAccount()
        guard let data = SessionVault.read(account: account) else { return }
        let pending = try JSONDecoder().decode(PendingIntake.self, from: data)
        _ = try await request("/api/v1/owner/recognition-intake", method: "POST", body: pending.payload, key: pending.key)
        SessionVault.clear(account: account)
    }
    private func store(_ value: Session) throws {
        try SessionVault.write(JSONEncoder().encode(value)); session = value
    }
    func login(identifier: String, password: String) async throws {
        let data = try await send(url: Self.base.appendingPathComponent("api/v1/public/owner-session"),
            method: "POST", body: ["identifier": identifier, "password": password])
        let value = try Self.decoder().decode(Session.self, from: data)
        generation += 1
        try store(value)
        do { let _: ProfileResponse = try await get("/api/v1/owner/profile") }
        catch { await logout(); throw error }
    }
    private func configuration() async throws -> PublicConfig {
        if let config { return config }
        let data = try await send(url: Self.base.appendingPathComponent("api/v1/public-config"))
        let value = try Self.decoder().decode(PublicConfig.self, from: data)
        guard let url = URL(string: value.supabaseUrl), url.scheme == "https",
              url.host?.hasSuffix(".supabase.co") == true else { throw APIError.invalidConfiguration }
        config = value; return value
    }
    private func token(force: Bool = false) async throws -> String {
        guard let session else { throw APIError.signedOut }
        if !force, let expires = session.expiresAt, expires > Date().timeIntervalSince1970 + 60 {
            return session.accessToken
        }
        if let refreshTask { return try await refreshTask.value.accessToken }
        let currentGeneration = generation
        let task = Task<Session, Error> {
            let config = try await self.configuration()
            let url = URL(string: config.supabaseUrl + "/auth/v1/token?grant_type=refresh_token")!
            let data = try await self.send(url: url, method: "POST", body: ["refresh_token": session.refreshToken],
                headers: ["apikey": config.publishableKey])
            return try Self.decoder().decode(Session.self, from: data)
        }
        refreshTask = task
        defer { refreshTask = nil }
        do {
            let value = try await task.value
            guard generation == currentGeneration else { throw APIError.signedOut }
            try store(value); return value.accessToken
        } catch APIError.response(let code, _) where code == 400 || code == 401 {
            self.session = nil; SessionVault.clear(); throw APIError.signedOut
        }
    }
    func logout() async {
        let old = session
        generation += 1; session = nil; refreshTask?.cancel(); refreshTask = nil; SessionVault.clear()
        if let old, let config = try? await configuration(),
           let url = URL(string: config.supabaseUrl + "/auth/v1/logout?scope=local") {
            _ = try? await send(url: url, method: "POST", headers: ["apikey": config.publishableKey, "Authorization": "Bearer \(old.accessToken)"])
        }
    }
    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        try Self.decoder().decode(T.self, from: await request(path, query: query))
    }
    func post<T: Decodable>(_ path: String, body: [String: String], key: String? = nil) async throws -> T {
        try Self.decoder().decode(T.self, from: await request(path, method: "POST", body: body, key: key))
    }
    func mutate(_ path: String, method: String = "POST", body: [String: String], key: String? = nil) async throws {
        _ = try await request(path, method: method, body: body, key: key)
    }
    private func request(_ path: String, method: String = "GET", query: [String: String] = [:], body: [String: String]? = nil, key: String? = nil) async throws -> Data {
        var parts = URLComponents(url: Self.base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        parts.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        var headers = ["Authorization": "Bearer \(try await token())"]
        if let key { headers["Idempotency-Key"] = key }
        do { return try await send(url: parts.url!, method: method, body: body, headers: headers) }
        catch APIError.response(401, _) {
            headers["Authorization"] = "Bearer \(try await token(force: true))"
            return try await send(url: parts.url!, method: method, body: body, headers: headers)
        }
    }
    private func send(url: URL, method: String = "GET", body: [String: String]? = nil, headers: [String: String] = [:]) async throws -> Data {
        var request = URLRequest(url: url); request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        if let body { request.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, response) = try await transport.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.response(0, "The server did not respond.") }
        guard (200...299).contains(http.statusCode) else {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let message = object?["detail"] as? String ?? "Request failed (\(http.statusCode)). Please try again."
            throw APIError.response(http.statusCode, message)
        }
        return data
    }
}
