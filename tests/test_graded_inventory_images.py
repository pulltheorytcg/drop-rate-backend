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


@pytest.mark.asyncio
@pytest.mark.parametrize('grader', ['PSA','ACE','BGS','CGC'])
async def test_exact_approved_grader_raw_card_image_is_private_reference(monkeypatch, grader):
    item = dict(id=uuid4(), grading_company=grader, grade='9', certificate_number='62398872',
                reference_image_url='should-clear', reference_image_path='/raw')
    asset = dict(inventory_id=item['id'], scope='INVENTORY_ITEM',
                 capture_context='RAW_UNSLEEVED', approval_status='APPROVED',
                 rights_tier='INTERNAL_REFERENCE_ONLY', source_type='OFFICIAL_PROVIDER',
                 source_provider=grader, shopify_cdn_url='https://cdn.shopify.com/cert-card.jpg')
    async def assets(*args):
        return [asset]
    monkeypatch.setattr(media, 'shared_media_assets', assets)
    result = (await media.add_shared_inventory_media(None, [item]))[0]
    assert result['image_url'] == asset['shopify_cdn_url']
    assert result['reference_image_status'] == 'GRADER_CERTIFICATE_RAW_REFERENCE'
    assert result['card_image_capture_context'] == 'RAW_UNSLEEVED'
    assert result['card_image_rights_tier'] == 'INTERNAL_REFERENCE_ONLY'
    assert result['card_image_source_type'] == 'OFFICIAL_PROVIDER'
    assert 'reference_image_url' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('reviewed', [True, False])
async def test_reviewed_graded_card_uses_exact_canonical_art_only_privately(monkeypatch, reviewed):
    item = dict(id=uuid4(), grading_company='PSA', grade='9', certificate_number='62398872',
                reference_image_url='old-unbound',
                reference_image_path='/old', image_url='old-unbound')
    asset = dict(inventory_id=item['id'], scope='CANONICAL_CARD', capture_context=None,
                 approval_status='APPROVED', rights_tier='STOREFRONT_ALLOWED',
                 source_type='LICENSED_PROVIDER', source_provider='TCGdex',
                 public_source_url='https://assets.tcgdex.net/en/swsh/swsh3/19/high.webp',
                 shopify_cdn_url=None, graded_card_art_allowed=reviewed)
    async def assets(*args):
        return [asset]
    monkeypatch.setattr(media, 'shared_media_assets', assets)
    result = (await media.add_shared_inventory_media(None, [item]))[0]
    assert result['image_url'] == (asset['public_source_url'] if reviewed else None)
    assert result['reference_image_status'] == (
        'GRADED_CARD_ART_REFERENCE' if reviewed else 'SLAB_PHOTO_REQUIRED')
    assert result['card_image_scope'] == ('CANONICAL_CARD' if reviewed else None)
    assert 'reference_image_path' not in result
    assert 'reference_image_url' not in result


def test_graded_fallback_selector_requires_exact_identity_review_and_never_public_sale_rights():
    sql = media.MEDIA_SQL
    for clause in (
        "to_jsonb(i)->>'identity_confirmed'='true'",
        "to_jsonb(i)->>'condition_review_status'='VERIFIED_GRADED'",
        "to_jsonb(i)->>'condition_verified_by_user_id' is not null",
        "to_jsonb(i)->>'status' in ('APPROVED','RESERVED','SOLD')",
        "length(btrim(i.certificate_number))>=6",
        "to_jsonb(p)->>'product_type'='CARD'",
        "ma.capture_context in ('GRADED_SLAB','RAW_UNSLEEVED')",
        "ma.capture_context='RAW_UNSLEEVED' and ma.rights_tier='INTERNAL_REFERENCE_ONLY'",
        "and ma.source_type='OFFICIAL_PROVIDER'",
        "ma.rights_tier='STOREFRONT_ALLOWED'",
    ):
        assert clause in sql
    assert "or (ma.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT')" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize('grader', ['PSA', 'ACE', 'BGS', 'CGC'])
@pytest.mark.parametrize('reverse_assets', [False, True])
async def test_certificate_reference_is_independent_of_other_items_in_page(monkeypatch, grader, reverse_assets):
    """An unrelated physical photo must not decide another item's reference eligibility."""
    first = dict(id=uuid4(), grading_company=grader, grade='9', certificate_number='12345678')
    second = dict(id=uuid4(), grading_company='PSA', grade='10', certificate_number='87654321')
    reference = dict(inventory_id=first['id'], scope='INVENTORY_ITEM',
        capture_context='RAW_UNSLEEVED', approval_status='APPROVED',
        rights_tier='INTERNAL_REFERENCE_ONLY', source_type='OFFICIAL_PROVIDER',
        source_provider=grader, shopify_cdn_url='https://cdn.shopify.com/reference.jpg')
    slab = dict(inventory_id=second['id'], scope='INVENTORY_ITEM',
        capture_context='GRADED_SLAB', approval_status='APPROVED',
        rights_tier='FIRST_PARTY_CAPTURE', source_type='CONSIGNOR_UPLOAD',
        source_provider='Drop Rate', shopify_cdn_url='https://cdn.shopify.com/slab.jpg')
    selected = [reference, slab]
    if reverse_assets:
        selected.reverse()
    async def assets(*args):
        return selected
    monkeypatch.setattr(media, 'shared_media_assets', assets)
    result = await media.add_shared_inventory_media(None, [first, second])
    assert result[0]['image_url'] == reference['shopify_cdn_url']
    assert result[0]['reference_image_status'] == 'GRADER_CERTIFICATE_RAW_REFERENCE'
    assert result[0]['card_image_rights_tier'] == 'INTERNAL_REFERENCE_ONLY'
    assert result[1]['image_url'] == slab['shopify_cdn_url']
    assert result[1]['reference_image_status'] == 'COPY_PHOTO'


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', [
    {'rights_tier': 'FIRST_PARTY_CAPTURE', 'source_type': 'FOUNDER_UPLOAD'},
    {'source_provider': 'BGS'},
    {'approval_status': 'PENDING'},
    {'rights_tier': 'MARKETPLACE_NATIVE_ONLY'},
])
async def test_other_items_valid_certificate_cannot_authorize_invalid_raw_photo(monkeypatch, invalid):
    first = dict(id=uuid4(), grading_company='PSA', grade='10')
    second = dict(id=uuid4(), grading_company='PSA', grade='9')
    valid = dict(inventory_id=second['id'], scope='INVENTORY_ITEM',
        capture_context='RAW_UNSLEEVED', approval_status='APPROVED',
        rights_tier='INTERNAL_REFERENCE_ONLY', source_type='OFFICIAL_PROVIDER',
        source_provider='PSA', shopify_cdn_url='https://cdn.shopify.com/reference.jpg')
    invalid_asset = dict(valid, inventory_id=first['id'], **invalid)
    async def assets(*args):
        return [invalid_asset, valid]
    monkeypatch.setattr(media, 'shared_media_assets', assets)
    result = await media.add_shared_inventory_media(None, [first, second])
    assert result[0]['image_url'] is None
    assert result[0]['reference_image_status'] == 'SLAB_PHOTO_REQUIRED'
    assert result[1]['reference_image_status'] == 'GRADER_CERTIFICATE_RAW_REFERENCE'
