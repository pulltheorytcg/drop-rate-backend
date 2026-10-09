from copy import deepcopy
from datetime import datetime,timedelta,timezone
from uuid import uuid4

import pytest

from app.cardmarket_valuations import guide_values,inventory_eligible,physical_basis,INVENTORY_METHOD

NOW=datetime(2026,10,9,20,tzinfo=timezone.utc)
PRODUCT=dict(catalogue_id=uuid4(),product_type='CARD',game='Pokemon',name='Absol',set_name='Phantasmal Flames',
    card_number='063/094',variant='Normal',rarity='Common',language=None)
QUOTE=dict(source='TCGDEX_CARDMARKET',finish='Normal',variant_id='exact-finish',product_id='857638',
    original_currency='EUR',original_minor=100,price_gbp_minor=85,fx_rate_to_gbp='0.85',
    source_field='trend',fx_source='ECB_EURO_REFERENCE_RATES',observed_at=(NOW-timedelta(hours=3)).isoformat(),
    fx_effective_at=(NOW-timedelta(hours=2)).isoformat(),fx_retrieved_at=(NOW-timedelta(hours=1)).isoformat())
REFERENCE=dict(provider='TCGdex',system_code='POKEMON_TCG',provider_id='me02-063',set_id='me02',
    reference_language='English',reference_name='Absol',reference_set_name='Phantasmal Flames',
    reference_number='063/94',quotes=[QUOTE])


def test_exact_guide_drives_v4_without_manufacturing_sold_or_physical_evidence():
    value=guide_values(PRODUCT,[REFERENCE],now=NOW)[0]
    assert value['result'].market_value_minor==85
    assert value['result'].recommended_retail_minor==100
    assert value['result'].sold_observation_count==0
    assert value['result'].algorithm_version=='drop-rate-market-v4'
    assert value['result'].confidence<=.60 and not value['result'].auto_publish_eligible
    assert value['evidence']['condition_breakdown_available'] is False
    assert value['evidence']['language_breakdown_available'] is False
    assert value['evidence_checked_at']==NOW-timedelta(hours=3)
    assert PRODUCT['language'] is None


@pytest.mark.parametrize('change',[
    {'name':'Umbreon'},{'set_name':'Mega Evolution'},{'card_number':'063/100'},
    {'card_number':'63'},{'variant':'Reverse Holofoil'},{'variant':'First Edition'},
    {'language':'Japanese'},{'product_type':'SEALED'},{'game':'One Piece'},
])
def test_guide_rejects_printing_mismatch(change):
    assert not guide_values(dict(PRODUCT,**change),[REFERENCE],now=NOW)


@pytest.mark.parametrize('change',[
    {'observed_at':(NOW-timedelta(days=8)).isoformat()},
    {'observed_at':(NOW+timedelta(minutes=1)).isoformat()},
    {'source':'TCGDEX_TCGPLAYER'},{'original_currency':'USD'},{'original_minor':True},
    {'price_gbp_minor':900},{'fx_rate_to_gbp':'NaN'},{'product_id':'0'},
    {'variant_id':''},{'fx_source':'guessed'},
])
def test_stale_wrong_currency_invalid_fx_and_missing_provenance_fail(change):
    ref=dict(REFERENCE,quotes=[dict(QUOTE,**change)])
    assert not guide_values(PRODUCT,[ref],now=NOW)


def test_ambiguous_reference_or_finish_never_resolved_by_price_availability():
    other=dict(REFERENCE,provider_id='another-print',quotes=[])
    assert not guide_values(PRODUCT,[REFERENCE,other],now=NOW)
    conflict=dict(REFERENCE,quotes=[QUOTE,dict(QUOTE,variant_id='other-treatment')])
    assert not guide_values(PRODUCT,[conflict],now=NOW)
    assert len(guide_values(PRODUCT,[REFERENCE,deepcopy(REFERENCE)],now=NOW))==1


def item_and_value():
    value=guide_values(PRODUCT,[REFERENCE],now=NOW)[0]
    value.update(identity_digest='exact-print',snapshot_id=uuid4())
    item=dict(id=uuid4(),catalogue_id=PRODUCT['catalogue_id'],owner_id=uuid4(),status='APPROVED',
        product_type='CARD',identity_confirmed=True,condition='Near Mint',language='English',
        grading_company=None,grade=None,seal_status=None,current_identity_digest='exact-print')
    return item,value


@pytest.mark.parametrize('change',[
    {'grading_company':'PSA','grade':'10'},{'condition':'Lightly Played'},
    {'condition':None},{'language':'Japanese'},{'status':'SOLD'},{'status':'RESERVED'},
    {'identity_confirmed':False},{'current_identity_digest':'changed-print'},
    {'seal_status':'SEALED'},
])
def test_only_confirmed_ungraded_near_mint_matching_language_can_receive_estimate(change):
    item,value=item_and_value()
    assert inventory_eligible(item,value,now=NOW)
    assert not inventory_eligible(dict(item,**change),value,now=NOW)


def test_current_ebay_has_priority_and_unchanged_guide_retries_are_noops():
    item,value=item_and_value()
    item.update(current_algorithm='drop-rate-market-v4',current_sold_count=5,market_value_minor=300,
        snapshot_market_value_minor=300,pricing_updated_at=NOW-timedelta(hours=2),
        current_evidence={'method':'LIVE_EBAY_MARKET_V1','sources':[{'source':'EBAY'}]})
    assert not inventory_eligible(item,value,now=NOW)
    assert inventory_eligible(dict(item,pricing_updated_at=NOW-timedelta(days=8)),value,now=NOW)
    item.update(market_value_minor=value['result'].market_value_minor,pricing_updated_at=value['evidence_checked_at'])
    item['current_evidence']={'method':INVENTORY_METHOD,'catalogue_snapshot_id':str(value['snapshot_id']),
                              'physical_basis':physical_basis(item)}
    assert not inventory_eligible(item,value,now=NOW)
