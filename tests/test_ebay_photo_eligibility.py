"""Exercise the publisher's actual photo query against isolated PostgreSQL."""
import ast
import inspect

from app.ebay_sales import _load_listing_plan
from test_book_connector_import import run_sql


def test_only_active_approved_photos_for_the_exact_owner_and_copy_can_publish(tmp_path):
    query = next(node.value for node in ast.walk(ast.parse(inspect.getsource(_load_listing_plan)))
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)
                 and 'select side, shopify_cdn_url' in node.value)
    setup = """create schema ebay_photo_test;
    create table ebay_photo_test.media_assets(
      owner_id text,inventory_id text,scope text,media_kind text,side text,
      rights_status text,approval_status text,source_status text,revoked_at timestamptz,
      shopify_file_status text,shopify_cdn_url text);
    insert into ebay_photo_test.media_assets values
      ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','VERIFIED','APPROVED','ACTIVE',null,'READY','front'),
      ('seller','copy','INVENTORY_ITEM','IMAGE','BACK','VERIFIED','APPROVED','ACTIVE',null,'READY','back'),
      ('other','copy','INVENTORY_ITEM','IMAGE','FRONT','VERIFIED','APPROVED','ACTIVE',null,'READY','foreign-owner'),
      ('seller','other','INVENTORY_ITEM','IMAGE','FRONT','VERIFIED','APPROVED','ACTIVE',null,'READY','foreign-copy'),
      ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','VERIFIED','APPROVED','INACTIVE',null,'READY','inactive'),
      ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','VERIFIED','APPROVED','ACTIVE',now(),'READY','revoked'),
      ('seller','copy','INVENTORY_ITEM','IMAGE','FRONT','VERIFIED','PENDING','ACTIVE',null,'READY','unapproved'),
      ('seller','copy','CANONICAL_CARD','IMAGE','FRONT','VERIFIED','APPROVED','ACTIVE',null,'READY','reference-art');
    """
    query = query.replace('tcg.media_assets', 'ebay_photo_test.media_assets').replace('$1', "'seller'").replace('$2', "'copy'")
    result = run_sql(tmp_path, [query], setup=setup, inspect='select 1')
    assert result['results'][0]['ok'], result
    assert result['results'][0]['rows'] == [
        {'side': 'FRONT', 'shopify_cdn_url': 'front'},
        {'side': 'BACK', 'shopify_cdn_url': 'back'},
    ]
