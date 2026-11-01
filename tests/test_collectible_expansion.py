"""New category contracts: exact identity, provenance, R2 parity and no phantom value."""
from datetime import datetime, timedelta, timezone
import copy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import collectible_reference_feed as feed
from app.collectible_source_adapters import (
    ReferenceSourceError, figure_product, group_yugioh_printings,
    lorcana_printing, sports_checklist_printing, yugioh_printings,
)
from app.object_storage import ObjectStorageError


def _row(**overrides):
    row = dict.fromkeys(feed.FIELDS)
    row.update(provider="Funko Official", system_code="FUNKO_POP", language="English",
               provider_id="97402", name="Pop! Yellow Lantern", manufacturer="Funko",
               variant="", source_url="https://funko.com/gb/pop-yellow-lantern/97402.html")
    row.update(overrides)
    return row


def test_figure_r2_metadata_roundtrip_keeps_every_identifier_and_unknown_price():
    row = _row(barcode_gtin="889698974027", figure_number="123", franchise="DC")
    manifest, parts = feed.pack("FUNKO_POP", 3, [row])
    assert manifest["count"] == 1 and len(parts) == 1
    assert feed.unpack(manifest, parts)[0] == row
    assert feed.unpack(manifest, parts)[0]["market_value_gbp_minor"] is None
    assert b"owner_id" not in parts[0] and b"store_price" not in parts[0]


@pytest.mark.parametrize("bad", [
    {"owner_id": "another founder"},
    {"market_value_gbp_minor": 0},
    {"image_r2_key": "drop-rate/private-media/unknown.webp"},
    {"source_url": "http://fake.example/art"},
    {"system_code": "YUGIOH"},
])
def test_figure_r2_rejects_private_invalid_or_cross_category_data(bad):
    with pytest.raises(ObjectStorageError):
        feed.pack("FUNKO_POP", 2, [_row(**bad)])


def test_manifest_rejects_missing_corrupt_duplicated_or_stale_parts():
    manifest, raw_parts = feed.pack("FUNKO_POP", 1, [_row()])
    with pytest.raises(ObjectStorageError):
        feed.unpack(manifest, [])
    with pytest.raises(ObjectStorageError):
        feed.unpack(manifest, [raw_parts[0] + b" "])
    bad = copy.deepcopy(manifest)
    bad["parts"].append(copy.deepcopy(bad["parts"][0]))
    with pytest.raises(ObjectStorageError):
        feed.validate_manifest(bad)
    with pytest.raises(ObjectStorageError):
        feed.pack("FUNKO_POP", 1, [_row(), _row()])


def test_empty_figure_r2_publication_has_no_spurious_objects():
    manifest, parts = feed.pack("COLLECTIBLE_FIGURES", 8, [])
    assert parts == []
    assert feed.unpack(manifest, parts) == ()


def test_expired_price_never_leaks_from_a_still_verified_r2_snapshot():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    item = feed._display_row(_row(market_value_gbp_minor=4000, expires_at=yesterday), None,
                             datetime.now(timezone.utc))
    assert item["market_value_gbp_minor"] is None and item["image_url"] is None
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    item = feed._display_row(_row(market_value_gbp_minor=4000, expires_at=tomorrow), None,
                             datetime.now(timezone.utc))
    assert item["market_value_gbp_minor"] == 4000


@pytest.mark.asyncio
async def test_r2_publication_verifies_actual_upload_and_download_before_commit():
    class FakeStorage:
        def __init__(self):
            self.payloads = {}

        def put_verified_reference_snapshot(self, payload):
            digest = feed._digest(payload)
            self.payloads[digest] = payload
            return {"sha256": digest, "verified": True}

        def read_verified_reference_snapshot(self, digest):
            return self.payloads[digest]

    conn = AsyncMock()
    conn.fetchrow.return_value = {"generation": 4, "published_generation": None}
    conn.fetch.return_value = [_row()]
    store = FakeStorage()
    manifest, parts = await feed.prepare_publication(conn, "FUNKO_POP")
    await feed.upload_publication(store, manifest, parts)
    assert manifest["count"] == 1 and len(store.payloads) == 1
    assert "owner_id" not in str(manifest)
    conn.execute.assert_not_called()  # No user/price/migration writes in publisher.

    store.read_verified_reference_snapshot = lambda digest: b"corrupt"
    with pytest.raises(ObjectStorageError):
        await feed.upload_publication(store, manifest, parts)


def test_ygo_requires_printing_code_and_quarantines_wrong_set_assignment():
    source = {"id": 46986414, "name": "Dark Magician", "card_images": [{"image_url": "https://images.ygoprodeck.com/example.jpg"}],
              "card_prices": [{"ebay_price": "0.99", "tcgplayer_price": "0.33"}],
              "card_sets": [{"set_name": "2016 Mega-Tins", "set_code": "CT13-EN003",
                             "set_rarity": "Ultra Rare", "set_rarity_code": "(UR)", "set_price": "6.97"},
                            {"set_name": "2017 Mega-Tins", "set_code": "CT14-EN001",
                             "set_rarity": "Secret Rare", "set_rarity_code": "(ScR)", "set_price": "9.66"}]}
    official = {"2016 Mega-Tins": {"set_code": "CT13", "tcg_date": "2016-09-01", "num_of_cards": 12},
                "2017 Mega-Tins": {"set_code": "CT14", "tcg_date": "2017-08-24", "num_of_cards": 8}}
    records = yugioh_printings(source, official_tcg_sets=official)
    assert len(records) == 2 and records[0][1]["provider_id"] != records[1][1]["provider_id"]
    assert records[0][0]["release_date"] == "2016-09-01"
    assert all(card["image_url"] is None for _, card in records)
    assert all("price" not in key for _, card in records for key in card)
    assert len(group_yugioh_printings([source, source], official_tcg_sets=official)) == 2

    source["card_sets"].append({"set_name": "2016 Mega-Tins", "set_code": "25TH-EN001",
                                "set_rarity": "Ultra Rare"})
    with pytest.raises(ReferenceSourceError, match="conflicts"):
        yugioh_printings(source, official_tcg_sets=official)


def test_sports_printing_keeps_player_manufacturer_parallel_and_print_run_distinct():
    base = dict(system_code="SPORT_SOCCER", source_url="https://uk.topps.com/pages/topps-chrome-premier-league",
                manufacturer="Topps", series="Chrome Premier League", year=2026,
                card_number="PL-101", athlete="Player Name", team="Team A", parallel="Base",
                print_run=None)
    _, card, details = sports_checklist_printing(base)
    assert details["manufacturer"] == "Topps" and details["parallel"] == "Base"
    assert details["athlete"] == "Player Name" and card["image_url"] is None
    _, parallel, _ = sports_checklist_printing({**base, "parallel": "Red /5", "print_run": 5})
    assert card["provider_id"] != parallel["provider_id"]
    with pytest.raises(ReferenceSourceError):
        sports_checklist_printing({**base, "source_url": "https://evil.example/topps"})
    with pytest.raises(ReferenceSourceError):
        sports_checklist_printing({**base, "parallel": ""})


def test_lorcana_uses_exact_print_id_and_never_borrows_foil_or_usd_prices():
    card = {"id": "crd_cbc18e77d7ec4d50bf19650a9a559686",
            "name": "Elsa", "version": "Spirit of Winter", "released_at": "2023-08-18",
            "collector_number": "207", "lang": "en", "rarity": "Enchanted",
            "set": {"id": "set_7ecb", "code": "1", "name": "The First Chapter"},
            "image_uris": {"digital": {"large": "https://cards.lorcast.io/example.avif"}},
            "prices": {"usd": "20.00", "usd_foil": "40.00"}}
    set_record, printing = lorcana_printing(card)
    assert set_record["system_code"] == "DISNEY_LORCANA"
    assert printing["provider_id"] == card["id"] and printing["finish"] is None
    assert printing["image_url"] is None and "prices" not in printing
    with pytest.raises(ReferenceSourceError):
        lorcana_printing({**card, "lang": "unknown"})


def test_funko_import_is_metadata_only_and_never_claims_image_rights():
    item = figure_product(dict(system_code="FUNKO_POP", manufacturer="Funko", provider_id="97402",
                               name="Pop! Yellow Lantern", figure_number="123", barcode_gtin="889698974027",
                               source_url="https://funko.com/gb/pop-yellow-lantern/97402.html",
                               reference_image_url="https://funko.com/images/example.jpg"))
    assert item["image_rights_status"] == "UNVERIFIED"
    assert item["image_r2_key"] is None and item["image_sha256"] is None
    with pytest.raises(ReferenceSourceError):
        figure_product({**item, "source_url": "https://fake-funko.example/item"})


def test_schema_is_additive_with_r2_generation_and_strict_rls():
    path = Path(__file__).parents[1] / "database/migrations/20261101205040_collectible_catalogue_expansion.sql"
    sql = path.read_text()
    assert "force row level security" in sql
    assert "generation = p.generation + 1" in sql
    assert "reference_figure_market_observations" in sql
    assert "grant select, insert on tcg.reference_figure_market_observations" in sql
    assert "drop table" not in sql.lower()
    assert "tcg.inventory_items" not in sql and "tcg.shopify_inventory_links" not in sql
