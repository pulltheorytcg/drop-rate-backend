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
                     rights_tier='FIRST_PARTY_CAPTURE' if slab_photo else 'STOREFRONT_ALLOWED',
                     source_type='FOUNDER_UPLOAD' if slab_photo else 'OFFICIAL_PROVIDER',
                     source_provider='Drop Rate' if slab_photo else 'PSA',
                     shopify_cdn_url='https://cdn.shopify.com/slab.jpg')]
    monkeypatch.setattr(media, 'shared_media_assets', assets)
    await media.add_shared_inventory_media(None, [item])
    assert 'reference_image_url' not in item and 'reference_image_path' not in item
    assert item['image_url'] == ('https://cdn.shopify.com/slab.jpg' if slab_photo else None)
    assert item['card_image_direct_url'] == item['image_url']
    assert item['reference_image_status'] == ('COPY_PHOTO' if slab_photo else 'SLAB_PHOTO_REQUIRED')


@pytest.mark.asyncio
@pytest.mark.parametrize('override', [
    {'rights_tier': 'INTERNAL_REFERENCE_ONLY', 'source_provider': 'BGS',
     'source_type': 'OFFICIAL_PROVIDER'},
    {'rights_tier': 'MARKETPLACE_NATIVE_ONLY', 'source_provider': 'ACE',
     'source_type': 'OFFICIAL_PROVIDER'},
    {'rights_tier': 'FIRST_PARTY_CAPTURE', 'source_type': 'OFFICIAL_PROVIDER'},
    {'rights_tier': 'FIRST_PARTY_CAPTURE', 'source_type': 'FOUNDER_UPLOAD',
     'approval_status': 'PENDING'},
])
async def test_wrong_grader_or_unapproved_shopify_file_never_claims_copy_photo(monkeypatch, override):
    item = dict(id=uuid4(), grading_company='PSA', grade='10',
                reference_image_url='https://assets.tcgdex.net/raw/high.webp',
                reference_image_path='/reference', image_url='old-raw')
    fake = dict(inventory_id=item['id'], scope='INVENTORY_ITEM',
                capture_context='GRADED_SLAB', approval_status='APPROVED',
                source_type='FOUNDER_UPLOAD',rights_tier='FIRST_PARTY_CAPTURE',
                source_provider='Drop Rate',shopify_cdn_url='https://cdn.shopify.com/slab.jpg')
    fake.update(override)
    async def assets(*args):
        return [fake]
    monkeypatch.setattr(media, 'shared_media_assets', assets)
    result = (await media.add_shared_inventory_media(None, [item]))[0]
    assert result['image_url'] is None
    assert result['card_image_url'] is None
    assert result['card_image_direct_url'] is None
    assert result['reference_image_status'] == 'SLAB_PHOTO_REQUIRED'
    assert result['card_image_scope'] is None
    assert 'reference_image_url' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('grader', ['PSA','ACE','BGS','CGC'])
async def test_approved_exact_grader_reference_displays_privately_but_not_as_selling_photo(monkeypatch, grader):
    item = dict(id=uuid4(), grading_company=grader, grade='10', certificate_number='12345678',
                reference_image_url='old-raw', reference_image_path='/raw')
    asset = dict(inventory_id=item['id'], scope='INVENTORY_ITEM', capture_context='GRADED_SLAB',
                 approval_status='APPROVED', rights_tier='INTERNAL_REFERENCE_ONLY',
                 source_type='OFFICIAL_PROVIDER', source_provider=grader,
                 shopify_cdn_url='https://cdn.shopify.com/certificate.jpg')
    async def assets(*args):
        return [asset]
    monkeypatch.setattr(media,'shared_media_assets',assets)
    result = (await media.add_shared_inventory_media(None,[item]))[0]
    assert result['image_url'] == asset['shopify_cdn_url']
    assert result['reference_image_status'] == 'GRADER_CERTIFICATE_REFERENCE'
    assert result['card_image_source_type'] == 'OFFICIAL_PROVIDER'
    assert result['card_image_rights_tier'] == 'INTERNAL_REFERENCE_ONLY'
    assert 'reference_image_url' not in result


@pytest.mark.asyncio
async def test_unapproved_provider_photo_does_not_win_over_valid_first_party_photo(monkeypatch):
    item = dict(id=uuid4(),grading_company='BGS',grade='10',
                reference_image_url='https://assets.tcgdex.net/raw/high.webp')
    provider=dict(inventory_id=item['id'],scope='INVENTORY_ITEM',
                  capture_context='GRADED_SLAB',approval_status='APPROVED',
                  source_type='OFFICIAL_PROVIDER',rights_tier='INTERNAL_REFERENCE_ONLY',
                  source_provider='BGS',shopify_cdn_url='https://cdn.shopify.com/provider.jpg')
    captured=dict(provider,source_type='CONSIGNOR_UPLOAD',rights_tier='FIRST_PARTY_CAPTURE',
                  source_provider='Drop Rate',shopify_cdn_url='https://cdn.shopify.com/actual-slab.jpg')
    async def assets(*args):
        return [provider,captured]
    monkeypatch.setattr(media,'shared_media_assets',assets)
    result=(await media.add_shared_inventory_media(None,[item]))[0]
    assert result['image_url']=='https://cdn.shopify.com/actual-slab.jpg'
    assert result['reference_image_status']=='COPY_PHOTO'


def test_media_sql_enforces_exact_owner_first_party_rights_and_staff_approval():
    sql=media.MEDIA_SQL
    for clause in (
        "ma.inventory_id=i.id and ma.owner_id=i.owner_id",
        "ma.rights_tier='FIRST_PARTY_CAPTURE'",
        "ma.source_type in ('FOUNDER_UPLOAD','CONSIGNOR_UPLOAD')",
        "ma.rights_tier='INTERNAL_REFERENCE_ONLY'",
        "ma.source_type='OFFICIAL_PROVIDER'",
        "upper(btrim(ma.source_provider))=upper(btrim(i.grading_company))",
        "position(btrim(i.certificate_number) in ma.source_reference)>0",
        "position(btrim(i.certificate_number) in ma.provider_asset_id)>0",
        "ma.approval_status='APPROVED'",
        "ma.capture_context='GRADED_SLAB'",
        "ma.revoked_at is null",
    ):
        assert clause in sql
    assert "ma.approval_status in ('PENDING','APPROVED')" not in sql
