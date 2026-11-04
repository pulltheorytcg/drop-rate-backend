"""Grouped R2 search remains bounded, immutable and owner scoped.

Fixtures exercise real disposable SQLite indexes and local object bytes only.
No provider, production SQL, inventory mutation or catalogue publication.
"""
from datetime import date

from fastapi import HTTPException
import pytest

from app import r2_first_catalogue as codec
from app import r2_first_service as service
from test_r2_first_service import (
    Connection, OWNER_A, OWNER_B, cache, clean_runtime, owned_link, row, snapshots,
)


def sports(number, maker, **changes):
    return row(str(number), name=f"Player {number:04}", set_id="shared-set",
               set_name="Shared Checklist", card_number=str(number),
               details={"manufacturer": maker, "sport": "Baseball"}, **changes)


@pytest.mark.asyncio
async def test_group_filter_precedes_count_paging_keys_and_release_filter(snapshots):
    rows = [sports(n, "Topps" if n % 2 else "Panini") for n in range(260)]
    rows += [sports(300, "Unreviewed maker"), sports(301, "Topps", release_date="2099-01-01")]
    snapshot = await snapshots(rows, system_code="SPORTS_CARDS")
    page = snapshot.search(browse_group="TOPPS", limit=40, offset=100, today=date(2026, 11, 4))
    assert page["total"] == 130
    assert [item["card_number"] for item in page["items"]] == [str(n) for n in range(201, 260, 2)]
    assert all(item["details"]["manufacturer"] == "Topps" for item in page["items"])
    keys = [codec.stable_key(snapshot.provider, snapshot.system_code, snapshot.language, str(n)) for n in (0, 1, 3)]
    assert [item["card_number"] for item in snapshot.search(browse_group="TOPPS", keys=keys)["items"]] == ["1", "3"]
    assert snapshot.search(browse_group="TOPPS", keys=keys, exclude_keys=[keys[1]])["items"][0]["card_number"] == "3"
    assert snapshot.search(browse_group="OTHER")["total"] == 1
    assert snapshot.search(browse_group="TOPPS", include_upcoming=True)["total"] == 131
    assert snapshot.search()["total"] == 261
    # Derived index data does not enter immutable payloads or change identity.
    stored = snapshot.get(keys[1])
    assert "browse_group" not in stored and stored["provider_id"] == "1"


@pytest.mark.asyncio
async def test_cross_partition_merge_passes_group_to_every_hundred_row_fetch(snapshots):
    first = await snapshots([sports(n, "Topps" if n % 2 else "Panini") for n in range(260)],
                            provider="fixture_one", system_code="SPORTS_CARDS")
    second = await snapshots([sports(n, "Topps" if n % 2 else "Panini") for n in range(260, 520)],
                             provider="fixture_two", system_code="SPORTS_CARDS")
    reads = len(snapshots.store.reads)
    page = service._merge_page([first, second], q="", set_id="", product_type="CARD",
        keys=None, exclude_keys=None, sort="name", limit=100, offset=117, browse_group="TOPPS")
    assert page["total_count"] == 260 and page["has_more"] is True
    assert [int(item["card_number"]) for item in page["items"]] == list(range(235, 435, 2))
    assert all(item["browse_group"] == "TOPPS" for item in page["items"])
    assert len(snapshots.store.reads) == reads, "Browsing must not fetch source files again"
    assert all(item["market_value_minor"] is None for item in page["items"])


@pytest.mark.asyncio
async def test_owned_and_not_owned_groups_never_include_another_owners_keys(snapshots):
    snapshot = await snapshots([sports(1, "Topps"), sports(2, "Panini"), sports(3, "Topps")],
                               system_code="SPORTS_CARDS")
    connection = Connection([cache(snapshot)])
    keys = {item["card_number"]: item["key"] for item in snapshot.search()["items"]}
    connection.owner_links[OWNER_A] = [owned_link(keys["1"], 2), owned_link(keys["2"], 1)]
    connection.owner_links[OWNER_B] = [owned_link(keys["3"], 4)]
    owned = await service.browse(connection, owner_id=OWNER_A, system_code="SPORTS_CARDS",
                                 category="SPORTS", browse_group="TOPPS", owned="owned")
    assert [item["key"] for item in owned["items"]] == [keys["1"]]
    assert owned["items"][0]["owned_quantity"] == 2
    other = await service.browse(connection, owner_id=OWNER_A, system_code="SPORTS_CARDS",
                                 category="SPORTS", browse_group="TOPPS", owned="not_owned")
    assert [item["key"] for item in other["items"]] == [keys["3"]]
    assert other["items"][0]["owned_quantity"] == 0
    saved = await service.browse(connection, owner_id=OWNER_A, system_code="SPORTS_CARDS",
        category="SPORTS", browse_group="TOPPS", keys=[keys["2"], keys["3"]])
    assert [item["key"] for item in saved["items"]] == [keys["3"]]


@pytest.mark.asyncio
async def test_set_group_counts_and_owner_totals_do_not_mix_manufacturers(snapshots):
    snapshot = await snapshots([sports(1, "Topps"), sports(2, "Panini"), sports(3, "Topps")],
                               system_code="SPORTS_CARDS")
    connection = Connection([cache(snapshot)])
    keys = {item["card_number"]: item["key"] for item in snapshot.search()["items"]}
    connection.owner_links[OWNER_A] = [owned_link(keys["1"], 1, 250), owned_link(keys["2"], 1, 900)]
    assert snapshot.sets(browse_group="TOPPS")[0]["count"] == 2
    page = await service.sets(connection, owner_id=OWNER_A, system_code="SPORTS_CARDS", browse_group="TOPPS")
    assert page["total_count"] == 1
    result = page["items"][0]
    assert result["card_count"] == 2 and result["owned_count"] == 1
    assert result["owned_value_minor"] == 250


@pytest.mark.asyncio
async def test_figures_classify_exact_funko_pop_not_arbitrary_makers_or_unknowns(snapshots):
    rows = [row("pop", product_type="FIGURE", details={"manufacturer": "Funko", "product_line": "Pop!"}),
            row("figure", product_type="FIGURE", details={"manufacturer": "Good Smile Company", "product_line": "Nendoroid"}),
            row("unknown", product_type="FIGURE", details={"franchise": "Unknown"})]
    snapshot = await snapshots(rows, provider="reviewed_figures", system_code="FIGURES")
    assert [item["provider_id"] for item in snapshot.search(browse_group="FUNKO_POP")["items"]] == ["pop"]
    assert [item["provider_id"] for item in snapshot.search(browse_group="FIGURINES")["items"]] == ["figure"]
    assert [item["provider_id"] for item in snapshot.search(browse_group="OTHER")["items"]] == ["unknown"]


@pytest.mark.asyncio
@pytest.mark.parametrize("group", ["MARVEL", "SHONEN", "TOPPS' OR 1=1 --", "TOPPS ", None, ["TOPPS"]])
async def test_invalid_or_cross_category_groups_fail_before_database_or_object_reads(snapshots, group):
    connection = Connection()
    with pytest.raises(HTTPException) as rejected:
        await service.browse(connection, owner_id=OWNER_A, category="SPORTS", system_code="SPORTS_CARDS", browse_group=group)
    assert rejected.value.status_code == 422
    assert connection.calls == [] and snapshots.store.reads == []


@pytest.mark.asyncio
async def test_tcg_cannot_borrow_a_sports_group_and_default_search_is_unchanged(snapshots):
    snapshot = await snapshots()
    assert snapshot.search()["total"] == 1
    with pytest.raises(codec.R2FirstCatalogueError):
        snapshot.search(browse_group="TOPPS")
    with pytest.raises(codec.R2FirstCatalogueError):
        snapshot.sets(browse_group="TOPPS")
