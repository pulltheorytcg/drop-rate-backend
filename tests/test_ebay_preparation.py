from copy import deepcopy

import pytest

from app.seller_inventory_policy import ebay_preparation


def prepared():
    return dict(owner_type='FOUNDER', product_type='CARD', identity_ready=True,
                language='English', condition='Near Mint', store_price_minor=100,
                status='APPROVED', sale_intent='FOR_SALE', ebay_photos_ready=True,
                ebay_catalogue_ready=False, intake_ready=True,
                ebay_shipping_ready=True)


def test_readiness_is_read_only_and_keeps_scope_separate_from_preparation():
    item = prepared(); before = deepcopy(item)
    result = ebay_preparation(item)
    assert result['completed'] == len(result['checks']) == 7
    assert result['scope_blocker'] is None and item == before
    item['owner_type'] = 'CONSIGNOR'
    result = ebay_preparation(item)
    assert result['completed'] == 7 and result['scope_blocker'] is None


@pytest.mark.parametrize('change,missing', [
    ({'identity_ready': False}, 'identity'), ({'language': None}, 'language'),
    ({'condition': 'Lightly Played'}, 'condition'), ({'store_price_minor': None}, 'price'),
    ({'sale_intent': 'PERSONAL_COLLECTION'}, 'approval'), ({'status': 'RESERVED'}, 'approval'),
    ({'ebay_photos_ready': False}, 'photos'),
    ({'intake_ready': False}, 'intake'), ({'ebay_shipping_ready': False}, 'shipping'),
])
def test_each_missing_requirement_is_an_actionable_step(change, missing):
    result = ebay_preparation({**prepared(), **change})
    step = next(s for s in result['checks'] if s['code'] == missing)
    assert not step['complete'] and step['next_step']
    assert result['completed'] == 6


def test_canonical_catalogue_image_replaces_extra_physical_photo_gate():
    item = {**prepared(), 'ebay_photos_ready': False,
            'ebay_catalogue_ready': True, 'condition': None,
            'grading_company': 'PSA', 'grade': '10'}
    assert ebay_preparation(item)['completed'] == 7
    item['ebay_catalogue_ready'] = False
    assert ebay_preparation(item)['completed'] == 6


def test_raw_card_defaults_to_near_mint_without_condition_review():
    item = {**prepared(), 'condition': None}
    assert ebay_preparation(item)['completed'] == 7
