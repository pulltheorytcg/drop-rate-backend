import XCTest
@testable import DropRate

final class ModelTests: XCTestCase {
    func testCertificatePreservesZeroes() {
        XCTAssertEqual(LabelReading.parse(lines: ["PSA", "0012345678", "GEM MT 10"]).certificate, "0012345678")
    }
    func testAmbiguousNumbersRequireReview() {
        XCTAssertNil(LabelReading.parse(lines: ["CGC", "1234567890", "0987654321"]).certificate)
    }
    func testUnknownGraderDoesNotProduceCertificate() {
        XCTAssertNil(LabelReading.parse(lines: ["12345678"]).certificate)
    }
    func testAllRequestedGraders() {
        for company in ["PSA", "BGS", "ACE", "CGC"] {
            XCTAssertEqual(LabelReading.parse(lines: [company, "1234567890"]).company, company)
        }
    }
    func testGraderMustBeWholeWord() {
        XCTAssertNil(LabelReading.parse(lines: ["SPACE", "12345678"]).company)
    }
    func testBarcodeReadsCertificateWithoutOpeningURL() {
        XCTAssertEqual(LabelReading.certificateFromBarcode("https://www.psacard.com/cert/00123456"), "00123456")
        XCTAssertNil(LabelReading.certificateFromBarcode("https://psacard.com.evil.example/cert/00123456"))
        XCTAssertNil(LabelReading.certificateFromBarcode("javascript:alert(12345678)"))
    }
    func testMoneyDoesNotInventMissingValue() { XCTAssertEqual(Money.display(nil), "Not valued") }
    func testInventoryContractAndStoreFallback() throws {
        let data = Data(#"{"total":1,"items":[{"inventory_code":"INV-1","name":"Card","game":"Pokemon","status":"DRAFT","market_value_minor":null,"store_price_minor":null,"recommended_retail_minor":1234}]}"#.utf8)
        let page = try API.decoder().decode(InventoryPage.self, from: data)
        XCTAssertNil(page.items[0].marketValueMinor)
        XCTAssertEqual(page.items[0].storeValue, 1234)
    }
    func testRecognitionDoesNotNeedOptionalCatalogueFields() throws {
        let data = Data(#"{"run":{"id":"abc","status":"NO_MATCH"},"candidates":[]}"#.utf8)
        let result = try API.decoder().decode(RecognitionResult.self, from: data)
        XCTAssertEqual(result.run.status, "NO_MATCH")
    }
    func testSessionContractAndSecureStorageRoundTrip() throws {
        let data = Data(#"{"access_token":"test-access","refresh_token":"test-refresh","expires_at":1234567890,"user":{"id":"owner-a"}}"#.utf8)
        let session = try API.decoder().decode(Session.self, from: data)
        XCTAssertEqual(session.user?.id, "owner-a")
        let account = "unit-test-" + UUID().uuidString
        defer { SessionVault.clear(account: account) }
        try SessionVault.write(JSONEncoder().encode(session), account: account)
        let restored = try JSONDecoder().decode(Session.self, from: XCTUnwrap(SessionVault.read(account: account)))
        XCTAssertEqual(restored.refreshToken, "test-refresh")
        XCTAssertNil(SessionVault.read(account: account + "-other-owner"))
    }
    func testInterruptedSavePreservesRequestIdentity() throws {
        let pending = PendingIntake(key: UUID().uuidString, payload: ["selected_catalogue_id": "card-a", "certificate_number": "00123456"])
        let restored = try JSONDecoder().decode(PendingIntake.self, from: JSONEncoder().encode(pending))
        XCTAssertEqual(restored.key, pending.key)
        XCTAssertEqual(restored.payload, pending.payload)
    }
    func testUncertainSaveFailuresMustRetainRetryKey() {
        for code in [408, 409, 429, 500, 502, 503] {
            XCTAssertFalse(APIError.response(code, "test").intakeWasRejectedBeforeWriting)
        }
        XCTAssertTrue(APIError.response(422, "Invalid grade").intakeWasRejectedBeforeWriting)
    }
    func testConflictingGraderLabelsAreNotGuessed() {
        XCTAssertNil(LabelReading.parse(lines: ["PSA CGC BECKETT", "12345678"]).company)
    }
}
