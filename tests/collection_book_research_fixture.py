"""Researched book -> explicit intake -> owner-scoped artwork, with real PG/RLS."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from app import book_recognition as scanner
from app import book_research
from app.db import user_connection
from collection_book_scanner_fixture import photo


async def exercise(client,db,pool,headers,settings,ua,ub,owner_a):
    fields=dict(system_code='MARVEL_COMICS',series_title='Fixture Research Adventure',issue_number='1',
        publisher='Marvel',book_format='SINGLE_ISSUE',language='English',release_year=2025,
        printing_number=2,cover_code='Cover A',cover_artist=None,volume_identifier=None,barcode_gtin=None)
    candidate=dict(id='a'*24,fields=fields,source_url='https://www.marvel.com/comics/issue/1/fixture',
        source_title='Fixture publisher record',image_url='https://cdn.marvel.com/u/prod/marvel/i/mg/9/03/abcd/clean.jpg',
        cover_matches_photo=False,explanation='Synthetic publisher edition reference.')
    values={key:dict(value='',visible_text='',confidence=0) for key in scanner.BookFields.model_fields}
    for key in ('series_title','issue_number','language'):
        values[key]=dict(value=str(fields[key]),visible_text=str(fields[key]),confidence=.99)
    observed=scanner.BookObservation(object_type='BOOK',category='MARVEL_COMICS',book_format='SINGLE_ISSUE',
        confidence=.99,fields=values,warnings=[])
    response=SimpleNamespace(observation=observed,telemetry=SimpleNamespace(to_dict=lambda:{}))
    researched=dict(status='CANDIDATES',candidates=[candidate],message='Compare the cover.')
    before=await db.fetchval('select count(*) from tcg.inventory_items')
    with patch.object(scanner,'get_settings',return_value=settings), \
         patch.object(scanner.BookVisionClient,'observe_with_telemetry',AsyncMock(return_value=response)), \
         patch.object(scanner,'research_book',AsyncMock(return_value=deepcopy(researched))):
        r=await client.post('/api/v1/owner/books/recognize',json={'images':[photo('purple')]},headers=headers(ua,uuid4()))
    assert r.status_code==200,r.text
    result=r.json();run_id=UUID(result['run_id'])
    assert result['research']['selected_candidate_id']=='a'*24 and result['fields']['printing_number']==2
    assert result['research']['candidates'][0]['cover_matches_photo'] is False
    assert 'image_url' not in result['research']['candidates'][0] and result['auto_save'] is False
    assert await db.fetchval('select count(*) from tcg.inventory_items')==before
    cover=result['research']['candidates'][0]['image_path']
    with patch.object(scanner,'reference_thumbnail',AsyncMock(return_value=SimpleNamespace(data=b'fixture-image',content_type='image/webp'))):
        for actor,status in ((None,401),(ub,404),(ua,200)):
            r=await client.get(cover,headers=headers(actor,uuid4()) if actor else {})
            assert r.status_code==status,r.text
    payload=dict(research_run_id=str(run_id),research_candidate_id=result['research']['selected_candidate_id'],
        new_catalogue=dict(product_type='COMIC',game='Books',name=fields['series_title'],set_name=fields['series_title'],
            language='English',comic_printing={k:v for k,v in fields.items() if k!='language'}))
    path='/api/v1/owner/books/intake'
    # A different owner cannot borrow a private scan even for the same title.
    assert (await client.post(path,json=payload,headers=headers(ub,uuid4()))).status_code==422
    wrong=deepcopy(payload);wrong['new_catalogue']['comic_printing']['printing_number']=3
    assert (await client.post(path,json=wrong,headers=headers(ua,uuid4()))).status_code==422
    assert await db.fetchval('select count(*) from tcg.inventory_items')==before
    key=uuid4();r=await client.post(path,json=payload,headers=headers(ua,key))
    assert r.status_code==201,r.text
    saved=r.json();inventory_id=UUID(saved['inventory']['id']);catalogue_id=UUID(saved['catalogue']['id'])
    replay=await client.post(path,json=payload,headers=headers(ua,key))
    assert replay.status_code==201 and replay.json()['inventory']['id']==str(inventory_id),replay.text
    assert await db.fetchval('select count(*) from tcg.inventory_items')==before+1
    assert await db.fetchval("select count(*) from tcg.recognition_runs where idempotency_key=$1",f'book-reference:{inventory_id}')==1
    row=await db.fetchrow('select status,sale_intent,identity_confirmed,market_value_minor from tcg.inventory_items where id=$1',inventory_id)
    assert dict(row)==dict(status='DRAFT',sale_intent='PERSONAL_COLLECTION',identity_confirmed=False,market_value_minor=None)
    async with user_connection(pool,ua,'book-reference-own') as conn:
        items=[dict(id=inventory_id,catalogue_id=catalogue_id,product_type='COMIC')]
        await book_research.add_saved_book_artwork(conn,items)
        assert items[0]['reference_image_url']==candidate['image_url']
    async with user_connection(pool,ub,'book-reference-foreign') as conn:
        items=[dict(id=inventory_id,catalogue_id=catalogue_id,product_type='COMIC')]
        await book_research.add_saved_book_artwork(conn,items)
        assert 'reference_image_url' not in items[0]
    await db.execute('update tcg.comic_printing_details set printing_number=3 where catalogue_id=$1',catalogue_id)
    async with user_connection(pool,ua,'book-reference-stale') as conn:
        items=[dict(id=inventory_id,catalogue_id=catalogue_id,product_type='COMIC')]
        await book_research.add_saved_book_artwork(conn,items)
        assert 'reference_image_url' not in items[0]
    print('PASS: cited book review, private covers, edited/foreign scan rejection, explicit intake, retry, persistent reference, identity invalidation and owner RLS.')
