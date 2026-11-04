"""A graded physical copy cannot borrow catalogue artwork while rendering."""
from uuid import uuid4

import pytest

from app import inventory_reference_media as media, owner_inventory


@pytest.mark.asyncio
async def test_reference_artwork_skips_graded_cards_and_books_without_lookup():
    class Connection:
        async def fetch(self, *args):
            raise AssertionError('Graded copies must not query raw references')
    items = [dict(id=uuid4(), catalogue_id=uuid4(), product_type=kind,
                  grading_company='PSA', grade='10', reference_image_url='old-raw',
                  reference_image_path='/old-reference') for kind in ('CARD', 'COMIC')]
    await owner_inventory.add_reference_artwork(Connection(), items)
    assert all('reference_image_url' not in item and 'reference_image_path' not in item for item in items)


@pytest.mark.asyncio
@pytest.mark.parametrize('slab_photo', [True, False])
async def test_shared_response_preserves_exact_slab_and_clears_raw_fields(monkeypatch, slab_photo):
    item = dict(id=uuid4(), grading_company='PSA', grade='10', reference_image_url='old-raw',
                reference_image_path='/raw', image_url='old-raw')
    async def assets(*args):
        return [dict(inventory_id=item['id'], scope='INVENTORY_ITEM' if slab_photo else 'CANONICAL_CARD',
                     capture_context='GRADED_SLAB' if slab_photo else None, approval_status='APPROVED',
                     source_provider='PSA', shopify_cdn_url='https://cdn.shopify.com/slab.jpg')]
    monkeypatch.setattr(media, 'shared_media_assets', assets)
    await media.add_shared_inventory_media(None, [item])
    assert 'reference_image_url' not in item and 'reference_image_path' not in item
    assert item['image_url'] == ('https://cdn.shopify.com/slab.jpg' if slab_photo else None)
    assert item['card_image_direct_url'] == item['image_url']
    assert item['reference_image_status'] == ('COPY_PHOTO' if slab_photo else 'SLAB_PHOTO_REQUIRED')
