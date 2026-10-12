from copy import deepcopy
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from app.inventory_reference_values import resolve_reference_value, reference_totals, reference_top_groups, SOLD, GUIDE
from app.inventory_reference_media import direct_image_url

NOW=datetime(2026,10,12,12,tzinfo=timezone.utc)
CAT=str(uuid4())
def item(**kw):
    return dict(catalogue_id=CAT,product_type='CARD',language='Japanese',catalogue_language='Japanese',condition='Near Mint',grading_company=None,grade=None,seal_status=None,**kw)
def snapshot(**kw):
    row=dict(snapshot_id=uuid4(),catalogue_id=CAT,basis_language='Japanese',basis_condition='Near Mint',grading_company=None,grade=None,seal_status=None,
      market_value_minor=1200,method=SOLD,algorithm_version='drop-rate-market-v4',input_sale_count='5',reference_current=True,
      evidence_checked_at=NOW-timedelta(days=1),calculated_at=NOW-timedelta(hours=1),oldest_sale_at=NOW-timedelta(days=10))
    row.update(kw);return row

def test_value_independent_of_owner_record_and_money():
    reference=snapshot();a=item(owner_id='A',market_value_minor=1200,acquisition_cost_minor=100,store_price_minor=1500)
    b=item(owner_id='B',market_value_minor=None,acquisition_cost_minor=900,store_price_minor=2000)
    before=deepcopy((a,b,reference));assert resolve_reference_value(a,[reference],now=NOW)==resolve_reference_value(b,[reference],now=NOW)
    assert (a,b,reference)==before

@pytest.mark.parametrize('change',[{'basis_language':'English'},{'grade':'10','grading_company':'PSA','basis_condition':None},{'basis_condition':'Damaged'},{'catalogue_id':str(uuid4())},{'input_sale_count':'4'},{'reference_current':False},{'algorithm_version':'arbitrary'},{'market_value_minor':0},{'market_value_minor':-1},{'market_value_minor':True},{'evidence_checked_at':NOW+timedelta(seconds=1)},{'calculated_at':NOW+timedelta(seconds=1)}])
def test_wrong_or_unsupported_evidence_never_used(change):
    assert resolve_reference_value(item(),[snapshot(**change)],now=NOW)['market_value_minor'] is None

@pytest.mark.parametrize('changes',[{'evidence_checked_at':NOW-timedelta(days=8)},{'oldest_sale_at':NOW-timedelta(days=91)}])
def test_recalculation_does_not_revive_old_evidence(changes):
    result=resolve_reference_value(item(),[snapshot(**changes)],now=NOW)
    assert result['status']=='STALE' and result['market_value_minor'] is None and result['last_known_minor']==1200

def test_exact_grade_and_company_select_the_shared_slab_value():
    slab=item();slab.update(condition=None,grade='10',grading_company='PSA')
    exact=snapshot(grade='10',grading_company='PSA',basis_condition=None,market_value_minor=9900)
    rows=[snapshot(),exact,snapshot(grade='9',grading_company='PSA',basis_condition=None),snapshot(grade='10',grading_company='BGS',basis_condition=None)]
    assert resolve_reference_value(slab,rows,now=NOW)['market_value_minor']==9900
    slab['grading_company']='BGS';assert resolve_reference_value(slab,[exact],now=NOW)['market_value_minor'] is None

def test_sealed_never_inherits_card_value():
    pack=item();pack.update(product_type='SEALED',condition=None,seal_status='SEALED')
    assert resolve_reference_value(pack,[snapshot()],now=NOW)['market_value_minor'] is None
    result=resolve_reference_value(pack,[snapshot(basis_condition=None,seal_status='SEALED',market_value_minor=866)],now=NOW)
    assert result['market_value_minor']==866

def test_guide_is_labelled_and_never_substituted_for_a_slab_or_worn_card():
    guide=snapshot(method=GUIDE,basis_condition=None,input_sale_count='0',oldest_sale_at=None)
    for condition in ('Near Mint',None):
        raw=item();raw['condition']=condition
        assert resolve_reference_value(raw,[guide],now=NOW)['status']=='REFERENCE_ESTIMATE'
    for changes in ({'condition':'Damaged'},{'condition':None,'grade':'10','grading_company':'PSA'},{'condition':None,'product_type':'SEALED','seal_status':'SEALED'}):
        raw=item();raw.update(changes);assert resolve_reference_value(raw,[guide],now=NOW)['market_value_minor'] is None
    assert resolve_reference_value(item(),[guide,snapshot(market_value_minor=777)],now=NOW)['market_value_minor']==777

def test_details_missing_no_fake_zero_or_future_refresh_promise():
    raw=item();raw['condition']=None
    result=resolve_reference_value(raw,[snapshot()],now=NOW)
    assert result['status']=='NEEDS_DETAILS' and result['market_value_minor'] is None
    raw['language']='English';assert resolve_reference_value(raw,[snapshot()],now=NOW)['market_value_minor'] is None

def test_reference_totals_and_groups_do_not_promote_unknowns():
    data=[]
    for value in (1200,1200,None):
        row=item();row['market_value_minor']=value;row['reference_value']={'status':'AVAILABLE' if value else 'UNAVAILABLE'};data.append(row)
    result=reference_totals(data);assert result['valued_count']==2 and result['unvalued_count']==1 and result['total_minor']==2400
    assert reference_totals([data[2]])['total_minor'] is None
    groups=reference_top_groups(data);assert len(groups)==1 and groups[0]['holding_value_minor']==2400 and groups[0]['quantity']==2

@pytest.mark.parametrize('url',['https://cdn.shopify.com/x.png','https://assets.tcgdex.net/en/x.png'])
def test_direct_image_url_safe_hosts(url):assert direct_image_url(url)==url
@pytest.mark.parametrize('url',['http://cdn.shopify.com/x','https://cdn.shopify.com.evil.test/x','https://user:pass@cdn.shopify.com/x','https://127.0.0.1/x','https://cdn.shopify.com:81/x','javascript:alert(1)'])
def test_direct_image_url_rejects_unsafe(url):assert direct_image_url(url) is None
