"""Signed HTTP scanner tests: real recognition table constraints and owner RLS."""
import asyncio
import base64
import io
import json
import re
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from PIL import Image
from app import book_recognition as scanner
from app.db import user_connection
from app.recognition_vision import RecognitionVisionError


async def prepare(db,root,actors):
    # Replace only the earlier minimal recognition fixture, after its card rows
    # have been exercised. Production's complete definition is used verbatim.
    await db.execute('drop table tcg.recognition_runs; create schema auth; create table auth.users(id uuid primary key)')
    await db.executemany('insert into auth.users values($1)',[(a,) for a in actors])
    sql=(root/'database/migrations/20260927184033_recognition_engine_v1.sql').read_text()
    await db.execute(re.search(r'create table tcg.recognition_runs \([\s\S]*?\n\);',sql).group())
    await db.execute('alter table tcg.recognition_runs enable row level security; alter table tcg.recognition_runs force row level security; grant select,insert,update on tcg.recognition_runs to tcg_api')
    await db.execute(re.search(r'create policy api_read on tcg.recognition_runs\n[\s\S]*?;',sql).group())
    access=(root/'database/migrations/20260928195408_owner_recognition_access.sql').read_text()
    for policy in ('api_insert','api_update'):
        await db.execute(re.search(rf'create policy {policy} on tcg.recognition_runs\n[\s\S]*?;',access).group())


def photo(color):
    output=io.BytesIO();Image.new('RGB',(220,320),color).save(output,format='JPEG')
    return 'data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode()


async def exercise(client,db,pool,headers,settings,ua,ub,uf,owner_a,owner_b):
    path='/api/v1/owner/books/recognize'
    fields={key:dict(value='',visible_text='',confidence=0) for key in scanner.BookFields.model_fields}
    fields['series_title']=dict(value='Fixture Manga',visible_text='Fixture Manga',confidence=.99)
    observed=scanner.BookObservation(object_type='BOOK',category='MANGA',book_format='MANGA',confidence=.99,fields=fields,warnings=[])
    calls=[];gate=None;failure=False;revoke=False
    async def observe(self,images):
        calls.append(images)
        if gate:await gate.wait()
        if failure:raise RecognitionVisionError('Fixture unavailable',status_code=503,retryable=True)
        if revoke:await db.execute('update tcg.owner_memberships set active=false where user_id=$1',ua)
        return SimpleNamespace(observation=observed,telemetry=SimpleNamespace(to_dict=lambda:{'provider':'fixture'}))
    settings.openai_api_key='fixture-only';settings.recognition_model='fixture-model';settings.recognition_max_image_bytes=3_000_000
    before=await db.fetchval('select count(*) from tcg.inventory_items')
    with patch.object(scanner,'get_settings',return_value=settings),patch.object(scanner.BookVisionClient,'observe_with_telemetry',observe):
        for actor,status in ((None,401),(uf,403)):
            r=await client.post(path,json={'images':[photo('red')]},headers=headers(actor,uuid4()) if actor else {})
            assert r.status_code==status,r.text
        invalid=await client.post(path,json={'images':['data:image/jpeg;base64,'+'x'*120]},headers=headers(ua,uuid4()))
        assert invalid.status_code==422 and not calls,invalid.text
        gate=asyncio.Event()
        first=asyncio.create_task(client.post(path,json={'images':[photo('red')]},headers=headers(ua,uuid4())))
        for _ in range(200):
            if calls:break
            await asyncio.sleep(.01)
        assert calls
        duplicate=await client.post(path,json={'images':[photo('red')]},headers=headers(ua,uuid4()))
        assert duplicate.status_code==409 and len(calls)==1,duplicate.text
        gate.set();response=await first;gate=None
        assert response.status_code==200,response.text
        body=response.json();assert body['status']=='NEEDS_REVIEW' and body['auto_save'] is False and body['market_value_minor'] is None
        replay=await client.post(path,json={'images':[photo('red')]},headers=headers(ua,uuid4()))
        assert replay.json()['replayed'] and replay.json()['run_id']==body['run_id'] and len(calls)==1
        other=await client.post(path,json={'images':[photo('red')]},headers=headers(ub,uuid4()))
        assert other.status_code==200 and other.json()['run_id']!=body['run_id'] and len(calls)==2,other.text
        async with user_connection(pool,ub,'book-scan-isolation') as conn:
            assert await conn.fetchval('select count(*) from tcg.recognition_runs where id=$1',UUID(body['run_id']))==0
        history=await db.fetch('select ai_observation,provider_evidence,source_image_sha256,source_size_bytes from tcg.recognition_runs')
        assert all('base64' not in json.dumps(dict(row)) for row in history)
        failure=True
        r=await client.post(path,json={'images':[photo('blue')]},headers=headers(ua,uuid4()))
        assert r.status_code==503,r.text
        assert await db.fetchval("select count(*) from tcg.recognition_runs where status='FAILED'")==1
        failure=False;revoke=True
        r=await client.post(path,json={'images':[photo('green')]},headers=headers(ua,uuid4()))
        assert r.status_code==403 and 'fields' not in r.json(),r.text
        await db.execute('update tcg.owner_memberships set active=true where user_id=$1',ua);revoke=False
        # Twenty actual receipt rows enforce a durable per-owner cap, including
        # failed runs. No external model/provider call occurs after the cap.
        await db.execute("""insert into tcg.recognition_runs(owner_id,idempotency_key,created_by_user_id)
            select $1,'book-scan:rate-fixture:'||n,$2 from generate_series(1,20) n""",owner_b,ub)
        count=len(calls)
        r=await client.post(path,json={'images':[photo('yellow')]},headers=headers(ub,uuid4()))
        assert r.status_code==429 and len(calls)==count,r.text
        quote=dict(new_catalogue=dict(product_type='COMIC',game='Books',name='New book',set_name='New book',language='English',
            comic_printing=dict(system_code='MANGA',series_title='Uncatalogued fixture',issue_number='1',publisher='Fixture',book_format='MANGA')),condition='Near Mint')
        for actor,status in ((None,401),(uf,403),(ua,200)):
            r=await client.post('/api/v1/owner/books/market-value',json=quote,headers=headers(actor,uuid4()) if actor else {})
            assert r.status_code==status,r.text
            if status==200:assert r.json()['market_value_minor'] is None
    assert await db.fetchval('select count(*) from tcg.inventory_items')==before
    print('PASS: book scan signed HTTP, real receipt constraints/RLS, concurrent dedup, owner isolation, input validation, provider failure, revoked access, durable rate cap, no image or inventory write.')
