"""Pending-card corrections through real authenticated HTTP and PostgreSQL."""
from uuid import UUID


async def verify_pending_card_review(client, db, headers, actor, other_actor):
    upload = '/api/v1/owner/imports/upload'
    payload = {'filename': 'pending-corrections.csv', 'adapter': 'GENERIC_CSV', 'content':
        'Name,Game,Set,Number,Variant,Rarity,Language,Condition,Grading Company,Grade,Certificate,Quantity\n'
        'Known Card,Pokemon,Synthetic Set,001,Normal,C,English,Pristine,,,,1\n'
        'Synthetic Slab 0,Pokemon,Synthetic Set,100,Normal,C,English,Near Mint,BGS,,,1\n'
        'Known Card,Pokemon,Synthetic Set,001,Normal,C,English,Pristine,PSA,10,REPEATED-SOURCE-CERT,2\n'
        'Known Card,Pokemon,Synthetic Set,001,Normal,C,English,Pristine,,,,bad\n'}
    result = await client.post(upload, json=payload, headers=headers(actor))
    assert result.status_code == 201, result.text
    assert result.json()['created_count'] == 0 and result.json()['summary']['review_rows'] == 4
    batch_id = result.json()['batch_id']
    detail = '/api/v1/owner/imports/' + batch_id
    stored = (await client.get(detail, headers=headers(actor))).json()
    rows = stored['candidates']
    source_before = await db.fetch('select id,raw_record from tcg.import_candidates where batch_id=$1 order by source_row', UUID(batch_id))
    known = await db.fetchval("select id from tcg.catalogue_products where identity_key='synthetic:a'")
    slab = await db.fetchval("select id from tcg.catalogue_products where identity_key='synthetic:slab:0'")
    version = stored['batch']['version']
    def route(row):
        return detail + '/candidates/' + row['id'] + '/resolve'
    def correction(catalogue, **card_details):
        return {'version': version, 'catalogue_id': str(catalogue), 'card_details': card_details}
    # Reproduce the old dead end: matching the identity alone cannot clear a
    # malformed physical condition. The new explicit correction can.
    old = await client.post(route(rows[0]), json={'version': version, 'catalogue_id': str(known)}, headers=headers(actor))
    assert old.status_code == 200 and old.json()['candidate']['status'] == 'REVIEW'
    assert old.json()['created_count'] == 0
    version = old.json()['version']
    raw = correction(known, card_state='RAW', condition='Lightly Played')
    assert (await client.post(route(rows[0]), json=raw, headers=headers(other_actor))).status_code == 404
    malformed = correction(known, card_state='GRADED', condition='Near Mint', grading_company='PSA', grade='10')
    assert (await client.post(route(rows[0]), json=malformed, headers=headers(actor))).status_code == 422
    saved = await client.post(route(rows[0]), json=raw, headers=headers(actor))
    assert saved.status_code == 200 and saved.json()['created_count'] == 1, saved.text
    retry = await client.post(route(rows[0]), json=raw, headers=headers(actor))
    assert retry.status_code == 200 and retry.json()['created_count'] == 0
    raw_copy = await db.fetchrow('select * from tcg.inventory_items where import_batch_id=$1 and source_row=$2', UUID(batch_id), rows[0]['source_row'])
    assert raw_copy['condition'] == 'Lightly Played' and raw_copy['grade'] is None
    assert raw_copy['source_record']['Condition'] == 'Pristine'
    version = saved.json()['version']

    saved = await client.post(route(rows[1]), json=correction(slab, card_state='GRADED', grading_company='BGS', grade='9.5', certificate_number='CORRECTED-TEST-123'), headers=headers(actor))
    assert saved.status_code == 200 and saved.json()['created_count'] == 1, saved.text
    graded_copy = await db.fetchrow('select * from tcg.inventory_items where import_batch_id=$1 and source_row=$2', UUID(batch_id), rows[1]['source_row'])
    assert graded_copy['condition'] is None and graded_copy['grade'] == '9.5'
    assert graded_copy['certificate_number'] == 'CORRECTED-TEST-123'
    assert graded_copy['source_record']['Grade'] == '' and graded_copy['source_record']['Condition'] == 'Near Mint'
    version = saved.json()['version']

    repeated = correction(known, card_state='GRADED', grading_company='PSA', grade='10', certificate_number='ONE-CERT')
    assert (await client.post(route(rows[2]), json=repeated, headers=headers(actor))).status_code == 422
    assert await db.fetchval('select count(*) from tcg.inventory_items where import_batch_id=$1', UUID(batch_id)) == 2
    saved = await client.post(route(rows[2]), json=correction(known, card_state='GRADED', grading_company='PSA', grade='10'), headers=headers(actor))
    assert saved.status_code == 200 and saved.json()['created_count'] == 2, saved.text
    version = saved.json()['version']
    saved = await client.post(route(rows[3]), json=correction(known, card_state='RAW'), headers=headers(actor))
    assert saved.status_code == 200 and saved.json()['created_count'] == 0, saved.text
    assert saved.json()['candidate']['status'] == 'REVIEW' and 'invalid_quantity' in saved.json()['candidate']['issues']
    assert saved.json()['candidate']['normalized_record']['condition'] is None
    skip = await client.post(detail + '/candidates/' + rows[3]['id'] + '/skip', json={'version': saved.json()['version']}, headers=headers(actor))
    assert skip.status_code == 200 and skip.json()['status'] == 'COMMITTED'
    assert source_before == await db.fetch('select id,raw_record from tcg.import_candidates where batch_id=$1 order by source_row', UUID(batch_id))
    copies = await db.fetch('select * from tcg.inventory_items where import_batch_id=$1', UUID(batch_id))
    assert len(copies) == 4 and all(c['status'] == 'DRAFT' and not c['identity_confirmed'] and c['acquisition_cost_minor'] is None for c in copies)

    # A correction does not rewrite the Collectr quantity identity or cause
    # corrected copies to be added again on an unchanged/increased export.
    collectr = {'filename': 'pending-collectr.csv', 'adapter': 'COLLECTR', 'content':
        'Portfolio Name,Category,Product Name,Set,Card Number,Rarity,Variance,Quantity,Card Condition,Language,Grade,Average Cost Paid\n'
        'Test,Pokemon,Known Card,Synthetic Set,001,C,Normal,2,Pristine,English,Ungraded,\n'}
    result = await client.post(upload, json=collectr, headers=headers(actor))
    assert result.status_code == 201 and result.json()['created_count'] == 0, result.text
    batch_id = result.json()['batch_id']; detail = '/api/v1/owner/imports/' + batch_id
    stored = (await client.get(detail, headers=headers(actor))).json(); row = stored['candidates'][0]
    original_identity = row['normalized_record']['_collectr_source_identity']
    version = stored['batch']['version']
    saved = await client.post(route(row), json=correction(known, card_state='RAW', condition='Lightly Played'), headers=headers(actor))
    assert saved.status_code == 200 and saved.json()['created_count'] == 2, saved.text
    assert saved.json()['candidate']['normalized_record']['_collectr_source_identity'] == original_identity
    replay = await client.post(upload, json=collectr, headers=headers(actor))
    assert replay.status_code == 201 and replay.json()['created_count'] == 0
    increased = {**collectr, 'content': collectr['content'].replace(',Normal,2,', ',Normal,3,')}
    delta = await client.post(upload, json=increased, headers=headers(actor))
    assert delta.status_code == 201 and delta.json()['created_count'] == 0, delta.text
    delta_detail = (await client.get('/api/v1/owner/imports/' + delta.json()['batch_id'], headers=headers(actor))).json()
    assert len(delta_detail['candidates']) == 1 and delta_detail['candidates'][0]['quantity'] == 1
    assert delta_detail['candidates'][0]['normalized_record']['previous_quantity'] == 2
    print('PASS: authenticated physical corrections, foreign-owner denial, unchanged CSV, exact retry, slab certificates, unrelated issue retention and Collectr +1 reconciliation.')
