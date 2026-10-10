"""Published SEALED pool and legacy order routing regression tests."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from app.shopify_pipeline import ShopifyProcessingError, _select_order_units
from app.shopify_sealed_pooling import (
    evaluate_published_sealed_group,
    pooled_sealed_description_html,
    sealed_pool_identity,
    validate_sealed_remote_snapshots,
)

OWNER=str(uuid4())
CATALOGUE="24393ecd-59f6-4561-a7c4-971bb3482f2d"
ACTOR=str(uuid4())
ANCHOR_PRODUCT="gid://shopify/Product/10788230791515"
RETIRED_PRODUCT="gid://shopify/Product/10788230857051"
ANCHOR_VARIANT="gid://shopify/ProductVariant/54295232119131"
RETIRED_VARIANT="gid://shopify/ProductVariant/54295233134939"
ANCHOR_ITEM="gid://shopify/InventoryItem/56430021902683"
RETIRED_ITEM="gid://shopify/InventoryItem/56430022918491"
SOURCE_NAME="Booster Pack: World's Strongest Warriors [OP-17]"
SOURCE_SET="World's Strongest Warriors [OP-17]"


def item(index):
    approval={
      "name":SOURCE_NAME, "set_name":SOURCE_SET, "variant":"",
      "catalogue_id":CATALOGUE, "owner_id":OWNER,
      "language":"Japanese", "actor_user_id":ACTOR,
    }
    return {
      "inventory_id":str(uuid4()),"catalogue_id":CATALOGUE,
      "owner_id":OWNER,"created_by_user_id":ACTOR,
      "inventory_code":"INV-OP17-"+str(index),
      "inventory_created_at":"2026-10-01" if index==0 else "2026-10-10",
      "status":"APPROVED","sale_intent":"FOR_SALE",
      "identity_confirmed":True,"catalogue_identity_status":"VERIFIED",
      "language":"Japanese","catalogue_language":"Japanese",
      "condition":None,"seal_status":"SEALED","product_type":"SEALED",
      "sealed_product_type":"BOOSTER_PACK","grade":None,
      "grading_company":None,"certificate_number":None,
      "acquisition_cost_minor":None,"storage_location_id":None,
      "store_price_minor":1000,"synced_price_minor":1000,
      "shop_domain":"fqu56y-hm.myshopify.com",
      "shopify_product_gid":ANCHOR_PRODUCT if index==0 else RETIRED_PRODUCT,
      "shopify_variant_gid":ANCHOR_VARIANT if index==0 else RETIRED_VARIANT,
      "shopify_inventory_item_gid":ANCHOR_ITEM if index==0 else RETIRED_ITEM,
      "shopify_location_gid":"gid://shopify/Location/118816145755",
      "shopify_publication_gid":"gid://shopify/Publication/353099710811",
      "sku":"INV-OP17-"+str(index), "sync_state":"PUBLISHED",
      "test_mode":False,"has_live_ebay_link":False,
      "reserved_order_reference":None,"reserved_line_reference":None,
      "has_listing_membership":False,"has_active_reservation":False,
      "source_record":{"seller_held_approval":approval},
      "name":SOURCE_NAME,"set_name":SOURCE_SET,"variant":"",
      "owner_type":"CONSIGNOR",
    }


def remote(member):
    return {
      "status":"ACTIVE","title":SOURCE_NAME+" · JP",
      "tags":["Drop Rate","One Piece","Language:Japanese"],"vendor":"One Piece",
      "productType":"Sealed TCG Product",
      "collections":{"nodes":[{"title":"Sealed"},{"title":"One Piece"}]},
      "media":{"nodes":[{"id":"gid://shopify/MediaImage/58904403149147"}]},
      "variants":{"nodes":[{
        "id":member["shopify_variant_gid"],"price":"10.00",
        "inventoryQuantity":1,"inventoryPolicy":"DENY",
        "inventoryItem":{"id":member["shopify_inventory_item_gid"],"tracked":True}
      }]},
    }


def test_two_op17_packs_select_oldest_original_shopify_listing():
    a,b=item(0),item(1)
    result=evaluate_published_sealed_group([b,a])
    assert result["ready"],result["blockers"]
    assert result["quantity"]==2
    assert result["price_minor"]==1000
    assert result["anchor_product_gid"]==ANCHOR_PRODUCT
    assert result["anchor_variant_gid"]==ANCHOR_VARIANT
    assert result["other_products"]==[RETIRED_PRODUCT]
    assert result["pool"]["listing_key"].startswith("shopify-pool:sealed:")
    assert result["pool"]["sku"].startswith("DRP-S-")
    assert sealed_pool_identity(b)==sealed_pool_identity(a)
    assert validate_sealed_remote_snapshots(result, {
        ANCHOR_PRODUCT:remote(a), RETIRED_PRODUCT:remote(b)
    })==[]


def test_sealed_description_never_leaks_a_single_inventory_code():
    original=(
      "<p><strong>"+SOURCE_NAME+"</strong> is an individually tracked sealed TCG product from Drop Rate inventory.</p>"
      "<ul>\n<li>\n<strong>Game:</strong> One Piece</li>\n"
      "<li>\n<strong>Inventory ID:</strong> INV-ORIGINAL</li>\n</ul>"
    )
    pooled=pooled_sealed_description_html(original)
    assert "Inventory ID:" not in pooled
    assert "INV-ORIGINAL" not in pooled
    assert "Each pack remains individually tracked" in pooled
    assert "One Piece" in pooled
    assert pooled_sealed_description_html(pooled)==pooled
    with pytest.raises(ValueError,match="Unrecognised"):
        pooled_sealed_description_html("<p>Unknown seller content</p>")
    with pytest.raises(ValueError,match="exactly one"):
        pooled_sealed_description_html("<p>"+SOURCE_NAME+
            " is an individually tracked sealed TCG product from Drop Rate inventory.</p>")


@pytest.mark.parametrize("name,value",[
    ("product_type","CARD"),("seal_status","UNSEALED"),
    ("status","RESERVED"),("sale_intent","PERSONAL_COLLECTION"),
    ("language","English"),("store_price_minor",900),
    ("sealed_product_type","BOOSTER_BOX"),("variant","SPECIAL_ART"),
    ("grade","10"),("identity_confirmed",False),
    ("catalogue_identity_status","UNVERIFIED"),("reserved_order_reference","old-order"),
    ("has_active_reservation",True),("has_listing_membership",True),
    ("acquisition_cost_minor",None),
])
def test_non_interchangeable_or_unapproved_sealed_copies_are_blocked(name,value):
    a,b=item(0),item(1)
    b[name]=value
    if name=="acquisition_cost_minor":
        b["source_record"]={}  # Null acquisition only permitted for verified seller-held stock.
    result=evaluate_published_sealed_group([a,b])
    assert not result["ready"],(name,result)
    assert result["blockers"]


@pytest.mark.parametrize("change",[
    lambda r:r["variants"]["nodes"][0].update(inventoryPolicy="CONTINUE"),
    lambda r:r["variants"]["nodes"][0].update(price="9.99"),
    lambda r:r["variants"]["nodes"][0].update(inventoryQuantity=2),
    lambda r:r["variants"]["nodes"][0]["inventoryItem"].update(tracked=False),
    lambda r:r["media"].update(nodes=[{"id":"gid://shopify/MediaImage/unrelated"}]),
    lambda r:r.update(status="ARCHIVED"),
])
def test_remote_prerequisites_fail_closed(change):
    a,b=item(0),item(1);group=evaluate_published_sealed_group([a,b])
    snapshot_a,snapshot_b=remote(a),remote(b)
    change(snapshot_b)
    assert validate_sealed_remote_snapshots(group,{
        ANCHOR_PRODUCT:snapshot_a,RETIRED_PRODUCT:snapshot_b
    })


@pytest.mark.asyncio
async def test_legacy_variant_resolves_only_original_physical_copy():
    owner=uuid4()
    catalogue=uuid4()
    legacy={"id":uuid4(),"inventory_id":uuid4(),"owner_id":owner,
      "created_by_user_id":uuid4(),"allocation_priority":2,
      "linked_at":"2026-10-10T15:41:00Z",
      "status":"APPROVED","inventory_status":"APPROVED",
      "sale_intent":"FOR_SALE","synced_price_minor":1000,
      "reserved_order_reference":None,"reserved_line_reference":None,
      "acquisition_cost_minor":None,"store_price_minor":1000,
      "sku":"DRP-S-NEW","shopify_variant_gid":ANCHOR_VARIANT,
      "shopify_product_gid":ANCHOR_PRODUCT,
      "legacy_variant_gid":RETIRED_VARIANT,
      "legacy_product_gid":RETIRED_PRODUCT,
      "legacy_sku":"INV-LEGACY-OLD",
      "source_record":{"seller_held_approval":{
        "owner_id":str(owner),"catalogue_id":str(catalogue),
        "language":"Japanese","name":SOURCE_NAME,
        "set_name":SOURCE_SET,"variant":"","actor_user_id":str(uuid4())}},
      "catalogue_id":catalogue,"language":"Japanese","seal_status":"SEALED",
      "identity_confirmed":True,"catalogue_language":"Japanese",
      "product_type":"SEALED","name":SOURCE_NAME,"set_name":SOURCE_SET,
      "variant":"","owner_type":"CONSIGNOR",
      "inventory_code":"INV-LEGACY-OLD"}
    class FakeConnection:
        async def fetch(self,sql,*args):
            if "where sil.shopify_variant_gid=$1" in sql:
                assert args == (RETIRED_VARIANT,)
                return []
            if "tcg.shopify_variant_pool_aliases a" in sql:
                assert args == (RETIRED_VARIANT,"old-order")
                return [legacy]
            raise AssertionError(sql)
    spec={"variant_gid":RETIRED_VARIANT,"quantity":1,
      "unit_price_minor":1000,"discount_minor":0,"line_reference":"old-line",
      "line":{"product_id":RETIRED_PRODUCT.removeprefix("gid://shopify/Product/"),
              "sku":"INV-LEGACY-OLD"}}
    selected=await _select_order_units(FakeConnection(),order_reference="old-order",line_specs=[spec])
    assert len(selected)==1
    assert selected[0]["link"]["inventory_id"]==legacy["inventory_id"]
    assert selected[0]["link"]["shopify_variant_gid"]==RETIRED_VARIANT
    assert selected[0]["link"]["shopify_product_gid"]==RETIRED_PRODUCT
    assert selected[0]["link"]["sku"]=="INV-LEGACY-OLD"
    assert selected[0]["sale_price_minor"]==1000
