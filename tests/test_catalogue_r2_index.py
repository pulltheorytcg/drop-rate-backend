"""R2's scoped input population is indexed in Railway, never copied to SQL for filtering."""
from dataclasses import replace
import hashlib
import json

from app.catalogue_r2_index import SharedReferenceIndex
from app import catalogue_r2_live as r2


def row(table, system, set_id, provider_id, language="English", provider="Bandai Official"):
    value={key:None for key,_ in r2.RELATIONS[table]}
    value.update(provider=provider,system_code=system,language=language,
                 set_id=set_id)
    if "provider_id" in value:
        value["provider_id"]=provider_id
    if "name" in value:
        value["name"]=provider_id
    return value


def fixture_rows():
    return {
        "reference_cards":[
            row("reference_cards","ONE_PIECE_CARD_GAME","OP15","OP15-001"),
            row("reference_cards","ONE_PIECE_CARD_GAME","OP15","OP15-001_p1"),
            row("reference_cards","ONE_PIECE_CARD_GAME","OP16","OP16-001"),
            row("reference_cards","ONE_PIECE_CARD_GAME","OP15","OP15-001",language="Japanese"),
            row("reference_cards","DRAGON_BALL_SUPER_MASTERS","BT1","BT1-001"),
        ],
        "reference_sets":[
            row("reference_sets","ONE_PIECE_CARD_GAME","OP15","unused"),
            row("reference_sets","ONE_PIECE_CARD_GAME","OP16","unused"),
            row("reference_sets","DRAGON_BALL_SUPER_MASTERS","BT1","unused"),
        ],
        "reference_sealed_products":[
            row("reference_sealed_products","ONE_PIECE_CARD_GAME","OP15","pack-001"),
            row("reference_sealed_products","DRAGON_BALL_SUPER_MASTERS","BT1","pack-bt"),
        ],
        "catalogue_products":[
            {key:None for key,_ in r2.RELATIONS["catalogue_products"]}
        ],
        "catalogue_product_profiles":[
            {key:None for key,_ in r2.RELATIONS["catalogue_product_profiles"]}
        ],
    }


def old_filter(rows, *, systems=None, language="", provider=None, set_id=""):
    return [x for x in rows if (not systems or x["system_code"] in systems)
            and (not language or x["language"] == language)
            and (provider is None or x["provider"] == provider)
            and (not set_id or x["set_id"] == set_id)]


def test_scope_index_exactly_matches_legacy_reference_population():
    rows=fixture_rows()
    index=SharedReferenceIndex.build(rows)
    for table in ("reference_cards","reference_sets","reference_sealed_products"):
        for options in (
            {},
            {"systems":["ONE_PIECE_CARD_GAME"]},
            {"systems":["ONE_PIECE_CARD_GAME","DRAGON_BALL_SUPER_MASTERS"]},
            {"systems":["ONE_PIECE_CARD_GAME"],"language":"English"},
            {"systems":["ONE_PIECE_CARD_GAME"],"language":"English",
             "provider":"Bandai Official","set_id":"OP15"},
            {"systems":["ONE_PIECE_CARD_GAME"],"language":"Japanese",
             "provider":"Bandai Official","set_id":"OP15"},
            {"systems":["ONE_PIECE_CARD_GAME"],"language":"English",
             "provider":"Wrong publisher","set_id":"OP15"},
            {"systems":["UNKNOWN"],"language":"English",
             "provider":"Bandai Official","set_id":"OP15"},
        ):
            actual=index.select(table,rows[table],**options)
            expected=old_filter(rows[table],**options)
            assert {json.dumps(x,sort_keys=True) for x in actual} == {
                json.dumps(x,sort_keys=True) for x in expected
            }, (table,options)
    variants=index.select("reference_cards",rows["reference_cards"],
        systems=["ONE_PIECE_CARD_GAME"],language="English",
        provider="Bandai Official",set_id="OP15")
    assert {r["provider_id"] for r in variants} == {"OP15-001","OP15-001_p1"}


def test_exact_scope_uses_index_without_scanning_original_collection():
    rows=fixture_rows()
    index=SharedReferenceIndex.build(rows)
    class ForbiddenScan(list):
        def __iter__(self):
            raise AssertionError("Exact-scope lookup scanned the complete catalogue")
    actual=index.select("reference_cards",ForbiddenScan(rows["reference_cards"]),
        systems=["ONE_PIECE_CARD_GAME"],provider="Bandai Official",
        language="English",set_id="OP15")
    assert len(actual)==2


def test_sql_uses_index_but_does_not_narrow_canonical_product_population():
    rows=fixture_rows()
    # Production assemble() validates the R2 manifest and builds this index;
    # direct construction here inspects the SQL parameter shapes.
    snap=r2.LiveCatalogue(1,"digest",rows,SharedReferenceIndex.build(rows))
    query="\nwith reference_base as not materialized (select * from tcg.reference_cards r) select * from reference_base"
    sql,params=snap.sql(query,["owner"],
        systems=["ONE_PIECE_CARD_GAME"],language="English",
        provider="Bandai Official",set_id="OP15")
    assert "live_r2_reference_cards" in sql
    assert "live_r2_catalogue_products" in sql
    assert params[1]==["Bandai Official","Bandai Official"]
    assert params[4]==["OP15-001","OP15-001_p1"]
    offset=1+len(r2.RELATIONS["reference_cards"])
    assert params[offset+1]==["Bandai Official"]
    assert params[offset+len(r2.RELATIONS["reference_sets"]) + 1]==["Bandai Official"]
    canonical_offset=1+sum(len(r2.RELATIONS[t]) for t in
        ("reference_cards","reference_sets","reference_sealed_products"))
    assert params[canonical_offset+1]==[None]


def test_canonical_rows_are_always_complete_for_exact_link_suppression():
    rows=fixture_rows()
    index=SharedReferenceIndex.build(rows)
    result=index.select("catalogue_products",rows["catalogue_products"],
        systems=["UNKNOWN"],language="Japanese",provider="Nobody",set_id="missing")
    assert result is rows["catalogue_products"]
