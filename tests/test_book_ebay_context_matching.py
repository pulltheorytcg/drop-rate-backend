"""Adversarial evidence checks for display-only exact-edition asking context.

All provider payloads are synthetic. No eBay, database or other network calls
are made, and no fixture represents a completed sale or a physical valuation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from app.book_ebay_context import edition_target, listing_reference, normalize_isbn


NOW = datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc)
ISBN = "9781598163476"
ISBN10 = "1598163477"
OTHER_ISBN = "9781427800022"
ITEM_ID = "v1|123456789012|0"
ITEM_URL = "https://www.ebay.co.uk/itm/123456789012"
IMAGE_URL = "https://i.ebayimg.com/images/g/ABC123/s-l500.jpg"


def canonical_row(**updates):
    row = {
        "catalogue_id": "607ab7c5-4e33-5bd0-8725-640ccb506c98",
        "product_type": "COMIC",
        "system_code": "MANGA",
        "series_title": "+Anima",
        "issue_number": "1",
        "volume_identifier": "Paperback",
        "release_year": 2006,
        "language": "English",
        "barcode_gtin": ISBN,
        "identity_status": "STRUCTURED",
        "profile_status": "STRUCTURED",
        "attributes": {
            "publisher": "Tokyopop",
            "book_format": "MANGA",
            "identity_source": "OPEN_LIBRARY_CATALOGUE",
        },
    }
    row.update(updates)
    return row


def detail(**updates):
    row = {
        "itemId": ITEM_ID,
        "title": "+Anima Volume 1 Paperback English",
        "product": {"gtins": [ISBN]},
        "localizedAspects": [
            {"name": "Language", "value": "English"},
            {"name": "Format", "value": "Paperback"},
            {"name": "Volume", "value": "1"},
        ],
        "itemLocation": {"country": "GB"},
        "price": {"currency": "GBP", "value": "12.50"},
        "buyingOptions": ["FIXED_PRICE"],
        "condition": "Very Good",
        "itemWebUrl": ITEM_URL,
        "image": {"imageUrl": IMAGE_URL},
        "itemCreationDate": "2026-10-01T12:00:00Z",
    }
    row.update(updates)
    return row


def match(row=None, *, canonical=None, expected_item_id=ITEM_ID):
    target = edition_target(canonical if canonical is not None else canonical_row())
    assert target is not None, "The test requires a usable canonical edition"
    return listing_reference(
        row if row is not None else detail(),
        target,
        checked_at=NOW,
        expected_item_id=expected_item_id,
    )


def set_aspect(row, name, value):
    row["localizedAspects"] = [
        item for item in row["localizedAspects"] if item["name"] != name
    ] + [{"name": name, "value": value}]
    return row


def product_aspect(name, *values):
    return {"localizedName": name, "localizedValues": list(values)}


@pytest.mark.parametrize("product", [
    {"additionalProductIdentities": [{"productIdentity": [{"identifierType": "ISBN", "identifierValue": ISBN}]}]},
    {"additionalProductIdentities": [{"productIdentity": [
        {"identifierType": "ISBN-10", "identifierValue": ISBN10},
        {"identifierType": "EAN", "identifierValue": ISBN}]}]},
    {"aspectGroups": [{"localizedGroupName": "Product Identifiers",
                       "aspects": [product_aspect("ISBN-13", ISBN)]}]},
])
def test_documented_nested_product_identifier_paths_prove_the_same_edition(product):
    assert match(detail(product=product)) is not None


def test_nested_product_aspects_can_supply_explicit_listing_edition_facts():
    product = {"aspectGroups": [{"localizedGroupName": "Product Details", "aspects": [
        product_aspect("ISBN", ISBN10, ISBN), product_aspect("Language", "English"),
        product_aspect("Format", "Paperback"), product_aspect("Volume", "1"),
        product_aspect("Publisher", "Tokyopop"), product_aspect("Publication Year", "2006")]}]}
    assert match(detail(product=product, localizedAspects=[])) is not None


@pytest.mark.parametrize("name,value", [
    ("ISBN", OTHER_ISBN), ("Language", "Japanese"), ("Format", "Hardcover"),
    ("Volume", "2"), ("Publisher", "VIZ Media"), ("Publication Year", "2007"),
    ("Signed", "Yes"), ("Features", "Omnibus signed edition"),
])
def test_product_aspects_never_overwrite_conflicting_item_facts(name, value):
    row = detail(product={"gtins": [ISBN], "aspectGroups": [{"aspects": [product_aspect(name, value)]}]})
    assert match(row) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicts_between_product_groups_remain_visible_regardless_of_order(reverse):
    groups = [{"aspects": [product_aspect("Language", "English")]},
              {"aspects": [product_aspect("Language", "Japanese")]}]
    if reverse:
        groups.reverse()
    assert match(detail(product={"gtins": [ISBN], "aspectGroups": groups})) is None


def test_conflicting_nested_identifier_cannot_hide_behind_matching_flat_identifier():
    product = {"gtins": [ISBN], "additionalProductIdentities": [{"productIdentity": [
        {"identifierType": "ISBN", "identifierValue": OTHER_ISBN}]}]}
    assert match(detail(product=product)) is None


@pytest.mark.parametrize("product", [
    None, [], {"aspectGroups": None}, {"aspectGroups": [{}]},
    {"aspectGroups": [{"aspects": [product_aspect("ISBN", ISBN), {"localizedName": "Language", "localizedValues": "English"}]}]},
    {"aspectGroups": [{"aspects": [{"localizedName": "ISBN", "localizedValues": [ISBN, 123]}]}]},
    {"aspectGroups": [{"aspects": [{"localizedName": "ISBN", "localizedValues": []}]}]},
    {"aspectGroups": [{"aspects": [product_aspect("ISBN", "x" * 501)]}]},
    {"aspectGroups": [{"aspects": [product_aspect("Language", "English")]}] * 21},
    {"additionalProductIdentities": {}},
    {"additionalProductIdentities": [{"productIdentity": {}}]},
    {"additionalProductIdentities": [{"productIdentity": [{"identifierType": "ISBN", "identifierValue": 9781598163476}]}]},
    {"additionalProductIdentities": [{"productIdentity": [{"identifierType": "ISBN", "identifierValue": "x" * 501}]}]},
])
def test_malformed_or_excessive_product_containers_cannot_match(product):
    assert match(detail(gtin=ISBN, product=product)) is None


def test_title_isbn_alone_is_still_insufficient_identity_evidence():
    assert match(detail(title=f"+Anima Volume 1 Paperback ISBN {ISBN}", product={})) is None


@pytest.mark.parametrize(
    "value, expected",
    [
        (ISBN, ISBN),
        ("978-1-59816-347-6", ISBN),
        ("978 1 59816 347 6", ISBN),
        (ISBN10, ISBN),
        ("1-59816-347-7", ISBN),
        ("159116852X", "9781591168522"),
        ("159116852x", "9781591168522"),
        ("9791234567896", "9791234567896"),
    ],
)
def test_isbn_checksums_and_equivalent_printed_forms(value, expected):
    assert normalize_isbn(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None, True, 9781598163476, "", "9781598163470", "1598163470",
        "97815981634761", "09781598163476", "1591168520", "9791234567890",
        "9781598163476;9781427800022", "ISBN 9781598163476",
        "９７８１５９８１６３４７６", "9781598163476/1598163477",
    ],
)
def test_invalid_or_ambiguous_identifiers_are_not_canonical_isbns(value):
    assert normalize_isbn(value) is None


def test_trusted_structured_edition_does_not_require_invented_printing_verification():
    row = canonical_row()
    target = edition_target(row)
    assert target is not None
    assert target.isbn == ISBN
    assert target.volume == "1"
    assert target.language == "English"
    assert target.binding.lower() == "paperback"
    assert row["identity_status"] == "STRUCTURED"
    assert "printing_number" not in row


def test_database_json_attributes_have_the_same_identity_as_decoded_attributes():
    row = canonical_row()
    original = edition_target(row)
    row["attributes"] = json.dumps(row["attributes"])
    encoded = edition_target(row)
    assert original is not None and encoded is not None
    assert encoded == original


@pytest.mark.parametrize("attributes", [None, [], "not JSON", {"book_format": "MANGA"}])
def test_incomplete_database_attributes_fail_without_a_provider_lookup(attributes):
    assert edition_target(canonical_row(attributes=attributes)) is None


@pytest.mark.parametrize(
    "updates",
    [
        {"product_type": "CARD"},
        {"identity_status": "NEEDS_REVIEW"},
        {"profile_status": "NEEDS_REVIEW"},
        {"barcode_gtin": "9781598163470"},
        {"barcode_gtin": None},
        {"language": None},
        {"series_title": ""},
        {"issue_number": ""},
        {"issue_number": "1-3"},
    ],
)
def test_incomplete_or_untrusted_canonical_identity_cannot_start_a_match(updates):
    assert edition_target(canonical_row(**updates)) is None


@pytest.mark.parametrize("unknown_binding", [None, "Manga"])
def test_manga_category_does_not_itself_prove_paperback_binding(unknown_binding):
    target = edition_target(canonical_row(volume_identifier=unknown_binding))
    assert target is not None
    assert target.binding is None


@pytest.mark.parametrize("binding", ["Paperback", "Hardcover"])
def test_unknown_canonical_binding_keeps_the_listing_physical_binding_explicit(binding):
    row = set_aspect(detail(title=f"+Anima Volume 1 {binding} English"), "Format", binding)
    result = match(row, canonical=canonical_row(volume_identifier=None))
    assert result is not None
    assert result["binding"].lower() == binding.lower()


def test_unknown_canonical_binding_does_not_allow_unstated_listing_format():
    row = detail(title="+Anima Volume 1 English")
    row["localizedAspects"] = [item for item in row["localizedAspects"] if item["name"] != "Format"]
    assert match(row, canonical=canonical_row(volume_identifier=None)) is None


def test_actual_listing_facts_are_returned_without_market_value_semantics():
    result = match()
    assert result is not None
    assert result["item_id"] == ITEM_ID
    assert result["title"] == detail()["title"]
    assert result["condition"] == "Very Good"
    assert result["price_minor"] == 1250
    assert result["shipping_minor"] is None
    assert result["url"] == ITEM_URL
    assert result["image_url"] == IMAGE_URL
    assert datetime.fromisoformat(result["listed_at"].replace("Z", "+00:00")) == datetime(
        2026, 10, 1, 12, tzinfo=timezone.utc
    )
    assert not {"market_value_minor", "recommended_retail_minor", "sold_at"}.intersection(result)


@pytest.mark.parametrize("condition", ["New", "Good", "Acceptable", "Very Good"])
def test_actual_provider_condition_is_not_replaced_with_near_mint(condition):
    result = match(detail(condition=condition))
    assert result is not None
    assert result["condition"] == condition


@pytest.mark.parametrize(
    "identifier_payload",
    [
        {"product": {"gtins": [ISBN10]}},
        {"product": {"gtins": [ISBN10, ISBN]}},
        {"product": {"gtins": ["978-1-59816-347-6"]}},
    ],
)
def test_returned_equivalent_isbn_aliases_bind_the_same_edition(identifier_payload):
    assert match(detail(**identifier_payload)) is not None


@pytest.mark.parametrize("name,value", [("ISBN", ISBN), ("ISBN-13", ISBN), ("ISBN-10", ISBN10)])
def test_returned_isbn_aspect_is_evidence_even_without_product_gtins(name, value):
    row = detail(product={})
    row["localizedAspects"].append({"name": name, "value": value})
    assert match(row) is not None


def test_search_hit_and_title_isbn_alone_do_not_prove_returned_product_identity():
    row = detail(product={}, title=f"+Anima Volume 1 Paperback English ISBN {ISBN}")
    assert match(row) is None


@pytest.mark.parametrize("other", [OTHER_ISBN, "9781598163470", "not an ISBN"])
def test_one_matching_gtin_cannot_hide_conflicting_or_invalid_identifiers(other):
    row = detail(product={"gtins": [ISBN, other]})
    assert match(row) is None


def test_conflicting_isbn_aspect_overrides_a_matching_product_gtin():
    row = detail()
    row["localizedAspects"].append({"name": "ISBN", "value": OTHER_ISBN})
    assert match(row) is None


def test_conflicting_isbn_in_title_overrides_matching_structured_identifiers():
    row = detail(title=f"+Anima Volume 1 Paperback English ISBN {OTHER_ISBN}")
    assert match(row) is None


def test_explicit_conflicting_title_isbn_does_not_require_a_space_after_the_label():
    row = detail(title=f"+Anima Volume 1 Paperback English ISBN{OTHER_ISBN}")
    assert match(row) is None


def test_hyphenated_exact_isbn_in_title_is_not_treated_as_a_volume_range():
    row = detail(title="+Anima Volume 1 Paperback English ISBN 978-1-59816-347-6")
    assert match(row) is not None


@pytest.mark.parametrize(
    "name,value",
    [
        ("Language", "Japanese"),
        ("Language", "English and Japanese"),
        ("Volume", "2"),
        ("Volume", "1-3"),
        ("Format", "Hardcover"),
        ("Format", "eBook"),
        ("Format", "Paperback and eBook"),
    ],
)
def test_explicit_aspect_conflicts_override_compatible_title(name, value):
    assert match(set_aspect(detail(), name, value)) is None


@pytest.mark.parametrize(
    "title",
    [
        "+Anima Volume 2 Paperback English",
        "+Anima Volume 1 Paperback Japanese",
        "+Anima Volume 1 Hardcover English",
        "+Animax Volume 1 Paperback English",
        "+Anima Volumes 1-3 Paperback English",
        "+Anima Volume 1 and Volume 2 Paperback English",
        "+Anima Volumes 1 & 2 Paperback English",
        "+Anima Volume 1 + 2 Paperback English",
    ],
)
def test_conflicting_title_identity_is_not_rescued_by_aspects(title):
    assert match(detail(title=title)) is None


@pytest.mark.parametrize(
    "extra",
    [
        "digital", "eBook", "Kindle", "PDF", "bundle", "box set", "lot of 2",
        "set of 3", "choose a volume", "pick your volume", "x2", "2 copies",
        "CGC 9.8", "BGS 9.5", "PSA 10", "signed", "restored", "ex-library",
        "missing pages", "facsimile", "replica", "poster", "dust jacket only",
        "cover only", "empty box", "without book",
    ],
)
def test_digital_multi_item_graded_and_special_copy_context_is_excluded(extra):
    assert match(detail(title=f"+Anima Volume 1 Paperback English {extra}")) is None


@pytest.mark.parametrize(
    "name,value",
    [("Signed", "Yes"), ("Professional Grader", "CGC"), ("Features", "Ex-Library")],
)
def test_special_copy_aspects_are_not_hidden_by_an_ordinary_title(name, value):
    row = detail()
    row["localizedAspects"].append({"name": name, "value": value})
    assert match(row) is None


def test_explicitly_unsigned_is_not_mistaken_for_a_signed_copy():
    row = detail()
    row["localizedAspects"].append({"name": "Signed", "value": "No"})
    assert match(row) is not None


def test_actual_condition_cannot_disguise_an_accessory_as_a_complete_book():
    assert match(detail(condition="Very Good; dust jacket only")) is None


@pytest.mark.parametrize(
    "value",
    [None, True, False, {}, "NaN", "sNaN", "Infinity", "-Infinity", "1e99999", "0", "-1", "0.001", "10000000000000"],
)
def test_invalid_prices_never_escape_as_an_asking_quote(value):
    assert match(detail(price={"currency": "GBP", "value": value})) is None


@pytest.mark.parametrize("currency", ["USD", "EUR", None])
def test_no_currency_conversion_or_currency_guessing(currency):
    assert match(detail(price={"currency": currency, "value": "12.50"})) is None


def test_provider_free_shipping_is_zero_not_unknown():
    row = detail(shippingOptions=[{"shippingCost": {"currency": "GBP", "value": "0.00"}}])
    result = match(row)
    assert result is not None
    assert result["shipping_minor"] == 0
    assert result["price_minor"] == 1250


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "1e99999", True])
def test_invalid_shipping_is_not_fabricated_as_free_postage(value):
    row = detail(shippingOptions=[{"shippingCost": {"currency": "GBP", "value": value}}])
    result = match(row)
    assert result is None or result["shipping_minor"] is None


@pytest.mark.parametrize("country", ["US", "IE", None, ""])
def test_gbp_or_uk_url_does_not_override_non_gb_item_location(country):
    assert match(detail(itemLocation={"country": country})) is None


@pytest.mark.parametrize("options", [[], ["AUCTION"], None, "NOT_FIXED_PRICE", {"FIXED_PRICE": False}])
def test_an_auction_bid_is_not_a_fixed_asking_price(options):
    assert match(detail(buyingOptions=options)) is None


def test_ended_listing_is_not_current_asking_context():
    assert match(detail(itemEndDate="2026-10-26T20:00:00Z")) is None


def test_known_out_of_stock_listing_is_not_current_asking_context():
    row = detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "OUT_OF_STOCK"}])
    assert match(row) is None


def test_malformed_availability_cannot_hide_an_explicit_out_of_stock_status():
    row = detail(estimatedAvailabilities={"estimatedAvailabilityStatus": "OUT_OF_STOCK"})
    assert match(row) is None


def test_one_available_status_cannot_override_a_conflicting_out_of_stock_status():
    row = detail(estimatedAvailabilityStatus="IN_STOCK", availabilityStatus="OUT_OF_STOCK")
    assert match(row) is None


def test_malformed_availability_status_is_rejected_without_raising():
    row = detail(estimatedAvailabilityStatus={"status": "OUT_OF_STOCK"})
    assert match(row) is None


@pytest.mark.parametrize(
    "name,prefix,conflict",
    [("Language", "English", "Japanese"), ("Format", "Paperback", "Hardcover"), ("Volume", "1", "2")],
)
def test_oversized_identity_aspect_cannot_lose_a_conflict_through_truncation(name, prefix, conflict):
    row = set_aspect(detail(), name, prefix + " " * 500 + conflict)
    assert match(row) is None


def test_fetched_item_must_match_the_exact_requested_provider_id():
    assert match(detail(itemId="v1|123456789013|0")) is None


def test_item_url_must_refer_to_the_same_legacy_listing_id():
    assert match(detail(itemWebUrl="https://www.ebay.co.uk/itm/123456789013")) is None


def test_recognized_item_url_drops_tracking_and_redirect_query_parameters():
    result = match(detail(itemWebUrl=ITEM_URL + "?hash=item123&campid=456&url=https%3A%2F%2Fevil.test"))
    assert result is not None
    assert result["url"] == ITEM_URL


def test_exact_variation_url_preserves_only_its_matching_numeric_variant():
    variant_id = "v1|123456789012|9876543210"
    row = detail(itemId=variant_id, itemWebUrl=ITEM_URL + "?var=9876543210&campid=456")
    result = match(row, expected_item_id=variant_id)
    assert result is not None
    assert result["url"] == ITEM_URL + "?var=9876543210"


@pytest.mark.parametrize("query", ["", "?var=9876543211", "?var=9876543210&var=9876543211"])
def test_variation_id_cannot_be_lost_or_changed_by_its_source_url(query):
    variant_id = "v1|123456789012|9876543210"
    row = detail(itemId=variant_id, itemWebUrl=ITEM_URL + query)
    assert match(row, expected_item_id=variant_id) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://www.ebay.co.uk/itm/123456789012",
        "//www.ebay.co.uk/itm/123456789012",
        "https://www.ebay.co.uk.evil.test/itm/123456789012",
        "https://evil.test/itm/123456789012",
        "https://user:secret@www.ebay.co.uk/itm/123456789012",
        "https://www.ebay.co.uk:443/itm/123456789012",
        "https://www.ebay.co.uk/redirect?item=123456789012",
        "https://www.ebay.co.uk/itm/123456789012/../../other",
        "javascript:alert(1)",
    ],
)
def test_untrusted_source_links_cannot_be_returned_as_valid_item_links(url):
    assert match(detail(itemWebUrl=url)) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://i.ebayimg.com/images/g/ABC123/s-l500.jpg",
        "//i.ebayimg.com/images/g/ABC123/s-l500.jpg",
        "https://i.ebayimg.com.evil.test/images/g/ABC123/s-l500.jpg",
        "https://user:secret@i.ebayimg.com/images/g/ABC123/s-l500.jpg",
        "https://i.ebayimg.com:443/images/g/ABC123/s-l500.jpg",
        "https://i.ebayimg.com/images/g/ABC123/../s-l500.jpg",
        "https://i.ebayimg.com/images/g/ABC123/%2e%2e/s-l500.jpg",
        "https://i.ebayimg.com/redirect?url=https://evil.test/photo.jpg",
        "https://i.ebayimg.com/images/g/ABC123/s-l500.jpg?url=https://evil.test/photo.jpg",
        "https://i.ebayimg.com/images/g/ABC123/s-l500.svg",
        "data:image/svg+xml,<svg onload=alert(1)>",
    ],
)
def test_unsafe_image_is_omitted_without_forging_replacement_art(url):
    result = match(detail(image={"imageUrl": url}))
    assert result is None or result["image_url"] is None


def test_matching_does_not_mutate_canonical_or_provider_payloads():
    canonical = canonical_row()
    listing = detail()
    before = deepcopy((canonical, listing))
    assert match(listing, canonical=canonical) is not None
    assert (canonical, listing) == before
