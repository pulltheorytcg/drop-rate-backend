import json
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from app.book_research import (ResearchAnswer, accepted_candidates, identity_digest,
    prepare_research_result, public_result, publisher_source, research_book, add_saved_book_artwork,
    publisher_page_cover, source_cover_matches)
from app.owner_books import BookIntakeRequest

SOURCE = 'https://www.marvel.com/comics/issue/129606/marveldc_deadpoolbatman_1_2025_1'
COVER = 'https://cdn.marvel.com/u/prod/marvel/i/mg/9/03/68aefe0f5edd4/clean.jpg'


def candidate(**updates):
    row = dict(fields=dict(system_code='MARVEL_COMICS',series_title='Deadpool/Batman',issue_number='1',
        publisher='Marvel',book_format='SINGLE_ISSUE',language='English',volume_identifier=None,
        release_year=2025,printing_number=None,cover_code=None,cover_artist=None,barcode_gtin=None),
        source_url=SOURCE,source_title='Deadpool/Batman #1',image_url=COVER,
        cover_matches_photo=True,explanation='Compare this publisher cover with your copy.')
    row.update(updates)
    return row


def response(*candidates):
    return {'output_text':json.dumps({'candidates':list(candidates or [candidate()])}),
        'output':[{'type':'web_search_call','action':{'type':'search','sources':[{'url':SOURCE}]}}]}


def observed(**kwargs):
    return dict(series_title='Deadpool / Batman',issue_number='1',system_code='MARVEL_COMICS',language='English',**kwargs)


def test_only_retrieved_publisher_records_become_candidates():
    found = accepted_candidates(response(),observed())
    assert len(found)==1 and found[0]['fields']['release_year']==2025
    assert found[0]['fields']['printing_number'] is None
    for url in ('https://evil.test/comics/issue/1','https://www.marvel.com.evil.test/comics/issue/1',
                'https://www.marvel.com@evil.test/comics/issue/1','http://www.marvel.com/comics/issue/1',
                'https://www.marvel.com/comics/issue/1?url=https://evil.test','https://www.marvel.com:8443/comics/issue/1'):
        assert publisher_source(url) is None
        assert not accepted_candidates(response(candidate(source_url=url)),observed())
    missing = response(); missing['output']=[]
    assert not accepted_candidates(missing,observed())
    missing = response(); missing['output'][0]['action']['sources']=[]
    assert not accepted_candidates(missing,observed())


@pytest.mark.parametrize('field,value',[('issue_number','2'),('language','Japanese'),
    ('system_code','DC_COMICS'),('printing_number',2),('release_year',2024),('barcode_gtin','036000291452')])
def test_research_cannot_overwrite_visible_identity_conflicts(field,value):
    row=candidate(); row['fields'][field]=value
    photo=observed(); photo.update(printing_number=1,release_year=2025,barcode_gtin='03600029145200111')
    assert not accepted_candidates(response(row),photo)


def test_image_host_is_bound_to_source_and_duplicate_editions_are_not_choices():
    for image in ('https://evil.test/cover.jpg','https://static.dc.com/2026-10/Batman.jpg',
                  'https://cdn.marvel.com/u/prod/marvel/i/mg/9/03/abcd/clean.jpg?redirect=evil'):
        found=accepted_candidates(response(candidate(image_url=image)),observed())
        assert found[0]['image_url'] is None and not found[0]['cover_matches_photo']
    assert len(accepted_candidates(response(candidate(),candidate()),observed()))==1
    other = candidate(image_url='https://cdn.marvel.com/u/prod/marvel/i/mg/9/03/abcd/clean.jpg')
    assert len(accepted_candidates(response(candidate(),other),observed()))==2


def test_visual_suggestion_prefills_but_does_not_approve_save_or_price():
    result=dict(status='NEEDS_REVIEW',fields=observed(printing_number=2),uncertain_fields=['release_year','printing_number'],auto_save=False,market_value_minor=None)
    found=accepted_candidates(response(),result['fields'])
    result=prepare_research_result(result,{'candidates':found},uuid4())
    assert result['fields']['release_year']==2025 and result['fields']['printing_number']==2
    assert result['status']=='NEEDS_REVIEW' and not result['auto_save'] and result['market_value_minor'] is None
    assert result['research']['selected_candidate_id']==found[0]['id']
    assert 'image_url' not in public_result(result)['research']['candidates'][0]
    assert found[0]['image_url']==COVER
    two=prepare_research_result({'fields':observed(),'uncertain_fields':[]},{'candidates':[deepcopy(found[0]),deepcopy(found[0])]},uuid4())
    assert 'selected_candidate_id' not in two['research'] and 'release_year' not in two['fields']


@pytest.mark.asyncio
async def test_request_uses_existing_model_cited_bounded_search_and_no_private_identifiers():
    requests=[]
    def reply(request):
        requests.append(json.loads(request.content)); return httpx.Response(200,json=response())
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        result=await research_book(observed(certificate_number='PRIVATE-123',label_notes='Private name'),['data:image/jpeg;base64,fixture'],
                                   api_key='fixture',model='configured-model',http_client=http)
    assert result['status']=='CANDIDATES'
    body=requests[0]; assert body['model']=='configured-model' and not body['store']
    assert body['max_tool_calls']==3 and body['include']==['web_search_call.action.sources']
    assert body['tools'][0]['filters']['allowed_domains']
    assert 'PRIVATE-123' not in json.dumps(body) and 'Private name' not in json.dumps(body)
    schema=body['text']['format']['schema']
    for part in [schema,*schema['$defs'].values()]:
        assert part['additionalProperties'] is False and set(part['required'])==set(part['properties'])


@pytest.mark.asyncio
@pytest.mark.parametrize('code,payload',[(429,{}),(503,{}),(400,{}),(200,{'output_text':'invalid'}),
    (200,{'output_text':'{"candidates":[{"price":999}]}','output':[{'type':'web_search_call'}]})])
async def test_provider_failure_does_not_destroy_cover_ocr(code,payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(code,json=payload))) as http:
        result=await research_book(observed(),[],api_key='fixture',model='fixture',http_client=http)
    assert result['status']=='UNAVAILABLE' and result['candidates']==[]


@pytest.mark.asyncio
async def test_unreadable_issue_is_researched_without_promoting_tentative_ocr():
    calls = []
    def reply(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response())
    fields = observed(); fields.pop('issue_number')
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        research = await research_book(fields, ['data:image/jpeg;base64,photo'], api_key='fixture',
            model='fixture', tentative_fields={'issue_number':'304','certificate_number':'PRIVATE'}, http_client=http)
    sent = json.loads(calls[0]['input'][0]['content'][0]['text'])
    assert sent['tentative_fields'] == {'issue_number':'304'}
    assert 'issue_number' not in sent['observed_fields']
    assert research['status'] == 'CANDIDATES'
    research['candidates'][0]['cover_matches_photo'] = False
    result = prepare_research_result({'fields':fields,'uncertain_fields':['issue_number']}, research, uuid4())
    assert 'issue_number' not in result['fields']
    assert 'selected_candidate_id' not in result['research']


def test_exact_issue_prefills_source_metadata_without_claiming_cover_confirmation():
    result = dict(fields=observed(), uncertain_fields=['release_year'], auto_save=False)
    found = accepted_candidates(response(candidate(image_url=None, cover_matches_photo=False)), observed())
    result = prepare_research_result(result, {'candidates':found}, uuid4())
    assert result['fields']['release_year'] == 2025
    assert result['auto_save'] is False and 'selected_candidate_id' not in result['research']


DC_SOURCE = 'https://www.dcuniverseinfinite.com/comics/book/batman-1940-463/cd396b6b-50f5-4741-99df-16c0f1f26fa9'
DC_COVER = 'https://imgix-media.wbdndc.net/ingest/book/preview/cd396b6b-50f5-4741-99df-16c0f1f26fa9/d5d88c05-af46-42cc-b3eb-e33a4faab49b/0.jpg?auto=format%2Ccompress&fill=blur&fit=fill&h=576&sharp=50&w=375'


def test_dc_archive_cover_is_bound_to_that_exact_issue_and_public_preview():
    assert publisher_source(DC_SOURCE) == DC_SOURCE
    assert source_cover_matches(DC_SOURCE, DC_COVER)
    assert not source_cover_matches(DC_SOURCE.replace('cd396b6b','aa396b6b'), DC_COVER)
    for url in (DC_COVER.replace('/0.jpg','/1.jpg'),DC_COVER+'&url=https://evil.test',
                DC_COVER.replace('w=375','w=9999'),DC_COVER.replace('wbdndc.net','wbdndc.net.evil.test')):
        assert not source_cover_matches(DC_SOURCE, url)


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['', 'wrong-issue', 'wrong-page', 'wrong-host', 'denied', 'redirect', 'huge'])
async def test_publisher_metadata_recovers_exact_cover_and_rejects_unsafe_pages(bad):
    row=candidate(); row['image_url']=None
    title='Deadpool/Batman #1' if bad != 'wrong-issue' else 'Deadpool/Batman #2'
    source=SOURCE if bad != 'wrong-page' else SOURCE.replace('/129606/', '/129607/')
    image=COVER if bad != 'wrong-host' else 'https://evil.test/cover.jpg'
    page=f'<meta property="og:title" content="{title}"><meta property="og:url" content="{source}"><meta property="og:image" content="{image}">'
    if bad=='huge':page=' ' * 1_500_001 + page
    calls=[]
    def reply(request):
        calls.append(request)
        return httpx.Response(403 if bad=='denied' else 302 if bad=='redirect' else 200,
            text=page,headers={'content-type':'text/html','location':'https://evil.test'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        cover=await publisher_page_cover(row,http_client=http)
    assert cover == (COVER if not bad else None)
    assert len(calls)==1 and 'authorization' not in calls[0].headers


def test_reference_identity_includes_printing_cover_and_language():
    fields=candidate()['fields']; first=identity_digest(fields)
    for key,value in [('printing_number',2),('cover_code','Variant B'),('language','Japanese')]:
        assert identity_digest({**fields,key:value})!=first
    assert identity_digest({**fields,'publisher':'MARVEL'})==first


@pytest.mark.asyncio
async def test_reviewed_publisher_covers_skip_slow_search_without_approving_a_copy():
    from app.book_research import reviewed_candidates, reviewed_scan_references
    assert len(reviewed_scan_references()) == 19
    for title, issue, system in [('Amazing Spider-Man','528','MARVEL_COMICS'),
            ('The Amazing Spider-Man','795','MARVEL_COMICS'),('Batman','463','DC_COMICS'),
            ('One Piece','1','MANGA'),('Peter Parker The Spectacular Spider-Man','114','MARVEL_COMICS'),
            ('Peter Parker, The Spectacular Spider-Man','11','MARVEL_COMICS')]:
        fields=dict(series_title=title,issue_number=issue,system_code=system,language='English')
        def unexpected(_): raise AssertionError('Reviewed reference must not start another web search')
        async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
            found=await research_book(fields,['photo'],api_key='fixture',model='fixture',http_client=http)
        assert found['status']=='CANDIDATES' and len(found['candidates'])==1
        cover=found['candidates'][0]
        assert source_cover_matches(cover['source_url'],cover['image_url'])
        assert cover['fields']['printing_number'] is None and not cover['cover_matches_photo']
        ready=prepare_research_result(dict(fields=fields,uncertain_fields=['printing_number'],auto_save=False),found,uuid4())
        assert 'selected_candidate_id' not in ready['research'] and not ready['auto_save']
        assert not reviewed_candidates({**fields,'language':'Japanese'})
        assert not reviewed_candidates({**fields,'release_year':2100})
        assert not reviewed_candidates({**fields,'issue_number':'unreadable'})
    assert not reviewed_candidates(dict(series_title='Amazing Spider-Man',system_code='MARVEL_COMICS'))


@pytest.mark.asyncio
async def test_marvel_slug_change_and_published_image_sizes_keep_exact_issue_binding():
    from app.book_artwork import publisher_cover_url
    from app.book_research import same_publisher_record
    canonical='https://www.marvel.com/comics/issue/129606/deadpool-batman-2025-1'
    image=COVER.replace('/clean.jpg','/portrait_uncanny.jpg')
    assert publisher_cover_url(image.replace('cdn.marvel.com','i.annihil.us'))
    assert not publisher_cover_url(image.replace('cdn.marvel.com','i.annihil.us.evil.test'))
    assert publisher_cover_url(image) and publisher_cover_url(COVER.replace('/clean.jpg','/background.jpg'))
    assert same_publisher_record(SOURCE,canonical)
    assert not same_publisher_record(SOURCE,canonical.replace('/129606/','/129607/'))
    for bad in ('?url=https://evil.test','#secret','/../private.jpg'):
        assert not publisher_cover_url(image+bad)
    page=f'<meta property="og:title" content="Deadpool/Batman #1"><meta property="og:url" content="{canonical}"><meta property="og:image" content="{image}">'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,text=page,headers={'content-type':'text/html'}))) as http:
        assert await publisher_page_cover(candidate(image_url=None),http_client=http)==image


@pytest.mark.parametrize('fields',[
    dict(series_title='Peter Parker, The Spectacular Spider-Man',issue_number='11',release_year=1977,cover_code='02199'),
    dict(series_title='Peter Parker, The Spectacular Spider-Man',issue_number='114',cover_artist='Pollard'),
    dict(series_title='The Amazing Spider-Man',issue_number='528',release_year=2006,volume_identifier='1999',cover_code='DIRECT EDITION'),
    dict(series_title='The Amazing Spider-Man',issue_number='795',release_year=2018,volume_identifier='2015 series',barcode_gtin='75960608765579511',cover_artist='Alex Ross'),
])
def test_recorded_public_book_fields_resolve_cover_without_losing_copy_evidence(fields):
    from app.book_research import reviewed_candidates
    observed={**fields,'system_code':'MARVEL_COMICS','language':'English','publisher':'Marvel','book_format':'SINGLE_ISSUE'}
    found=reviewed_candidates(observed)
    assert len(found)==1 and found[0]['image_url'] and not found[0]['cover_matches_photo']
    for key in ('issue_number','release_year','volume_identifier','cover_code','barcode_gtin','cover_artist'):
        if key in fields: assert found[0]['fields'][key]==fields[key]


@pytest.mark.asyncio
async def test_cached_cover_cannot_be_reused_for_a_conflicting_issue(monkeypatch):
    from collections import OrderedDict
    from app import book_research
    monkeypatch.setattr(book_research, '_cover_cache', OrderedDict())
    page=f'<meta property="og:title" content="Deadpool/Batman #1"><meta property="og:url" content="{SOURCE}"><meta property="og:image" content="{COVER}">'
    calls=[]
    def reply(request):
        calls.append(request)
        return httpx.Response(200,text=page,headers={'content-type':'text/html'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        monkeypatch.setattr(book_research, '_shared_http_client', lambda: http)
        assert await publisher_page_cover(candidate()) == COVER
        wrong=candidate(); wrong['fields']['issue_number']='2'
        assert await publisher_page_cover(wrong) is None
        assert await publisher_page_cover(candidate()) == COVER
    assert len(calls)==2


@pytest.mark.asyncio
async def test_saved_artwork_requires_current_identity_and_remains_reference_only():
    item=dict(id=uuid4(),catalogue_id=uuid4(),product_type='COMIC')
    fields=candidate()['fields']; row={**fields,'inventory_id':item['id'],
        'attributes':{'publisher':'Marvel','book_format':'SINGLE_ISSUE'},
        'provider_evidence':{'book_reference':candidate(),'identity_digest':identity_digest(fields)}}
    class DB:
        async def fetch(self,sql,ids):
            assert 'i.owner_id=r.owner_id' in sql and ids==[item['id']]
            return [row]
    await add_saved_book_artwork(DB(),[item])
    assert item['reference_image_url']==COVER and item['artwork_kind']=='COLLECTOR_CONFIRMED_PUBLISHER_REFERENCE'
    assert 'identity_confirmed' not in item and 'market_value_minor' not in item and 'image_url' not in item
    row['printing_number']=2
    changed={k:v for k,v in item.items() if k in ('id','catalogue_id','product_type')}
    await add_saved_book_artwork(DB(),[changed])
    assert 'reference_image_url' not in changed
