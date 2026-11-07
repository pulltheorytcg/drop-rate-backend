"""Real generic scan HTTP -> private book receipt -> original-photo research."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from app import recognition, book_recognition
from app.recognition_vision import RecognitionObservation
from collection_book_scanner_fixture import photo
from test_book_recognition import observed
from test_recognition_vision_transport import observation_payload


async def exercise(client,db,headers,settings,ua,ub):
    book=observed(series_title='Fixture auto comic',issue_number='7',language='English',publisher='Marvel')
    book=book.model_copy(update={'category':'MARVEL_COMICS','book_format':'SINGLE_ISSUE'})
    observation=RecognitionObservation.model_validate({**observation_payload(), 'object_type':'BOOK',
        'game':'Unknown','card_number':'','book':book.model_dump()})
    response=SimpleNamespace(observation=observation,telemetry=SimpleNamespace(request_ms=12,to_dict=lambda:{'request_ms':12}))
    vision=AsyncMock(return_value=response)
    fallback=AsyncMock(return_value=SimpleNamespace(observation=book,telemetry=response.telemetry))
    lookup=AsyncMock(return_value={'status':'UNAVAILABLE','candidates':[],'message':'Fixture finished'})
    before=await db.fetchval('select count(*) from tcg.inventory_items')
    image=photo('navy');path='/api/v1/recognition/resolve'
    with patch.object(recognition,'get_settings',return_value=settings), \
         patch.object(book_recognition,'get_settings',return_value=settings), \
         patch.object(recognition,'discover_reference_candidate_hints',AsyncMock(return_value=[])), \
         patch.object(recognition.OpenAIRecognitionVisionClient,'observe_with_telemetry',vision), \
         patch.object(book_recognition.BookVisionClient,'observe_with_telemetry',fallback), \
         patch.object(book_recognition,'research_book',lookup):
        assert (await client.post(path,json={'image_data_url':image})).status_code==401
        r=await client.post(path,json={'image_data_url':image},headers=headers(ua,uuid4()))
        assert r.status_code==200,r.text
        data=r.json(); result=data['book_result']; rid=result['run_id']
        assert result['fields']['issue_number']=='7' and result['research']['status']=='PENDING'
        assert data['candidates']==[] and data['auto_applied'] is False
        vision.assert_awaited_once(); fallback.assert_not_awaited(); lookup.assert_not_awaited()
        replay=await client.post(path,json={'image_data_url':image},headers=headers(ua,uuid4()))
        assert replay.json()['book_result']==result and vision.await_count==1
        receipt=f'/api/v1/owner/books/recognize/{rid}';research=f'/api/v1/owner/books/research/{rid}'
        for actor,status in ((ub,404),(ua,200)):
            assert (await client.get(receipt,headers=headers(actor,uuid4()))).status_code==status
        assert (await client.post(research,json={'images':[image]},headers=headers(ub,uuid4()))).status_code==404
        assert (await client.post(research,json={'images':[photo('white')]},headers=headers(ua,uuid4()))).status_code==422
        lookup.assert_not_awaited()
        finished=await client.post(research,json={'images':[image]},headers=headers(ua,uuid4()))
        assert finished.status_code==200,finished.text
        assert finished.json()['research']['status']=='UNAVAILABLE'
        await client.post(research,json={'images':[image]},headers=headers(ua,uuid4()))
        lookup.assert_awaited_once()
        assert (await client.get(receipt,headers=headers(ua,uuid4()))).json()==finished.json()
        # Historical card-schema failure: use a single bounded book-only fallback.
        response.observation=observation.model_copy(update={'object_type':'NONE','book':None,
            'notes':['The photograph shows a comic book rather than a trading card.']})
        legacy=await client.post(path,json={'image_data_url':photo('maroon')},headers=headers(ua,uuid4()))
        assert legacy.status_code==200 and legacy.json()['book_result']['fields']['issue_number']=='7',legacy.text
        fallback.assert_awaited_once()
        # The capped owner from the preceding scanner fixture cannot evade the
        # existing book allowance through the new automatic route.
        capped=await client.post(path,json={'image_data_url':photo('olive')},headers=headers(ub,uuid4()))
        assert capped.status_code==429,capped.text
        assert fallback.await_count==1
    assert await db.fetchval('select count(*) from tcg.inventory_items')==before
    stored=await db.fetchval('select provider_evidence from tcg.recognition_runs where id=$1',UUID(rid))
    assert stored['book_route'] and stored['book_image_digest']
    print('PASS: default camera book handoff, one vision call, legacy recovery, private receipt, original-photo research, replay, shared cap and no inventory writes.')
