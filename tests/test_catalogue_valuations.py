from datetime import datetime,timedelta,timezone
from uuid import uuid4

from app.catalogue_valuations import catalogue_values
from app.live_market_refresh import identity_key

NOW=datetime(2026,10,9,18,tzinfo=timezone.utc)
CAT=uuid4()
PRODUCT=dict(catalogue_id=CAT,product_type='CARD',game='Pokemon',name='Seel',set_name='Phantasmal Flames',
             card_number='021/094',variant='Normal',rarity='Common',language='English',set_code=None,
             profile_identity_status=None,sealed_identity_status=None,sealed_product_type=None)


def observation(n):
    return dict(id=uuid4(),catalogue_id=CAT,source='EBAY',observation_type='SOLD',source_country='GB',currency='GBP',
        observed_at=NOW-timedelta(days=n),ingested_at=NOW-timedelta(hours=3),price_gbp_minor=100*n,shipping_gbp_minor=100,
        condition='Near Mint',grading_company=None,grade=None,language='English',seal_status=None,
        metadata={'selection_rule':'FIVE_NEWEST_EXACT_COMPARABLE_SALES','marketplace':'EBAY_GB','provider_item_id':str(n),
                  'title':'Seel 021/094 Phantasmal Flames English NM'})


def test_catalogue_value_requires_no_inventory_owner_or_seller_price():
    values=catalogue_values(PRODUCT,[observation(n) for n in range(1,6)],now=NOW)
    assert len(values)==1
    value=values[0]
    assert value['result'].algorithm_version=='drop-rate-market-v4' and value['result'].market_value_minor>0
    assert value['evidence']['input_sale_count']==5
    assert value['evidence_checked_at']==NOW-timedelta(hours=3)
    assert 'owner_id' not in value['evidence'] and 'inventory_id' not in value['evidence']


def test_exact_identity_language_printing_depth_and_uk_source_still_required():
    rows=[observation(n) for n in range(1,6)]
    assert not catalogue_values(PRODUCT,rows[:4]+[rows[0]],now=NOW)
    assert not catalogue_values(dict(PRODUCT,variant='Reverse Holofoil'),rows,now=NOW)
    assert not catalogue_values(dict(PRODUCT,language='Japanese'),rows,now=NOW)
    assert not catalogue_values(dict(PRODUCT,name='Dewgong'),rows,now=NOW)
    assert not catalogue_values(PRODUCT,[dict(row,source_country='US') for row in rows],now=NOW)
    assert not catalogue_values(PRODUCT,[dict(row,metadata={}) for row in rows],now=NOW)


def test_recalculation_cannot_make_old_evidence_fresh_but_actual_provider_recheck_can():
    rows=[dict(observation(n),ingested_at=NOW-timedelta(days=8)) for n in range(1,6)]
    assert not catalogue_values(PRODUCT,rows,now=NOW)
    key=identity_key(dict(PRODUCT,condition='Near Mint',grading_company=None,grade=None,seal_status=None,identity_confirmed=True))
    checked=NOW-timedelta(hours=1)
    values=catalogue_values(PRODUCT,rows,now=NOW,provider_checks={key:checked})
    assert values[0]['evidence_checked_at']==checked
    assert not catalogue_values(PRODUCT,rows,now=NOW,provider_checks={'other identity':checked})
    assert not catalogue_values(PRODUCT,rows,now=NOW,provider_checks={key:NOW+timedelta(hours=1)})


def test_stale_sales_and_graded_bases_do_not_mix_with_raw():
    rows=[observation(n) for n in range(1,6)]
    assert not catalogue_values(PRODUCT,[dict(r,observed_at=NOW-timedelta(days=91)) for r in rows],now=NOW)
    split=[dict(rows[0],grading_company='PSA',grade='10',condition=None),*rows[1:]]
    assert not catalogue_values(PRODUCT,split,now=NOW)
