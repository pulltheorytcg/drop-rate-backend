"""Display references must never weaken edition, copy, media, or price evidence."""
from copy import deepcopy
from datetime import date
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.book_bulk_import import source_attributes
from app.book_catalogue import with_book_details
from app.book_catalogue_sources import _normalise_adapted
from app.book_community_artwork import (
    KIND, community_book_covers, community_cover_reference,
)
from app.book_research import add_saved_book_artwork, catalogue_candidates


def test_rendered_founder_and_seller_shells_load_the_same_current_cover_assets():
    from html.parser import HTMLParser
    from app.main import STATIC_DIR, _dashboard_html

    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sources = []

        def handle_starttag(self, tag, attrs):
            if tag == "script" and dict(attrs).get("src"):
                self.sources.append(dict(attrs)["src"])

    scripts = []
    for html in (_dashboard_html(), (STATIC_DIR / "owner.html").read_text()):
        parsed = Scripts(); parsed.feed(html)
        cover = [src for src in parsed.sources if src.startswith("/assets/book-community-artwork.js?")]
        catalogue = [src for src in parsed.sources if src.startswith("/assets/catalogue-browser.js?")]
        assert cover == ["/assets/book-community-artwork.js?v=1"]
        assert catalogue == ["/assets/catalogue-browser.js?v=book-community-covers-v1"]
        assert parsed.sources.index(cover[0]) < parsed.sources.index(catalogue[0])
        scripts.append((cover, catalogue))
    assert scripts[0] == scripts[1]


def imported_book(edition_id="OL8537239M"):
    entry = _normalise_adapted(dict(
        provider="OPEN_LIBRARY", record_id=edition_id,
        book=dict(system_code="MANGA", series_title="+Anima", issue_number="1",
                  volume_identifier="Paperback", printing_number=None, release_year=2006,
                  cover_code=None, cover_artist=None, barcode_gtin="9781598163476",
                  publisher="Tokyopop", book_format="MANGA"),
        language="English", source_url="https://openlibrary.org/books/" + edition_id,
        release_date="2006-05-09", observed_on="2026-10-27", image_url=None,
        evidence_url="https://archive.org/download/ol_dump_2026-09-30/ol_dump_editions_2026-09-30.txt.gz"))
    return dict(
        **{key: value for key, value in entry["book"].items() if key not in {"publisher", "book_format"}},
        catalogue_id=UUID(entry["id"]), language="English", name=entry["catalogue"]["name"],
        identity_status="STRUCTURED", profile_status="STRUCTURED",
        profile_release_date=date(2006, 5, 9), attributes=source_attributes(entry, "test"),
        identity_key=entry["identity_key"], catalogue_product=entry["catalogue"],
        mapping_provider_id=edition_id, mapping_source_reference=entry["source_url"],
        mapping_status="REVIEW", mapping_verification_basis="DETERMINISTIC_EXACT",
        mapping_metadata=dict(import_version="book-bulk-v1", record_digest=entry["record_digest"],
                              identity_key=entry["identity_key"],
                              metadata_license=entry["metadata_license"]))


def test_exact_unchanged_import_gets_only_a_public_display_reference():
    row = imported_book(); before = deepcopy(row)
    cover = community_cover_reference(row)
    assert cover == dict(kind=KIND, provider="OPEN_LIBRARY", edition_id="OL8537239M",
                         language="English", scope="COMMUNITY_EDITION", status="REFERENCE_ONLY",
                         image_url="https://covers.openlibrary.org/b/olid/OL8537239M-M.jpg?default=false",
                         detail_image_url="https://covers.openlibrary.org/b/olid/OL8537239M-M.jpg?default=false",
                         source_url="https://openlibrary.org/books/OL8537239M")
    assert row == before
    assert row["attributes"]["cover_rights_status"] == "PENDING"
    assert row["attributes"]["publisher_reference"] is None


@pytest.mark.parametrize("path,value", [
    (("identity_status",), "NEEDS_REVIEW"), (("identity_status",), "VERIFIED"),
    (("profile_status",), "NEEDS_REVIEW"), (("language",), "Japanese"),
    (("issue_number",), "2"), (("series_title",), "Another manga"),
    (("printing_number",), 1), (("cover_code",), "Variant B"),
    (("barcode_gtin",), "9781569319017"), (("profile_release_date",), date(2006, 5, 10)),
    (("identity_key",), "changed"), (("catalogue_product", "name"), "Different product"),
    (("attributes", "publisher"), "VIZ Media"), (("attributes", "book_format"), "HARDCOVER"),
    (("attributes", "identity_source"), "SELLER_ENTERED"),
    (("attributes", "source_url"), "https://openlibrary.org/books/OL2M"),
    (("attributes", "source_url"), "https://openlibrary.org.evil.test/books/OL8537239M"),
    (("attributes", "cover_rights_status"), "REVOKED"),
    (("attributes", "cover_rights_status"), "REJECTED"),
    (("attributes", "cover_source_status"), "INACTIVE"),
    (("attributes", "catalogue_import", "provider"), "PUBLISHER"),
    (("attributes", "catalogue_import", "record_id"), "OL8537239W"),
    (("attributes", "catalogue_import", "record_digest"), "0" * 64),
    (("attributes", "catalogue_import", "source_snapshot"), "https://example.test/dump.gz"),
    (("attributes", "catalogue_import", "metadata_license"), "CC0"),
    (("mapping_metadata", "record_digest"), "0" * 64),
    (("mapping_metadata", "identity_key"), "another edition"),
    (("mapping_metadata", "import_version"), "manual"),
    (("mapping_provider_id",), "OL2M"), (("mapping_status",), "REJECTED"),
    (("mapping_source_reference",), "https://openlibrary.org/books/OL2M"),
    (("mapping_verification_basis",), "TITLE_MATCH"),
])
def test_changed_identity_receipt_or_mapping_never_gets_a_cover(path, value):
    row = imported_book(); target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert community_cover_reference(row) is None


def test_known_incorrect_source_cover_is_excluded_without_replacing_its_edition():
    assert community_cover_reference(imported_book("OL9465913M")) is None


def test_reviewed_metadata_hold_cannot_be_cleared_by_a_cover(monkeypatch):
    from app import book_openlibrary_bulk
    monkeypatch.setattr(book_openlibrary_bulk, "reviewed_hold_registry", lambda: ({
        "9781598163476": {"source_id": "OL8537239M", "reason": "EDITION_REVIEW"}}, "digest"))
    assert community_cover_reference(imported_book()) is None


@pytest.mark.asyncio
async def test_batch_read_is_exact_bounded_and_read_only_and_rejects_ambiguity():
    row = imported_book(); db = AsyncMock(); db.fetch.return_value = [row]
    assert str(row["catalogue_id"]) in await community_book_covers(db, [row["catalogue_id"]])
    sql, ids = db.fetch.await_args.args
    assert ids == [row["catalogue_id"]]
    for required in ("p.id=any($1::uuid[])", "m.source_provider='OPEN_LIBRARY'",
                     "m.provider_entity_type='COMIC_PRINTING'", "m.provider_variant_key=''",
                     "m.provider_language=''", "m.system_code=b.system_code"):
        assert required in sql
    db.execute.assert_not_awaited()
    db.fetch.return_value = [row, row]
    assert await community_book_covers(db, [row["catalogue_id"]]) == {}


@pytest.mark.asyncio
async def test_catalogue_display_does_not_create_prices_or_canonical_media():
    row = imported_book(); db = AsyncMock(); db.fetch.side_effect = [[row], [row]]
    source = dict(catalogue_id=row["catalogue_id"], product_type="COMIC", language="English", market_value_minor=None)
    [result] = await with_book_details(db, [source])
    assert result["community_cover"]["kind"] == KIND
    assert result["artwork_kind"] == KIND
    assert "community_cover" not in source
    assert "reference_image_url" not in result and "reference_image_path" not in result
    assert "image_url" not in result and "display_image_url" not in result
    assert result["market_value_minor"] is None
    assert result["book_market_status"] == "PRINTING_REVIEW_REQUIRED"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_catalogue_image_keeps_priority_and_needs_no_community_read():
    row = imported_book(); db = AsyncMock(); db.fetch.return_value = [row]
    [result] = await with_book_details(db, [dict(catalogue_id=row["catalogue_id"],
        product_type="COMIC", language="English", display_image_url="https://cdn.shopify.com/approved.jpg")])
    assert "community_cover" not in result
    db.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_saved_copy_reference_keeps_owner_language_boundary_and_proxy_fields_empty():
    row = imported_book(); row.update(inventory_id=uuid4(), provider_evidence=None)
    db = AsyncMock(); db.fetch.side_effect = [[row], [row]]
    item = dict(id=row["inventory_id"], catalogue_id=row["catalogue_id"], product_type="COMIC")
    await add_saved_book_artwork(db, [item])
    assert item["community_cover"]["kind"] == KIND
    assert "reference_image_url" not in item and "reference_image_path" not in item
    assert "image_url" not in item
    sql, ids = db.fetch.await_args_list[0].args
    assert "where i.id=any($1::uuid[])" in sql and ids == [row["inventory_id"]]
    assert "coalesce(i.language,p.language)=p.language" in sql
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_community_image_does_not_become_scanner_identity_or_photo_match():
    row = imported_book(); db = AsyncMock(); db.fetch.return_value = [row]
    candidates = await catalogue_candidates(db, dict(barcode_gtin=row["barcode_gtin"], language="English"))
    assert candidates == []
    db.fetch.assert_awaited_once()
    db.execute.assert_not_awaited()
