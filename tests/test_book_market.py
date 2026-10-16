from datetime import datetime,timedelta,timezone
from uuid import uuid4

import pytest
from app import book_market as books, live_market_refresh as market
from app.catalogue_valuations import catalogue_values
from app.inventory_reference_values import resolve_reference_value, SOLD

NOW=datetime(2026,10,16,18,tzinfo=timezone.utc)
TITLE='Fixture Hero #1 Marvel 2022 English first printing Cover A Near Mint'


def target(**changes):
    book=dict(system_code='MARVEL_COMICS',series_title='Fixture Hero',issue_number='1',volume_identifier=None,
              printing_number=1,release_year=2022,cover_code='Cover A',cover_artist=None,barcode_gtin=None,
              publisher='Marvel',book_format='SINGLE_ISSUE',identity_status='VERIFIED',profile_status='VERIFIED')
    value=dict(catalogue_id=uuid4(),product_type='COMIC',game='Marvel Comics',name='Fixture Hero #1',
        set_name='Fixture Hero (2022)',card_number='1',variant='Single Issue Cover A Printing 1',rarity='',
        language='English',condition='Near Mint',grading_company=None,grade=None,seal_status=None,
        book_printing=book,book_identity_digest=books.printing_digest(book),identity_confirmed=True,
        profile_identity_status='VERIFIED')
    return dict(value,**changes)


def sale(n=1,**changes):
    return dict(dict(item_id=str(6000+n),title=TITLE,sale_price=10+n,shipping_price=2,currency='GBP',
        date_sold=(NOW-timedelta(days=n)).isoformat(),condition_raw='Near Mint'),**changes)


@pytest.mark.parametrize('title',[
    TITLE.replace('#1','#2'),TITLE.replace('2022','2023'),TITLE+' 2023 reprint',
    TITLE.replace('first','second'),TITLE+' second printing',TITLE.replace('Cover A','Cover B'),
    TITLE+' Cover B',TITLE+' newsstand',TITLE+' signed',TITLE+' restored',TITLE+' qualified',
    TITLE+' facsimile',TITLE+' x2',TITLE+' bundle',TITLE+' issues 1-5',TITLE+' Japanese',
    TITLE.replace('English',''),TITLE.replace('Marvel','DC'),TITLE.replace('Near Mint','Very Good'),
    TITLE+' CGC 9.8',TITLE+' #2',TITLE+' Annual',TITLE+' preview',TITLE+' 3-in-1',TITLE.replace('Fixture Hero','Fixture Heroine'),
])
def test_near_matches_are_not_sales_evidence(title):
    assert not books.exact_match(sale(title=title),target())


def test_positive_raw_and_graded_match_and_conflicting_labels():
    t=target();assert books.exact_match(sale(),t)
    t.update(condition=None,grading_company='CGC',grade='9.8')
    graded=TITLE.replace('Near Mint','CGC 9.8')
    assert books.exact_match(sale(title=graded),t)
    for suffix in (' BGS',' PSA 10',' raw',' potential',' signature series',' purple label'):
        assert not books.exact_match(sale(title=graded+suffix),t)
    assert not books.exact_match(sale(title=graded.replace('9.8','9.6')),t)


def test_manga_requires_volume_printing_language_edition_and_isbn():
    t=target();t['book_printing'].update(system_code='MANGA',series_title='Fixture Manga',publisher='VIZ Media',
        book_format='MANGA',cover_code=None,release_year=2003,barcode_gtin='9781566199094')
    title='Fixture Manga Volume 1 VIZ Media 2003 English first printing ISBN 9781566199094 Near Mint'
    assert books.exact_match(sale(title=title),t)
    for replacement in (title.replace('Volume 1','Volume 2'),title+' omnibus',title.replace('English','Japanese'),
                        title.replace('9781566199094','97815661990949'),title.replace('first printing','')):
        assert not books.exact_match(sale(title=replacement),t)
    t.update(condition=None,grading_company='BGS',grade='9.5')
    assert books.exact_match(sale(title=title.replace('Near Mint','BGS 9.5')),t)


def test_printing_approval_special_state_and_condition_are_required():
    for changes in ({'identity_status':'NEEDS_REVIEW'},{'profile_status':'NEEDS_REVIEW'},
                    {'printing_number':None},{'release_year':None},{'cover_code':None}):
        t=target();t['book_printing'].update(changes)
        assert books.eligibility(t)
    for changes in ({'condition':None},{'notes':'Signed by artist'},{'grading_company':'BGS','grade':'9.5','condition':None}):
        assert books.eligibility(target(**changes))


def test_duplicate_wrong_market_stale_and_invalid_money_are_excluded():
    t=target();rows=[sale(n) for n in range(1,6)]
    payload=dict(site='EBAY_GB',currency='GBP',results=rows)
    comps=market.select_comps(payload,t,NOW)
    assert len(comps)==5 and market.value_comps(comps,t,now=NOW).market_value_minor>0
    for bad in ({'sale_price':'NaN'},{'sale_price':'1e1000'},{'shipping_price':-1},{'currency':'USD'},
                {'date_sold':(NOW+timedelta(days=1)).isoformat()},{'date_sold':(NOW-timedelta(days=91)).isoformat()}):
        assert not books.select_comps(dict(payload,results=[sale(**bad)]),t,NOW)
    assert not books.select_comps(dict(payload,results=[sale(),sale()]),t,NOW)
    with pytest.raises(ValueError): books.select_comps(dict(payload,site='EBAY_US'),t,NOW)
    with pytest.raises(ValueError): market.value_comps(comps[:4],t,now=NOW)


def test_shared_values_require_exact_book_digest_and_remain_owner_independent():
    t=target();observations=[]
    for n in range(1,6):
        row=sale(n)
        observations.append(dict(id=uuid4(),catalogue_id=t['catalogue_id'],source='EBAY',observation_type='SOLD',source_country='GB',
            currency='GBP',observed_at=NOW-timedelta(days=n),ingested_at=NOW-timedelta(hours=1),price_gbp_minor=(10+n)*100,
            shipping_gbp_minor=200,condition='Near Mint',grading_company=None,grade=None,language='English',seal_status=None,
            metadata=dict(selection_rule='FIVE_NEWEST_EXACT_BOOK_SALES',marketplace='EBAY_GB',provider_item_id=row['item_id'],
                title=TITLE,book_identity_digest=t['book_identity_digest'])))
    values=catalogue_values(t,observations,now=NOW);assert len(values)==1
    evidence=values[0]['evidence']
    row=dict(snapshot_id=uuid4(),catalogue_id=t['catalogue_id'],basis_language='English',basis_condition='Near Mint',
        grading_company=None,grade=None,seal_status=None,market_value_minor=values[0]['result'].market_value_minor,
        method=SOLD,algorithm_version='drop-rate-market-v4',input_sale_count=5,reference_current=True,
        evidence_checked_at=NOW-timedelta(hours=1),calculated_at=NOW,oldest_sale_at=NOW-timedelta(days=5),
        book_identity_digest=evidence['book_identity_digest'])
    a=resolve_reference_value(dict(t,owner_id='A'),[row],now=NOW)
    assert a['status']=='AVAILABLE' and a==resolve_reference_value(dict(t,owner_id='B',store_price_minor=99999),[row],now=NOW)
    assert resolve_reference_value(dict(t,notes='Restored spine'),[row],now=NOW)['market_value_minor'] is None
    assert resolve_reference_value(t,[dict(row,book_identity_digest='wrong')],now=NOW)['market_value_minor'] is None
    assert not catalogue_values(t,[dict(r,metadata={}) for r in observations],now=NOW)
    original_key=market.identity_key(t)
    t['book_printing']['printing_number']=2
    assert market.identity_key(t)!=original_key
    assert not catalogue_values(t,observations,now=NOW)
