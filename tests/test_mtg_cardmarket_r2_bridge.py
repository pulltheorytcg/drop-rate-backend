from copy import deepcopy
from uuid import UUID

import pytest

from app import mtg_cardmarket_r2_bridge as bridge
from app import r2_first_catalogue as codec


UID = "11111111-1111-5111-8111-111111111111"


def row(uid=UID, finish="nonfoil", external="12345", **updates):
    item = {
        "provider": "mtgjson", "system_code": "MAGIC_THE_GATHERING",
        "language": "English", "provider_id": f"mtgjson:{uid}:{finish}",
        "product_type": "CARD", "name": "Test Card", "set_name": "Example Edition",
        "set_id": "ABC", "card_number": "009", "rarity": "Common",
        "finish": finish, "release_date": "2026-01-02",
        "source_url": "https://mtgjson.com/api/v5/AllPrintings.json.xz",
        "details": {"cardmarket_product_id": external} if external is not None else {},
    }
    item.update(updates)
    return item


def test_exact_r2_uuid_and_finish_grouping_retains_only_source_identity():
    rows = [row(), row(finish="foil")]
    original = deepcopy(rows)
    result = bridge.cards_from_verified_r2(rows)
    assert result["input_rows"] == 2
    assert result["exact_mcm_groups"] == 1
    assert result["quarantined_uuid_groups"] == 0
    assert result["cards"][0]["identifiers"] == {"mcmId":"12345"}
    assert result["cards"][0]["finishes"] == ["foil","nonfoil"]
    assert result["status"] == "IDENTITY_ONLY_NO_PRICE_PUBLICATION"
    assert result["verified_sold_values"] == result["database_writes"] == result["r2_writes"] == 0
    assert (rows == original)


@pytest.mark.parametrize("change", [
 {"name":"Other Card"}, {"set_name":"Other Edition"},
 {"details":{"cardmarket_product_id":"22222"}}, {"finish":"nonfoil"},
])
def test_conflicting_duplicate_uuid_is_quarantined_not_selected(change):
    first = row()
    second = row(finish="foil")
    second.update(change)
    # A finish mutation also updates provider_id, preserving an internally consistent row.
    if "finish" in change:
        second["provider_id"] = f"mtgjson:{UID}:nonfoil"
    result = bridge.cards_from_verified_r2([first,second])
    assert result["exact_mcm_groups"] == 0
    assert result["quarantined_uuid_groups"] == 1


@pytest.mark.parametrize("external", [None, "", "0", "abc", "01", "1.2", "-1", 1234, True, "99999999999"])
def test_invalid_cardmarket_id_never_inferred(external):
    result = bridge.cards_from_verified_r2([row(external=external)])
    assert result["exact_mcm_groups"] == 0
    assert result["missing_external_id_rows"] == 1


def test_wrong_scope_invalid_uuid_or_wrong_finish_fails_closed():
    with pytest.raises(bridge.IdentityBridgeError):
        bridge.cards_from_verified_r2([row(provider="ygoprodeck")])
    with pytest.raises(bridge.IdentityBridgeError):
        bridge.cards_from_verified_r2([row(provider_id="mtgjson:bad:foil")])
    with pytest.raises(bridge.IdentityBridgeError):
        bridge.cards_from_verified_r2([row(language="Japanese")])


def test_independent_uuid_groups_remain_distinct_with_equal_card_names():
    other = str(UUID(int=2))
    result=bridge.cards_from_verified_r2([row(),row(uid=other, external="54321")])
    assert result["exact_mcm_groups"] == 2
    assert {c["identifiers"]["mcmId"] for c in result["cards"]} == {"12345","54321"}


def test_size_guard_no_truncation(monkeypatch):
    monkeypatch.setattr(bridge, "MAX_ROWS", 1)
    with pytest.raises(bridge.IdentityBridgeError, match="bounded"):
        bridge.cards_from_verified_r2([row(),row(finish="foil")])


def test_verified_snapshot_pages_all_records_without_price_or_db_io():
    rows = [row(),row(finish="foil")]
    prepared=codec.prepare_catalogue(rows,provider="mtgjson",system_code="MAGIC_THE_GATHERING",
        language="English",source_url="https://mtgjson.com/api/v5/AllPrintings.json.xz",
        source_revision="fixture",permission_ref="https://mtgjson.com/license/")
    # _append/_finish is the existing verified manifest parser's in-memory route.
    snapshot=codec.Snapshot(prepared.manifest)
    try:
        for ix,raw in enumerate(prepared.parts):
            part=prepared.manifest["parts"][ix]
            snapshot._append(codec._parse_part(raw,part,("mtgjson","MAGIC_THE_GATHERING","English")))
        snapshot._finish()
        result=bridge.cards_from_snapshot(snapshot)
        assert result["input_rows"] == 2
        assert result["exact_mcm_groups"] == 1
    finally:
        snapshot.close()

