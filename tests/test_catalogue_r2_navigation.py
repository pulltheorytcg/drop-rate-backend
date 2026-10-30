"""Indexed R2 navigation preserves printings, owners and release boundaries."""
from datetime import date

from app.catalogue_r2_navigation import build_navigation


def fixture():
    s=[dict(provider="Punk Records",system_code="ONE_PIECE_CARD_GAME",language="English",
            set_id="s15",name="OP15 Set",release_date="2026-09-10",declared_card_count=4),
       dict(provider="Punk Records",system_code="ONE_PIECE_CARD_GAME",language="English",
            set_id="future",name="Future Set",release_date="2026-12-01",declared_card_count=2)]
    cards=[
        dict(provider="Punk Records",system_code="ONE_PIECE_CARD_GAME",language="English",
             provider_id="OP15-001",set_id="s15",name="Krieg",card_number="OP15-001",rarity="C"),
        dict(provider="Punk Records",system_code="ONE_PIECE_CARD_GAME",language="English",
             provider_id="OP15-001_p1",set_id="s15",name="Krieg",card_number="OP15-001",rarity="C"),
        dict(provider="Punk Records",system_code="ONE_PIECE_CARD_GAME",language="English",
             provider_id="FUT-001",set_id="future",name="Future",card_number="OP99-001",rarity="SR"),
    ]
    return dict(reference_sets=s,reference_cards=cards,
      reference_sealed_products=[
        dict(provider="Punk Records",system_code="ONE_PIECE_CARD_GAME",
             language="English",set_id="s15",provider_id="pack")],
      catalogue_products=[
        dict(id="card-uuid",product_type="CARD",game="One Piece",name="Krieg",
             set_name="OP15 Set",card_number="OP15-001",variant="OP15-001",
             rarity="C",language="English"),
        dict(id="book-uuid",product_type="COMIC",game="Manga",name="Volume 1",
             set_name="Book Series",card_number="1",variant="First",
             rarity="Standard",language="English"),
      ],
      catalogue_product_profiles=[
        dict(catalogue_id="card-uuid",system_code="ONE_PIECE_CARD_GAME",
             collectible_type="CARD",set_code="s15",release_date="2026-09-10"),
        dict(catalogue_id="book-uuid",system_code="MANGA",
             collectible_type="COMIC",set_code="books",release_date="2026-01-01"),
      ])


def test_games_count_each_artwork_separately_and_do_not_duplicate_linked_canon():
    nav=build_navigation(fixture(),today=date(2026,10,30))
    games={r["system_code"]:r for r in nav.games()}
    assert games["ONE_PIECE_CARD_GAME"]["products"]==3
    assert games["ONE_PIECE_CARD_GAME"]["sets"]==1
    assert games["ONE_PIECE_CARD_GAME"]["languages"]==["English"]
    assert games["MANGA"]["products"]==1
    assert games["MANGA"]["sets"]==1
    assert len(nav.set_templates)==2


def test_owner_aggregates_are_scoped_to_exact_catalogue_link_not_parallel():
    nav=build_navigation(fixture(),today=date(2026,10,30))
    owner={"card-uuid":(2,600,1),"book-uuid":(1,1200,0)}
    page=nav.sets(systems=["ONE_PIECE_CARD_GAME"],owner=owner)
    assert len(page)==1
    row=page[0]
    assert row["indexed_count"]==3  # standard, parallel, sealed
    assert row["card_count"]==4
    assert row["checklist_status"]=="PARTIAL"
    assert row["owned_count"]==1  # parallel NEVER inherits a base owner's copy
    assert row["owned_value_minor"]==600
    assert row["unknown_values"]==1
    assert row["total_count"]==1
    assert nav.sets(systems=["MANGA"],owner=owner)[0]["owned_value_minor"]==1200


def test_future_set_is_clock_driven_without_r2_snapshot_rewrite():
    shared=fixture()
    old=build_navigation(shared,today=date(2026,10,30))
    assert old.sets(systems=["ONE_PIECE_CARD_GAME"])[0]["total_count"]==1
    new=build_navigation(shared,today=date(2026,12,2))
    assert len(new.sets(systems=["ONE_PIECE_CARD_GAME"]))==2
    assert {r["indexed_count"] for r in new.sets(systems=["ONE_PIECE_CARD_GAME"])}=={1,3}


def test_human_mapping_to_unreleased_reference_does_not_hide_canonical():
    shared=fixture()
    verified=[dict(source_provider="Punk Records",system_code="ONE_PIECE_CARD_GAME",
                   provider_language="English",provider_id="FUT-001",
                   catalogue_id="card-uuid",provider_entity_type="CARD_PRINTING",
                   provider_variant_key="",match_status="VERIFIED")]
    nav=build_navigation(shared,today=date(2026,10,30),verified_mappings=verified)
    assert nav.games()[0]["products"]>=1
    # Unreleased reference cannot suppress the OP15 physical canonical.
    assert nav.sets(systems=["ONE_PIECE_CARD_GAME"])[0]["indexed_count"]==3


def test_page_filter_and_bounds():
    nav=build_navigation(fixture(),today=date(2026,12,2))
    items=nav.sets(systems=["ONE_PIECE_CARD_GAME"],search="Future",limit=2)
    assert len(items)==1 and items[0]["set_id"]=="future"
    assert len(nav.sets(systems=["ONE_PIECE_CARD_GAME"],offset=1,limit=1))==1
    assert nav.sets(systems=["DRAGON_BALL_SUPER_MASTERS"])==[]
    for invalid in (0,82):
        try:
            nav.sets(systems=["ONE_PIECE_CARD_GAME"],limit=invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Unbounded navigation request accepted")
