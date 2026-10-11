"""Real production physical-state migrations + restricted-role HTTP import.

Run after owner_auto_import_postgres.py and owner_import_http_acceptance.py.
Uses only their disposable localhost database, synthetic collection and local
JWT/JWKS issuer. This is not a production Supabase sign-in or live seller test.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI

from app import auth, imports, import_inventory, owner_auto_imports, owner_imports
from app.db import _init_connection, user_connection

ROOT = Path(__file__).resolve().parents[1]


def source(raw_quantity: int = 92) -> imports.ImportPreviewRequest:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Portfolio Name', 'Category', 'Product Name', 'Set', 'Card Number',
                     'Rarity', 'Variance', 'Quantity', 'Card Condition', 'Language',
                     'Grade', 'Average Cost Paid', 'Certificate'])
    writer.writerow(['Test', 'Pokemon', 'Known Card', 'Synthetic Set', '001',
                     'C', 'Normal', raw_quantity, 'Near Mint', 'English', 'Ungraded', '', ''])
    for index in range(3):
        writer.writerow(['Test', 'Pokemon', f'Synthetic Slab {index}', 'Synthetic Set', f'10{index}',
                         'C', 'Normal', 1, 'Near Mint', 'English', 'PSA 10', '', f'TEST-CERT-{index}'])
    writer.writerow(['Test', 'Pokemon', 'Needs confirmation', 'Synthetic Set', '002',
                     'C', 'Normal', 439, 'Near Mint', '', 'Ungraded', '', ''])
    return imports.ImportPreviewRequest(
        filename='synthetic-mixed-collection.csv', adapter='COLLECTR', content=output.getvalue(),
        column_mapping={'certificate_number': 'Certificate'},
    )


async def main():
    dsn = os.environ['IMPORT_TEST_DSN']
    url = urlsplit(dsn)
    assert url.hostname in {'localhost', '127.0.0.1'} and url.path == '/import_intake_test'
    db = await asyncpg.connect(dsn)
    await _init_connection(db)
    pool = None
    server = None
    thread = None
    try:
        assert await db.fetchval("select exists(select 1 from tcg.catalogue_products where identity_key='synthetic:a')"), 'Expected disposable fixture'
        # Import the actual version-controlled guard and CHECK, not a relaxed
        # look-alike schema. These migrations run ONLY in the disposable DB.
        for name in ('202609230016_harden_inventory_physical_state.sql',
                     '202609240005_inventory_physical_state_separation.sql'):
            await db.execute((ROOT / 'database/migrations' / name).read_text())
        await db.execute("""alter table tcg.inventory_items
            add constraint fixture_actual_grading_pair check (
                (grading_company is null and grade is null and certificate_number is null)
                or (grading_company is not null and grade is not null));""")
        guard_before = await db.fetchval("select pg_get_functiondef('tcg.validate_inventory_condition_state()'::regprocedure)")
        assert 'Graded card inventory cannot also use raw card condition' in guard_before
        owner_a, owner_b, actor_a, actor_b = [uuid4() for _ in range(4)]
        await db.executemany("insert into tcg.owners(id,display_name,owner_type,commission_bps) values($1,$2,'CONSIGNOR',1000)",
                             [(owner_a, 'Physical state seller A'), (owner_b, 'Physical state seller B')])
        await db.executemany("insert into tcg.owner_memberships(user_id,owner_id,role) values($1,$2,'OWNER')",
                             [(actor_a, owner_a), (actor_b, owner_b)])
        for index in range(3):
            await db.execute("""insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
                values($1,$2,'CARD','Pokemon',$3,'Synthetic Set',$4,'Normal','C','English')""",
                uuid4(), f'synthetic:slab:{index}', f'Synthetic Slab {index}', f'10{index}')
        catalogue_count = await db.fetchval('select count(*) from tcg.catalogue_products')
        async def setup(connection):
            await connection.execute('set role tcg_api')
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, init=_init_connection, setup=setup)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)),
                                  state=SimpleNamespace(request_id='physical-state-regression'))
        actor = SimpleNamespace(user_id=actor_a)
        preview = await imports.preview_import(source(), request, actor)
        batch_id = UUID(str(preview['batch_id']))
        assert preview['physical_units'] == 534 and preview['ready_units'] == 95
        # Match a saved legacy preview: it predates automatic source receipts.
        await db.execute("update tcg.import_candidates set normalized_record=normalized_record-'_collectr_source_identity' where batch_id=$1", batch_id)
        original_candidates = await db.fetch('select * from tcg.import_candidates where batch_id=$1 order by source_row', batch_id)
        original_batch = await db.fetchrow('select * from tcg.import_batches where id=$1', batch_id)
        original_stock = await db.fetch('select * from tcg.inventory_items order by id')
        original_audits = await db.fetchval('select count(*) from tcg.audit_events')
        # Restore ONLY the old writer projection to reproduce the exact
        # reported failure against the unchanged real production guard.
        with patch.object(import_inventory, 'physical_inventory_condition', side_effect=lambda row: row.get('condition')):
            try:
                await owner_auto_imports.add_recognised(batch_id, imports.ImportCommitRequest(version=1), request, actor)
            except asyncpg.CheckViolationError as exc:
                assert 'Graded card inventory cannot also use raw card condition' in str(exc)
            else:
                raise AssertionError('The old writer must reproduce the production rejection')
        assert original_stock == await db.fetch('select * from tcg.inventory_items order by id')
        assert original_candidates == await db.fetch('select * from tcg.import_candidates where batch_id=$1 order by source_row', batch_id)
        assert original_batch == await db.fetchrow('select * from tcg.import_batches where id=$1', batch_id)
        assert original_audits == await db.fetchval('select count(*) from tcg.audit_events')

        private = ec.generate_private_key(ec.SECP256R1())
        public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
        public.update(kid='physical-state-test', use='sig', alg='ES256')
        class JWKS(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({'keys': [public]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), JWKS)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        settings = SimpleNamespace(jwks_url=f'http://127.0.0.1:{server.server_port}/jwks.json',
                                   auth_audience='authenticated', auth_issuer='https://physical-state.test/auth/v1')
        def headers(user):
            now = int(time.time())
            claims = {'sub': str(user), 'iss': settings.auth_issuer, 'aud': 'authenticated',
                      'iat': now, 'exp': now + 600, 'role': 'authenticated', 'session_id': str(uuid4())}
            return {'Authorization': 'Bearer ' + jwt.encode(claims, private, algorithm='ES256', headers={'kid': 'physical-state-test'})}
        app = FastAPI()
        app.state.db_pool = pool
        @app.middleware('http')
        async def request_context(request, call_next):
            request.state.request_id = 'physical-state-http'
            return await call_next(request)
        app.include_router(owner_imports.router)
        auth._jwk_client.cache_clear()
        with patch.object(auth, 'get_settings', return_value=settings):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://import.test') as client:
                detail = '/api/v1/owner/imports/' + str(batch_id)
                commit = detail + '/commit'
                assert (await client.post(commit, json={'version': 1})).status_code == 401
                assert (await client.post(commit, json={'version': 1}, headers=headers(actor_b))).status_code == 404
                response = await client.post(commit, json={'version': 1}, headers=headers(actor_a))
                assert response.status_code == 200, response.text
                result = response.json()
                assert result['created_count'] == 95 and result['summary']['added_units'] == 95
                assert result['summary']['review_units'] == 439
                assert result['status'] == 'PREVIEW' and result['automatic_intake']
                stock = await db.fetch('select * from tcg.inventory_items where import_batch_id=$1 order by source_row,source_copy', batch_id)
                assert len(stock) == 95
                graded = [row for row in stock if row['grade'] is not None]
                assert len(graded) == 3
                assert {row['certificate_number'] for row in graded} == {'TEST-CERT-0', 'TEST-CERT-1', 'TEST-CERT-2'}
                assert all(row['condition'] is None and row['grade'] == '10' and row['grading_company'] == 'PSA' for row in graded)
                assert all(row['source_record']['Card Condition'] == 'Near Mint' and row['source_record']['Grade'] == 'PSA 10' for row in graded)
                assert all(row['condition'] == 'Near Mint' for row in stock if row['grade'] is None)
                assert all(row['owner_id'] == owner_a and row['status'] == 'DRAFT' and not row['identity_confirmed'] and row['acquisition_cost_minor'] is None for row in stock)
                assert await db.fetch('select raw_record from tcg.import_candidates where batch_id=$1 order by source_row', batch_id) == [dict(raw_record=row['raw_record']) for row in original_candidates]
                for _ in range(3):
                    replay = await client.post(commit, json={'version': 1}, headers=headers(actor_a))
                    assert replay.status_code == 200 and replay.json()['created_count'] == 0
                assert stock == await db.fetch('select * from tcg.inventory_items where import_batch_id=$1 order by source_row,source_copy', batch_id)
                assert (await client.get(detail, headers=headers(actor_b))).status_code == 404
                stored = (await client.get(detail, headers=headers(actor_a))).json()
                review = next(row for row in stored['candidates'] if row['status'] == 'REVIEW')
                card_b = await db.fetchval("select id from tcg.catalogue_products where identity_key='synthetic:b'")
                confirmation = {'version': stored['batch']['version'], 'catalogue_id': str(card_b)}
                resolved = await client.post(detail + '/candidates/' + review['id'] + '/resolve', json=confirmation, headers=headers(actor_a))
                assert resolved.status_code == 200, resolved.text
                assert resolved.json()['created_count'] == 439 and resolved.json()['status'] == 'COMMITTED'
                assert await db.fetchval('select count(*) from tcg.inventory_items where import_batch_id=$1', batch_id) == 534
                again = await client.post('/api/v1/owner/imports/upload', json=source().model_dump(), headers=headers(actor_a))
                assert again.status_code == 201 and again.json()['created_count'] == 0
                changed = await client.post('/api/v1/owner/imports/upload', json=source(93).model_dump(), headers=headers(actor_a))
                assert changed.status_code == 201, changed.text
                assert changed.json()['created_count'] == 1
                assert await db.fetchval('select count(*) from tcg.inventory_items where owner_id=$1', owner_a) == 535
        # Prove the patch did not weaken the real guard, then cover sealed
        # storage through the same shared writer (no new scanner capability).
        raw_card = await db.fetchval("select id from tcg.catalogue_products where identity_key='synthetic:a'")
        try:
            async with user_connection(pool, actor_a, 'guard-still-active') as connection:
                await connection.execute("""insert into tcg.inventory_items(id,inventory_code,catalogue_id,owner_id,condition,grading_company,grade)
                    values($1,$2,$3,$4,'Near Mint','PSA','10')""", uuid4(), 'INVALID-TEST-' + uuid4().hex, raw_card, owner_a)
        except asyncpg.CheckViolationError:
            pass
        else:
            raise AssertionError('The database guard must remain active')
        assert guard_before == await db.fetchval("select pg_get_functiondef('tcg.validate_inventory_condition_state()'::regprocedure)")
        assert catalogue_count == await db.fetchval('select count(*) from tcg.catalogue_products')
        assert not await db.fetchval("select has_any_column_privilege('tcg_api','tcg.owners','UPDATE')")
        print('PASS: original production graded/raw-condition error reproduced and fully rolled back; unchanged real SQL guard; authenticated legacy-preview resume adds 92 raw + 3 graded copies, leaves 439 pending; original source/grade/certificates preserved; replay adds zero; confirmation and +1 re-export succeed; cross-owner access denied. Synthetic data/local issuer only.')
    finally:
        auth._jwk_client.cache_clear()
        if pool:
            await pool.close()
        await db.close()
        if server:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
        if thread:
            thread.join(timeout=2)


if __name__ == '__main__':
    asyncio.run(main())
