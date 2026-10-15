"""Only genuine exact-SKU Naruto sealed references can be created."""
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

import pytest

from app import verified_kayou_sealed as kayou
from app import catalogue_browser as browser


def test_source_manifest_records_four_real_distinct_publisher_skus():
    items = kayou.candidate_manifest()
    assert len(items) == 4
    expected = {
        "NR-RDIV-Z001-NA": ("BOOSTER_BOX", 24, 8, "2025-09"),
        "NR-KP-DZJ-002A-NA": ("BOOSTER_BOX", 20, 7, "2026-03"),
        "NR-KP-CC-ZZZ-003A-NA": ("BOOSTER_BOX", 12, 8, "2026-04"),
        "NR-KP-RZSD-LH-001-NA": ("COLLECTION", 16, 5, "2026-08"),
    }
    for release, item in items:
        assert item["provider"] == "Kayou Official"
        assert release["provider"] == item["provider"]
        assert release["set_id"] == item["provider_id"] == item["set_id"]
        assert release["system_code"] == item["system_code"] == "NARUTO_KAYOU"
        assert release["language"] == item["language"] == "Unknown"
        assert release["release_date"] is None, "A published month cannot become an invented release day"
        assert item["image_url"] is None, "No unlicensed artwork URLs"
        assert item["source_url"].startswith("https://www.kayouofficial.com/en-US/series/")
        assert (item["product_type"], item["evidence"]["packs_per_box"],
                item["evidence"]["cards_per_pack"], item["evidence"]["release_month"]) == expected[item["provider_id"]]
        assert item["evidence"]["physical_valuation_eligible"] is False
        assert item["evidence"]["physical_language_confirmed"] is False
        assert item["evidence"]["physical_package_verified"] is False
        assert item["evidence"]["source_image_rights_verified"] is False
        assert "market_value_minor" not in item
        assert item["provider_id"] in release["set_id"]
        assert not any(k in item for k in ("owner_id", "shopify_product_id", "inventory_id"))
    assert len({i["provider_id"] for _, i in items}) == 4


@pytest.mark.parametrize("change", [
    {"source_url": "https://other-domain.example/series/series-5zdty4vj"},
    {"source_url": "http://www.kayouofficial.com/en-US/series/series-5zdty4vj"},
    {"product_model": "PREDICTED-BOX"},
    {"product_type": "CARD"},
    {"release_month": "2026-02-01"},
    {"packs_per_box": 0},
    {"cards_per_pack": 21},
])
def test_forged_models_sources_and_box_facts_cannot_enter_manifest(change):
    with pytest.raises(ValueError):
        replace(kayou.OFFICIAL_PRODUCTS[0], **change).validate()


class Connection:
    def __init__(self, conflicted=False):
        self.conflicted=conflicted
        self.transactions=0
        self.commits=0
        self.rolled_back=0
        self.queries=[]
        self.models=set()

    @asynccontextmanager
    async def transaction(self):
        self.transactions+=1
        try:
            yield self
            self.commits+=1
        except Exception:
            self.rolled_back+=1
            raise

    async def fetchval(self, sql, *values):
        self.queries.append((sql, values))
        assert "tcg.inventory_items" not in sql and "tcg.catalogue_products" not in sql
        assert "shopify" not in sql.lower() and "market_prices" not in sql
        assert "where tcg.reference" in sql
        if self.conflicted and len(self.queries)==4:
            return None
        self.models.add(values[3])
        return values[3]


@pytest.mark.asyncio
async def test_atomic_admin_import_limited_to_reference_sets_and_sealed_products():
    connection=Connection()
    result=await kayou.register_verified_publisher_products(connection)
    assert result["verified_sealed_references"] == 4
    assert result["market_prices_added"] == result["inventory_items_changed"] == 0
    assert connection.transactions==1 and connection.commits==1
    assert len(connection.queries)==8
    assert len(connection.models)==4
    assert all("insert into tcg.reference_" in query.lower() for query,_ in connection.queries)
    await kayou.register_verified_publisher_products(connection)
    assert connection.commits==2 and connection.transactions==2
    assert len(connection.models)==4, "Idempotent replay uses exact SKU rather than new identity"


@pytest.mark.asyncio
async def test_conflicting_existing_manufacturer_reference_rolls_back_everything():
    conn=Connection(conflicted=True)
    with pytest.raises(ValueError, match="identity conflict"):
        await kayou.register_verified_publisher_products(conn)
    assert conn.rolled_back==1 and conn.commits==0


def test_unknown_physical_language_must_be_confirmed_before_sealed_intake():
    release, sealed=kayou.candidate_manifest()[0]
    row=dict(catalogue_id=None,product_type="SEALED",game="Naruto Kayou",
             name=sealed["name"],set_name=release["name"],
             card_number=None,provider_id=sealed["provider_id"],language="Unknown")
    payload=browser.BrowseIntake(key="s:"+"a"*32,confirmed=True,seal_status="SEALED")
    with pytest.raises(Exception,match="Choose the physical product language"):
        browser.intake_payload(row,payload)
    selected=browser.intake_payload(row,payload.model_copy(update={"language":"English"}))
    assert selected.identity_confirmed is False
    assert selected.seal_status=="SEALED"
    assert selected.new_catalogue.game=="Naruto Kayou"
    assert selected.new_catalogue.language=="English"
    assert selected.new_catalogue.variant==sealed["provider_id"]
