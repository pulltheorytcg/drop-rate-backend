import json
from urllib.parse import parse_qs,urlsplit

import pytest

from app import fusion_official_rarity as rarity
from app import drop_rate_daily_model as model
from app.reference_feeds import ReferenceFeedError
from datetime import datetime,timezone
from test_book_connector_import import run_sql

URL='https://www.dbs-cardgame.com/fw/en/cardlist/?search=true&category%5B%5D=583001&rarity%5B%5D=C'


def page(*, locale='en', code='C', count=1, variant=''):
    marker='Result' if locale=='en' else '検索結果'
    return (f'<input name="rarity[]" value="{code}" checked>'
        f'{marker}<span class="num">{count}</span>'
        '<a class="cardStr" data-src="detail.php?card_no=FB01-003'+variant+'">'
        '<img alt="FB01-003 Vados" data-src="../../images/cards/card/'+locale+'/FB01-003.webp"></a>')


def card():
    return dict(provider_id='583001:FB01-003',card_number='FB01-003',name='Vados',
        image_url='https://www.dbs-cardgame.com/fw/images/cards/card/en/FB01-003.webp',
        source_url='https://www.dbs-cardgame.com/fw/en/cardlist/detail.php?card_no=FB01-003',
        evidence={'provider_variant':'','physical_finish_unresolved':True})


def test_official_filter_confirms_exact_rarity_and_preserves_physical_uncertainty():
    sources=rarity.filtered_cards(page(),url=URL,set_id='583001',rarity='C')
    original=card()
    enriched=rarity.attach_rarities([original],sources,set_id='583001',language='English')[0]
    assert enriched['rarity']=='C' and 'rarity' not in original
    assert enriched['evidence']['physical_finish_unresolved'] is True
    receipt=enriched['evidence']['rarity_reference']
    assert receipt['filtered_source_url']==URL and len(receipt['source_sha256'])==64
    assert receipt['reference_identity']['name']=='Vados'


@pytest.mark.parametrize('content',[
    page(code='UC'),page(count=2),page().replace(' checked',''),page().replace('Result','Changed'),
    page()+'<input name="rarity[]" value="UC" checked>',
])
def test_unconfirmed_filter_or_incomplete_checklist_is_rejected(content):
    with pytest.raises(ReferenceFeedError):
        rarity.filtered_cards(content,url=URL,set_id='583001',rarity='C')


def test_japanese_count_and_source_locale_are_verified():
    url=URL.replace('/en/','/jp/').replace('583001','584001')
    assert len(rarity.filtered_cards(page(locale='jp'),url=url,set_id='584001',rarity='C'))==1
    with pytest.raises(ReferenceFeedError):
        rarity.filtered_cards(page(locale='jp'),url=URL,set_id='584001',rarity='C')
    with pytest.raises(ReferenceFeedError):
        rarity.filtered_cards(page(locale='jp',count=2),url=url,set_id='584001',rarity='C')


@pytest.mark.parametrize('field,value',[
    ('provider_id','583001:FB01-003_p1'),('name','Another card'),('card_number','FB01-004'),
    ('image_url','https://www.dbs-cardgame.com/fw/images/cards/card/en/FB01-003_p1.webp'),
    ('source_url','https://www.dbs-cardgame.com/fw/en/cardlist/detail.php?card_no=FB01-003&p=_p1'),
    ('rarity','SR'),('evidence',{'provider_variant':'_p1'}),
])
def test_metadata_does_not_cross_identity_variant_or_conflicting_rarity(field,value):
    sources=rarity.filtered_cards(page(),url=URL,set_id='583001',rarity='C')
    target=dict(card(),**{field:value})
    result=rarity.attach_rarities([target],sources,set_id='583001',language='English')[0]
    assert 'rarity_reference' not in result.get('evidence',{})


def test_conflicting_or_duplicate_source_classifications_remain_unresolved():
    source=rarity.filtered_cards(page(),url=URL,set_id='583001',rarity='C')[0]
    other=dict(source,rarity='UC')
    assert 'rarity' not in rarity.attach_rarities([card()],[source,other],set_id='583001',language='English')[0]
    assert 'rarity' not in rarity.attach_rarities([card()],[source],set_id='584001',language='Japanese')[0]


def test_inventory_displays_same_formula_only_with_current_exact_fusion_receipt():
    from app.inventory_catalogue_reference import computed_catalogue_guide
    from app.reference_baseline_model import Printing,PeerGuide,ordinary_peer_baseline
    source=rarity.filtered_cards(page(),url=URL,set_id='583001',rarity='C')
    row=rarity.attach_rarities([card()],source,set_id='583001',language='English')[0]
    row.update(provider='Bandai Official',system_code='DRAGON_BALL_SUPER_FUSION_WORLD',
               language='English',set_id='583001',set_name='AWAKENED PULSE')
    now=datetime.now(timezone.utc)
    peers=[PeerGuide(Printing(row['provider'],row['system_code'],row['set_id'],f'583001:FB01-{n:03}',
        'English','STANDARD','C'),n,now,'CARDMARKET_BULK_SINGLES') for n in range(4,10)]
    estimate=ordinary_peer_baseline(model._printing(row),peers,now=now)
    quote=model._quote(row,estimate,now,peers)
    assert quote['algorithm_version']==1 and model.REVISION==2
    value=computed_catalogue_guide(row,[quote],'English',now=now)
    assert value['market_value_minor']==estimate.estimate_minor and not value['physical_valuation_eligible']
    for changed in (dict(row,image_url='changed'),dict(row,rarity='UC'),dict(row,evidence={}),dict(row,provider_id='583001:FB01-003_p1')):
        assert computed_catalogue_guide(changed,[quote],'English',now=now) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_filter',[False,True])
async def test_daily_import_keeps_verified_rarity_and_holds_failed_source_sets(bad_filter):
    from app.reference_public import bandai_feed
    class Feed:
        failures=[]
        async def get_text(self,url,**params):
            query=parse_qs(urlsplit(url).query)
            locale='jp' if '/jp/' in url else 'en'
            sid='584001' if locale=='jp' else '583001'
            if 'category[]' not in query:
                return f'<a data-val="{sid}">Booster FB01</a>'
            if query.get('rarity[]')==['UC']:
                marker='検索結果' if locale=='jp' else 'Result'
                return f'<input name="rarity[]" value="UC" checked>{marker}<span>0</span>'
            return page(locale=locale,count=2 if bad_filter and query.get('rarity[]') else 1)
    feed=Feed(); feed.failures=[]
    groups=[(record,cards) async for record,cards in bandai_feed(feed,fusion=True)]
    if bad_filter:
        assert groups==[] and len(feed.failures)==2
    else:
        assert len(groups)==2 and not feed.failures
        assert all(cards[0]['rarity']=='C' for record,cards in groups)
        assert all(cards[0]['evidence']['rarity_reference']['reference_identity']['language']==record['language']
                   for record,cards in groups)


def test_live_database_guards_and_model_sql_only_accept_verified_base_card(tmp_path):
    source=rarity.filtered_cards(page(),url=URL,set_id='583001',rarity='C')
    enriched=rarity.attach_rarities([card()],source,set_id='583001',language='English')[0]
    entry=dict(enriched,language='English',set_id='583001',receipt=enriched['evidence']['rarity_reference'])
    setup="""create schema art_test;
      create table art_test.reference_cards(provider text,system_code text,language text,provider_id text,
       set_id text,name text,card_number text,source_url text,image_url text,rarity text,evidence jsonb);
      create table art_test.reference_sets(provider text,system_code text,language text,set_id text,name text,release_date date);
      create table art_test.reference_market_prices(provider text,system_code text,language text,provider_id text,
       market_value_minor int,pricing_updated_at timestamptz,quotes jsonb);
      create table art_test.reference_catalogue_prices(like art_test.reference_market_prices);
      insert into art_test.reference_sets values('Bandai Official','DRAGON_BALL_SUPER_FUSION_WORLD','English','583001','AWAKENED PULSE','2024-02-23');
      insert into art_test.reference_cards values('Bandai Official','DRAGON_BALL_SUPER_FUSION_WORLD','English','583001:FB01-003',
       '583001','Vados','FB01-003','https://www.dbs-cardgame.com/fw/en/cardlist/detail.php?card_no=FB01-003',
       'https://www.dbs-cardgame.com/fw/images/cards/card/en/FB01-003.webp',null,'{"provider_variant":"","physical_finish_unresolved":true}');"""
    def write(row):
        return rarity.WRITE_SQL.replace('tcg.','art_test.').replace('$1',"'"+json.dumps([row]).replace("'","''")+"'")
    candidates=model.CANDIDATE_SQL.replace('tcg.','art_test.').replace('$1',"''").replace('$2','100')
    cohort=json.dumps([dict(provider='Bandai Official',system_code='DRAGON_BALL_SUPER_FUSION_WORLD',language='English',set_id='583001',rarity='C')])
    peers=model.PEER_SQL.replace('tcg.','art_test.').replace('$1',"'"+cohort+"'")
    steps=[candidates,write(dict(entry,name='Wrong name')),write(entry),write(entry),candidates,peers,
        "update art_test.reference_cards set evidence=jsonb_set(evidence,'{provider_variant}','\"_p1\"')",candidates]
    result=run_sql(tmp_path,steps,setup=setup,inspect='select rarity from art_test.reference_cards')
    assert all(r['ok'] for r in result['results']),result
    rows=[r['rows'] for r in result['results']]
    assert rows[0]==[] and [rows[i][0]['written'] for i in (1,2,3)]==[0,1,0]
    assert len(rows[4])==len(rows[5])==1 and rows[7]==[]
