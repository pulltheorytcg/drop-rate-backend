import XCTest
@testable import SellerHub

final class HubPolicyTests: XCTestCase {
    func testOnlyExactHTTPSOriginReceivesSession() {
        XCTAssertTrue(HubPolicy.isHub(HubPolicy.entry))
        XCTAssertTrue(HubPolicy.isHub(URL(string: HubPolicy.origin + ":443/owner")))
        for value in ["http://" + HubPolicy.host, HubPolicy.origin + ".evil.test",
                      "https://user@" + HubPolicy.host, HubPolicy.origin + ":8443/app",
                      "file:///etc/passwd", "javascript:alert(1)", "about:blank"] {
            XCTAssertFalse(HubPolicy.isHub(URL(string: value)), value)
        }
    }
    func testOnlyOwnBlobCanDownload() {
        XCTAssertTrue(HubPolicy.isHubBlob(URL(string: "blob:" + HubPolicy.origin + "/example")!))
        XCTAssertFalse(HubPolicy.isHubBlob(URL(string: "blob:https://evil.test/example")!))
    }
    func testSessionDoesNotPersistClientAuthority() throws {
        let raw = #"{"access_token":"fixture-access","refresh_token":"fixture-refresh","expires_in":3600,"user":{"role":"PLATFORM_ADMIN"},"password":"never-save"}"#
        let clean = try XCTUnwrap(HubPolicy.session(raw))
        XCTAssertFalse(clean.contains("PLATFORM_ADMIN"))
        XCTAssertFalse(clean.contains("never-save"))
        XCTAssertTrue(clean.contains("fixture-refresh"))
        XCTAssertNil(HubPolicy.session("invalid-json"))
        XCTAssertNil(HubPolicy.session(#"{"access_token":"no-refresh"}"#))
        XCTAssertNil(HubPolicy.session(String(repeating: "x", count: 32769)))
    }
    func testDownloadNameCannotEscapeTemporaryDirectory() {
        XCTAssertEqual(HubPolicy.downloadName("../../report.csv"), "report.csv")
        XCTAssertEqual(HubPolicy.downloadName(".."), "Drop-Rate-export")
    }
    func testKeychainRotationLogoutAndNewAccount() throws {
        let namespace = "com.pulltheory.sellerhub.tests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: namespace))
        let store = SessionStore(service: namespace, defaults: defaults)
        defer { try? store.clear(); defaults.removePersistentDomain(forName: namespace) }
        let first = #"{"access_token":"fixture-one","refresh_token":"refresh-one"}"#
        let second = #"{"access_token":"fixture-two","refresh_token":"refresh-two"}"#
        try store.save(first)
        XCTAssertEqual(try store.read(), HubPolicy.session(first))
        try store.save(second)
        XCTAssertEqual(try store.read(), HubPolicy.session(second))
        try store.clear()
        XCTAssertNil(try store.read())
        try store.save(first)
        XCTAssertEqual(try store.read(), HubPolicy.session(first))
    }
    func testInterruptedLogoutDoesNotRestoreKeychainSession() throws {
        let namespace = "com.pulltheory.sellerhub.tests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: namespace))
        let store = SessionStore(service: namespace, defaults: defaults)
        defer { try? store.clear(); defaults.removePersistentDomain(forName: namespace) }
        try store.save(#"{"access_token":"old-session","refresh_token":"old-refresh"}"#)
        defaults.set(true, forKey: namespace + ".signed-out")
        XCTAssertNil(try store.read())
    }
}
