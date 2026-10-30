"""Global default browse selects shared R2 page in Railway, never its owner prices."""
from datetime import date
import json

import pytest

from app.catalogue_r2_browse import build_browse_index, indexed_browse_sql
from app.catalogue_browser import product_query
from app.recognition_games import SYSTEM_BY_GAME


def fixture():
    return dict(
        reference_sets=[
            dict(provider="Bandai Official",system_code="ONE_PIECE_CARD_GAME",
                 language="English",set_id="OP15",name="OP15",release_date="2026-03-01"),
            dict(provider="Bandai Official",system_code="ONE_PIECE_CARD_GAME",
                 language="English",set_id="OP99",name="Future",release_date="2027-01-01"),
        ],
        reference_cards=[
            dict(provider="Bandai Official",system_code="ONE_PIECE_CARD_GAME",
                 language="English",set_id="OP15",provider_id="OP15-001",
                 name="Krieg",card_number="OP15-001",rarity="C",
                 image_url="https://publisher.invalid/base",source_url="https://publisher.invalid/a"),
            dict(provider="Bandai Official",system_code="ONE_PIECE_CARD_GAME",
                 language="English",set_id="OP15",provider_id="OP15-001_p1",
                 name="Krieg",card_number="OP15-001",rarity="C",
                 image_url="https://publisher.invalid/alt",source_url="https://publisher.invalid/b"),
            dict(provider="Bandai Official",system_code="ONE_PIECE_CARD_GAME",
                 language="English",set_id="OP99",provider_id="OP99-001",
                 name="Future",card_number="OP99-001",rarity="SEC",
                 image_url="https://publisher.invalid/future",source_url="https://publisher.invalid/c"),
        ],
        reference_sealed_products=[],
        catalogue_products=[
            dict(id="10000000-0000-0000-0000-000000000001",
                 product_type="CARD",game="One Piece",name="Krieg",
                 set_name="OP15",card_number="OP15-001",variant="OP15-001",
                 rarity="C",language="English"),
            dict(id="10000000-0000-0000-0000-000000000002",
                 product_type="COMIC",game="Manga",name="Volume 1",
                 set_name="Manga Series",card_number="1",variant="First",
                 rarity="Standard",language="English"),
        ],
        catalogue_product_profiles=[
            dict(catalogue_id="10000000-0000-0000-0000-000000000001",
                 collectible_type="CARD",system_code="ONE_PIECE_CARD_GAME",
                 set_code="OP15",release_date="2026-03-01"),
            dict(catalogue_id="10000000-0000-0000-0000-000000000002",
                 collectible_type="COMIC",system_code="MANGA",
                 set_code="manga-1",release_date="2026-02-01"),
        ],
    )


def test_default_global_browse_is_exact_printing_ordered_and_skips_reprint_alias():
    idx=build_browse_index(fixture(),today=date(2026,10,30))
    cards=[entry for entry in idx.entries if entry["source_kind"]=="REFERENCE"]
    assert len(cards)==2
    assert {r["provider_id"] for r in cards}=={"OP15-001","OP15-001_p1"}
    assert {r["image_url"] for r in cards}=={
        "https://publisher.invalid/base","https://publisher.invalid/alt"}
    assert not any(r["source_kind"]=="CATALOGUE"
                   and r["catalogue_id"]=="10000000-0000-0000-0000-000000000001"
                   for r in idx.entries)
    assert idx.entries[-1]["product_type"]=="COMIC"
    assert all(r["set_id"]!="OP99" for r in idx.entries)


def test_indexed_sql_only_transfers_a_bounded_page_and_no_private_data():
    idx=build_browse_index(fixture(),today=date(2026,10,30))
    from uuid import UUID
    query,params=product_query(owner_id=UUID("10000000-0000-0000-0000-000000000001"),limit=9)
    sql,args=indexed_browse_sql(query,params,idx)
    assert "jsonb_to_recordset($4::jsonb)" in sql
    assert "tcg.reference_market_prices" in sql
    assert "tcg.inventory_items" in sql
    assert "catalogue_reference_value_v2" in sql
    assert "reference_image_mirrors" in sql
    assert args[:3]==params
    values=json.loads(args[3])
    assert len(values)==len(idx.entries)
    assert all("owner_id" not in v and "store_price_minor" not in v
               and "market_value_minor" not in v for v in values)


def test_unknown_query_shapes_and_oversized_offsets_fallback():
    from uuid import UUID
    owner=UUID("10000000-0000-0000-0000-000000000001")
    idx=build_browse_index(fixture(),today=date(2026,10,30))
    for opts in (
        dict(q="Krieg"),dict(owned="owned"),dict(sort="value_desc"),
        dict(system_code="ONE_PIECE_CARD_GAME"),dict(set_id="OP15"),
        dict(provider="Bandai Official"),dict(language="Japanese"),
        dict(product_type="CARD"),dict(offset=1000),
    ):
        query,params=product_query(owner_id=owner,limit=9,**opts)
        with pytest.raises(ValueError):
            indexed_browse_sql(query,params,idx)
