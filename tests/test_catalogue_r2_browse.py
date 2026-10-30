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



def test_extended_indexed_modes_are_bounded_and_printing_safe():
    from copy import deepcopy
    from uuid import UUID
    from app.catalogue_r2_browse import indexed_catalogue_query
    data=deepcopy(fixture())
    data["reference_sealed_products"].append(dict(
        provider="Bandai Official",system_code="ONE_PIECE_CARD_GAME",
        language="English",set_id="OP15",provider_id="sealed-pack",
        name="OP15 Sealed Pack",product_type="BOOSTER_PACK",
        image_url=None,source_url=None))
    idx=build_browse_index(data,today=date(2026,10,30))
    owner=UUID("10000000-0000-0000-0000-000000000001")

    for kind in ("COMIC","SEALED"):
        query,params=product_query(owner_id=owner,product_type=kind,limit=9)
        sql,args,mode=indexed_catalogue_query(query,params,idx)
        assert mode==kind
        assert "jsonb_to_recordset($5::jsonb)" in sql
        assert {r["product_type"] for r in json.loads(args[-1])}=={kind}
        assert len(json.loads(args[-1]))==1
        assert "tcg.inventory_items" in sql
        assert "tcg.reference_catalogue_prices" in sql

    query,params=product_query(owner_id=owner,owned="owned",limit=9)
    owner_facts={"10000000-0000-0000-0000-000000000001":(1,400,0)}
    sql,args,mode=indexed_catalogue_query(query,params,idx,owned=owner_facts)
    assert mode=="OWNED"
    owned_rows=json.loads(args[-1])
    assert len(owned_rows)==1
    assert owned_rows[0]["provider_id"]=="OP15-001"
    # Owning the standard printing must never grant its parallel.
    assert owned_rows[0]["provider_id"]!="OP15-001_p1"
    assert all("owner_id" not in row and "market_value_minor" not in row
               for row in owned_rows)

    query,params=product_query(owner_id=owner,q="Krieg",limit=9)
    sql,args,mode=indexed_catalogue_query(query,params,idx)
    assert mode=="SEARCH_TEXT"
    matches=json.loads(args[-1])
    assert {r["provider_id"] for r in matches}=={
        "OP15-001","OP15-001_p1"}
    assert "tcg.reference_market_prices" in sql
    assert len(args)==len(params)+1


def test_extended_search_rejects_ambiguous_or_unbounded_work():
    from uuid import UUID
    from app.catalogue_r2_browse import indexed_catalogue_query
    idx=build_browse_index(fixture(),today=date(2026,10,30))
    owner=UUID("10000000-0000-0000-0000-000000000001")
    query,params=product_query(owner_id=owner,q="Krieg",limit=9)
    with pytest.raises(ValueError):
        indexed_catalogue_query(query,params,idx,max_candidates=1)
    for options in (
        dict(q="OP15-001"),dict(q="クリエグ"),
        dict(q="Krieg",owned="owned"),
        dict(q="Krieg",system_code="ONE_PIECE_CARD_GAME"),
        dict(product_type="CARD"),dict(sort="value_asc"),
        dict(owned="not_owned"),dict(owned="owned",offset=1000),
    ):
        query,params=product_query(owner_id=owner,limit=9,**options)
        with pytest.raises(ValueError):
            indexed_catalogue_query(query,params,idx,owned={})


def test_extended_live_reader_does_not_enable_itself_by_default(monkeypatch):
    from app import catalogue_r2_live as live
    monkeypatch.delenv("TCG_R2_LIVE_CATALOGUE_EXTENDED_BROWSE_ENABLED",raising=False)
    assert live.extended_browse_enabled() is False
    monkeypatch.setenv("TCG_R2_LIVE_CATALOGUE_EXTENDED_BROWSE_ENABLED","true")
    assert live.extended_browse_enabled() is True


def test_value_ordering_keeps_unpaged_population_and_live_price_owner_predicates():
    from uuid import UUID
    from app.catalogue_r2_browse import indexed_value_sql, _STATIC_COLUMNS
    idx=build_browse_index(fixture(),today=date(2026,10,30))
    owner=UUID('10000000-0000-0000-0000-000000000001')
    for direction in ('value_asc','value_desc'):
        query,params=product_query(owner_id=owner,sort=direction,limit=1,
                                  owned='owned',language='English')
        sql,args=indexed_value_sql(query,params,idx)
        assert len(args[len(params)])==len(idx.entries)>2
        provider_ids=args[len(params)+[name for name,_ in _STATIC_COLUMNS].index('provider_id')]
        assert 'OP15-001' in provider_ids and 'OP15-001_p1' in provider_ids
        assert 'tcg.reference_cards' not in sql
        assert 'tcg.reference_market_prices' in sql
        assert 'tcg.catalogue_reference_value_v2' in sql
        assert 'coalesce(o.quantity,0)>0' in sql
        assert 'e.language=$2' in sql
        assert 'tcg.reference_image_mirrors' in sql
        assert args[:len(params)]==params
