"""Exercise the actual eBay publisher and founder photo-readiness SQL in PostgreSQL."""
import ast
import inspect

import pytest

from app.ebay_sales import _load_listing_plan
from app.owner_inventory import DETAIL_SQL
from test_book_connector_import import run_sql


SETUP = """
create schema ebay_photo_test;
create table ebay_photo_test.media_assets(
  owner_id text,inventory_id text,scope text,media_kind text,side text,
  source_type text,rights_tier text,capture_context text,
  rights_status text,approval_status text,source_status text,
  revoked_at timestamptz,shopify_file_status text,shopify_cdn_url text
);
create table ebay_photo_test.items(
  id text,owner_id text,grade text,grading_company text
);
insert into ebay_photo_test.items values ('copy','seller','9','PSA');
insert into ebay_photo_test.media_assets values
  ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','FOUNDER_UPLOAD','FIRST_PARTY_CAPTURE','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',null,'READY','front'),
  ('seller','copy','INVENTORY_ITEM','IMAGE','BACK','FOUNDER_UPLOAD','FIRST_PARTY_CAPTURE','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',null,'READY','back'),
  ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','OFFICIAL_PROVIDER','INTERNAL_REFERENCE_ONLY','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',null,'READY','psa-front'),
  ('seller','copy','INVENTORY_ITEM','IMAGE','BACK','OFFICIAL_PROVIDER','INTERNAL_REFERENCE_ONLY','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',null,'READY','psa-back'),
  ('other','copy','INVENTORY_ITEM','IMAGE','FRONT','FOUNDER_UPLOAD','FIRST_PARTY_CAPTURE','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',null,'READY','foreign-owner'),
  ('seller','other','INVENTORY_ITEM','IMAGE','FRONT','FOUNDER_UPLOAD','FIRST_PARTY_CAPTURE','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',null,'READY','foreign-copy'),
  ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','FOUNDER_UPLOAD','FIRST_PARTY_CAPTURE','GRADED_SLAB','VERIFIED','APPROVED','INACTIVE',null,'READY','inactive'),
  ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','FOUNDER_UPLOAD','FIRST_PARTY_CAPTURE','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',now(),'READY','revoked'),
  ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','FOUNDER_UPLOAD','FIRST_PARTY_CAPTURE','GRADED_SLAB','VERIFIED','PENDING','ACTIVE',null,'READY','unapproved'),
  ('seller','copy','CANONICAL_CARD','IMAGE','FRONT','OFFICIAL_PROVIDER','STOREFRONT_ALLOWED','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',null,'READY','reference-art'),
  ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','OFFICIAL_PROVIDER','FIRST_PARTY_CAPTURE','GRADED_SLAB','VERIFIED','APPROVED','ACTIVE',null,'READY','invalid-first-party-provider');
"""


def publisher_sql(*, graded: bool) -> str:
    query = next(
        node.value for node in ast.walk(ast.parse(inspect.getsource(_load_listing_plan)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and "select side, shopify_cdn_url" in node.value
    )
    return (query.replace("tcg.media_assets", "ebay_photo_test.media_assets")
            .replace("$1", "'seller'").replace("$2", "'copy'")
            .replace("$3", "true" if graded else "false"))


def readiness_sql() -> str:
    start = DETAIL_SQL.index("(select count(distinct m.side)=2 from tcg.media_assets m")
    stop = DETAIL_SQL.index(") as ebay_photos_ready", start) + 1
    expression = DETAIL_SQL[start:stop].replace(
        "tcg.media_assets", "ebay_photo_test.media_assets"
    )
    return ("select " + expression
            + " as ebay_photos_ready from ebay_photo_test.items i where i.id='copy'")


@pytest.mark.parametrize("graded", [False, True])
def test_publisher_selects_only_first_party_rights_cleared_images(tmp_path, graded):
    result = run_sql(
        tmp_path, [publisher_sql(graded=graded)], setup=SETUP, inspect="select 1"
    )
    assert result["results"][0]["ok"], result
    assert result["results"][0]["rows"] == [
        {"side": "FRONT", "shopify_cdn_url": "front"},
        {"side": "BACK", "shopify_cdn_url": "back"},
    ]


def test_publisher_rejects_provider_reference_only_photos(tmp_path):
    setup = SETUP + """
    delete from ebay_photo_test.media_assets
    where source_type in ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD');
    """
    result = run_sql(
        tmp_path, [publisher_sql(graded=True)], setup=setup, inspect="select 1"
    )
    assert result["results"][0]["ok"], result
    assert result["results"][0]["rows"] == []


def test_publisher_rejects_wrong_capture_context_for_graded_card(tmp_path):
    setup = SETUP + """
    update ebay_photo_test.media_assets set capture_context='RAW_CARD'
    where rights_tier='FIRST_PARTY_CAPTURE';
    """
    result = run_sql(
        tmp_path,
        [publisher_sql(graded=True), publisher_sql(graded=False)],
        setup=setup,
        inspect="select 1",
    )
    assert all(step["ok"] for step in result["results"]), result
    assert result["results"][0]["rows"] == []
    assert result["results"][1]["rows"] == [
        {"side": "FRONT", "shopify_cdn_url": "front"},
        {"side": "BACK", "shopify_cdn_url": "back"},
    ]


def test_founder_photo_readiness_agrees_with_publisher(tmp_path):
    steps = [
        readiness_sql(),
        "update ebay_photo_test.media_assets set capture_context='RAW_CARD' "
        "where rights_tier='FIRST_PARTY_CAPTURE'",
        readiness_sql(),
        "update ebay_photo_test.items set grade=null,grading_company=null",
        readiness_sql(),
        "delete from ebay_photo_test.media_assets "
        "where source_type in ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD')",
        readiness_sql(),
    ]
    result = run_sql(tmp_path, steps, setup=SETUP, inspect="select 1")
    assert all(step["ok"] for step in result["results"]), result
    assert [result["results"][i]["rows"][0]["ebay_photos_ready"]
            for i in (0, 2, 4, 6)] == [True, False, True, False]
