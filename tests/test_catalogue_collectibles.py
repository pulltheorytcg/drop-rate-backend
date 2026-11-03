import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.catalogue_collectibles import MAX_PAGE_REFERENCES, with_collectible_details


SPORT = dict(sport="Basketball", release_year=2024, manufacturer="Fixture Cards", set_name="Fixture Set",
             subject_name="Fixture Player", card_number="23", parallel="Blue", league="NBA", print_run=99)
FIGURE = dict(manufacturer="Fixture Maker", franchise="Fixture World", character="Fixture Character",
              product_line="Fixture Line", edition="First edition", scale="1:6", barcode_gtin="1234567890123")


def reference(system="SPORTS_CARDS", kind="CARD"):
    return dict(catalogue_id=uuid4(), system_code=system, product_type=kind, name="Public title")


def record(item, fields, **changes):
    return {"catalogue_id": item["catalogue_id"], "system_code": item["system_code"],
            "collectible_type": item["product_type"], "identity_status": "VERIFIED",
            "sports_card" if item["product_type"] == "CARD" else "figure_details": fields, **changes}


@pytest.mark.asyncio
async def test_legacy_and_unresolved_pages_do_not_lookup_collectible_metadata():
    rows = [reference("POKEMON_TCG"), reference("MANGA", "COMIC"),
            {**reference("FIGURES", "FIGURE"), "catalogue_id": None},
            {**reference(), "catalogue_id": "r:not-a-canonical-id"}]
    db = SimpleNamespace(fetch=AsyncMock())
    assert await with_collectible_details(db, rows) == rows
    db.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_page_is_batched_deduplicated_and_only_typed_facts_are_returned():
    sport, figure = reference(), reference("FIGURES", "FIGURE")
    private = {"submitted_by_user_id": str(uuid4()), "owner_id": str(uuid4()), "source_url": "https://private.invalid", "market_value_minor": 9999}
    rows = [sport, figure, deepcopy(sport)]
    db = SimpleNamespace(fetch=AsyncMock(return_value=[record(sport, {**SPORT, **private}, **private),
        record(figure, json.dumps({**FIGURE, **private}), **private)]))
    result = await with_collectible_details(db, rows)
    db.fetch.assert_awaited_once()
    sql, ids = db.fetch.call_args.args
    assert set(ids) == {sport["catalogue_id"], figure["catalogue_id"]}
    assert "pr.identity_status='VERIFIED'" in sql
    assert "pr.attributes->'sports_card'" in sql and "pr.attributes->'figure_details'" in sql
    assert "pr.attributes as" not in sql and "pr.*" not in sql
    assert result[0]["sports_card"]["sport"] == "Basketball"
    assert result[0]["sports_card"]["print_run"] == 99
    assert result[1]["figure_details"]["franchise"] == "Fixture World"
    assert result[0]["sports_card"] == result[2]["sports_card"]
    for item in result:
        for key in private:
            assert key not in item and key not in item.get("sports_card", {}) and key not in item.get("figure_details", {})
    assert all("sports_card" not in item and "figure_details" not in item for item in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [dict(identity_status="NEEDS_REVIEW"), dict(identity_status="STRUCTURED"),
    dict(system_code="POKEMON_TCG"), dict(collectible_type="FIGURE")])
async def test_unreviewed_or_mismatched_records_are_not_hydrated(change):
    item = reference()
    item["sports_card"] = {"submitted_by_user_id": "must-be-removed"}
    db = SimpleNamespace(fetch=AsyncMock(return_value=[record(item, SPORT, **change)]))
    result = await with_collectible_details(db, [item])
    assert "sports_card" not in result[0] and "figure_details" not in result[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [None, "not-json", [], {}, {**SPORT, "release_year": "2024"},
    {**SPORT, "system_code": "POKEMON_TCG"}, {**SPORT, "parallel": ""}])
async def test_malformed_or_incomplete_typed_metadata_is_not_invented(fields):
    item = reference()
    db = SimpleNamespace(fetch=AsyncMock(return_value=[record(item, fields)]))
    assert "sports_card" not in (await with_collectible_details(db, [item]))[0]


@pytest.mark.asyncio
async def test_page_bound_is_enforced_before_a_database_read():
    db = SimpleNamespace(fetch=AsyncMock())
    with pytest.raises(ValueError, match="bounded"):
        await with_collectible_details(db, [reference() for _ in range(MAX_PAGE_REFERENCES + 1)])
    db.fetch.assert_not_called()
