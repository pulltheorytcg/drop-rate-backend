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
}
