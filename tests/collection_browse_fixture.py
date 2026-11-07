"""Actual catalogue-intake HTTP path, SQL, RLS and retry behaviour in local CI."""
import asyncio
import hashlib
from uuid import UUID, uuid4


async def prepare(db):
    # Empty provider tables used by the production SOURCE_CTE. No query mocks.
    await db.execute('''
      create table tcg.reference_sets(provider text,system_code text,language text,set_id text,name text,release_date date);
      create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,set_id text,name text,
        card_number text,rarity text,image_url text,source_url text);
      create table tcg.provider_catalogue_mappings(source_provider text,system_code text,provider_language text,provider_id text,
        catalogue_id uuid,provider_entity_type text,provider_variant_key text,match_status text);
      create table tcg.reference_market_prices(provider text,system_code text,language text,provider_id text,
        market_value_minor bigint,market_value_high_minor bigint,pricing_updated_at timestamptz,quotes jsonb,expires_at timestamptz,refresh_revision int);
      create table tcg.reference_catalogue_prices(like tcg.reference_market_prices);
      create table tcg.reference_sealed_market_prices(like tcg.reference_market_prices);
      create table tcg.reference_sealed_products(provider text,system_code text,language text,provider_id text,set_id text,
        name text,product_type text,image_url text,source_url text);
      grant select on tcg.reference_sets,tcg.reference_cards,tcg.provider_catalogue_mappings,
        tcg.reference_market_prices,tcg.reference_catalogue_prices,tcg.reference_sealed_market_prices,tcg.reference_sealed_products to tcg_api;
    ''')


async def exercise(client, db, headers, ua, ub, owner_a, owner_b, card, pack):
    endpoint = '/api/v1/catalogue-browser/intake'
    payload = {'key': 'c:' + str(card), 'confirmed': True}
    assert (await client.post(endpoint, json=payload)).status_code == 401
    for extra in ({'confirmed': False}, {'condition': 'best'}, {'condition': ''},
                  {'seal_status': 'SEALED'}, {'owner_id': str(owner_b)}, {'identity_confirmed': True}):
        response = await client.post(endpoint, json={**payload, **extra}, headers=headers(ua, uuid4()))
        assert response.status_code == 422, response.text
    before = await db.fetchval('select count(*) from tcg.inventory_items')
    key = uuid4()
    responses = await asyncio.gather(*[client.post(endpoint, json=payload, headers=headers(ua,key)) for _ in range(2)])
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()['inventory']['id'] for r in responses}) == 1
    inventory_id = UUID(responses[0].json()['inventory']['id'])
    item = await db.fetchrow('select * from tcg.inventory_items where id=$1', inventory_id)
    assert item['owner_id'] == owner_a and item['condition'] is None
    assert item['status'] == 'DRAFT' and item['sale_intent'] == 'PERSONAL_COLLECTION'
    assert not item['identity_confirmed'] and item['market_value_minor'] is None and item['store_price_minor'] is None
    assert await db.fetchval('select count(*) from tcg.inventory_items') == before + 1
    assert (await client.post(endpoint,json={**payload,'condition':'Near Mint'},headers=headers(ua,key))).status_code == 409
    # Same request key on another authenticated owner cannot replay A's copy.
    other = await client.post(endpoint,json=payload,headers=headers(ub,key))
    assert other.status_code == 409, other.text
    assert str(inventory_id) not in other.text
    # Deterministically commit B after A's first intake receipt SELECT but before
    # A reads inventory. The receipt and copy commit atomically; A must replay.
    from app import inventory_intake
    original_receipt = inventory_intake._existing_receipt
    race_key = uuid4()
    entered, release = asyncio.Event(), asyncio.Event()
    reads = 0
    async def gated_receipt(connection, owner_id, request_key):
        nonlocal reads
        result = await original_receipt(connection, owner_id, request_key)
        if request_key == race_key and owner_id == owner_a:
            reads += 1
            if reads == 2:  # Browse preflight is first; actual intake is second.
                assert result is None
                entered.set()
                await asyncio.wait_for(release.wait(), timeout=10)
        return result
    inventory_intake._existing_receipt = gated_receipt
    first = None
    try:
        first = asyncio.create_task(client.post(endpoint,json=payload,headers=headers(ua,race_key)))
        await asyncio.wait_for(entered.wait(), timeout=10)
        second = await client.post(endpoint,json=payload,headers=headers(ua,race_key))
        assert second.status_code == 201, second.text
        release.set()
        replay = await first
        assert replay.status_code == 201 and replay.json()['replayed'], replay.text
        assert replay.json()['inventory']['id'] == second.json()['inventory']['id']
        assert await db.fetchval('select count(*) from tcg.inventory_items where intake_request_key=$1',race_key)==1
    finally:
        release.set()
        if first is not None and not first.done():
            first.cancel()
            await asyncio.gather(first,return_exceptions=True)
        inventory_intake._existing_receipt = original_receipt
    assert (await client.post(endpoint,json={'key':'c:'+str(pack),'confirmed':True},headers=headers(ua,uuid4()))).status_code == 422
    assert (await client.post(endpoint,json={'key':'c:'+str(pack),'seal_status':'SEALED','confirmed':True},headers=headers(ua,uuid4()))).status_code == 201
    # A provider reference keeps the same exact catalogue, with no approvals.
    await db.execute("insert into tcg.reference_sets values('Fixture','ONE_PIECE_CARD_GAME','Japanese','FIX','Test set',current_date)")
    await db.execute("""insert into tcg.reference_cards values('Fixture','ONE_PIECE_CARD_GAME','Japanese','Parallel','FIX',
        'Test card','OP99-001','SR',null,'https://fixture.invalid/card')""")
    reference_key = 'r:' + hashlib.md5('\x1f'.join(('Fixture','ONE_PIECE_CARD_GAME','Japanese','Parallel')).encode()).hexdigest()
    reference = await client.post(endpoint,json={'key':reference_key,'confirmed':True},headers=headers(ua,uuid4()))
    assert reference.status_code == 201, reference.text
    assert reference.json()['inventory']['catalogue_id'] == str(card)
    assert reference.json()['inventory']['condition'] is None
    print('PASS: scan/search share collection admission; real browse SQL + signed HTTP/RLS, optional condition, explicit selection, sealed boundary, concurrent retry, owner isolation, no sale/price approvals.')
