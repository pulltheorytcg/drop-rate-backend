"""Fixture extensions for marketing_postgres_smoke; never a production runner."""
from uuid import uuid4

from app.marketing_run_attention import record_marketing_attention
from app.marketing_specialist_api import CreateCommand, PostgresStore
from app.marketing_specialists import Command, JobInput


async def install_fixture(admin):
    assert await admin.fetchval('select current_database()') == 'marketing_test'
    await admin.execute('''
        create table tcg.action_required_items(
            id uuid primary key default gen_random_uuid(),
            owner_id uuid not null references tcg.owners(id),
            category text not null check(category='AUTOMATION'),
            code text not null,
            severity text not null check(severity in ('LOW','MEDIUM','HIGH','CRITICAL')),
            entity_type text not null check(entity_type='OWNER'),
            entity_id uuid not null,
            dedupe_key text not null,
            title text not null,
            detail text not null,
            recommended_action text not null,
            status text not null check(status in ('OPEN','RESOLVED','DISMISSED')),
            metadata jsonb not null,
            unique(owner_id,dedupe_key)
        );
        alter table tcg.action_required_items enable row level security;
        alter table tcg.action_required_items force row level security;
        grant select,insert,update on tcg.action_required_items to tcg_api;
        create policy own_action_required_access on tcg.action_required_items for all to tcg_api
          using (owner_id in (select owner_id from tcg.owner_memberships
                 where user_id=tcg.current_user_id() and active))
          with check (owner_id in (select owner_id from tcg.owner_memberships
                 where user_id=tcg.current_user_id() and active));
    ''')


async def verify_attention(admin, pool, actor, other_actor, recovered):
    """Use actual PostgresStore with the existing disposable database only."""
    import app.marketing_specialist_api as api
    assert await admin.fetchval('select current_database()') == 'marketing_test'
    store = PostgresStore(pool, actor, str(uuid4()))
    recovery_key = 'marketing-run:' + str(recovered['id'])
    assert await admin.fetchval('select count(*) from tcg.action_required_items') == 1
    assert await admin.fetchval('select code from tcg.action_required_items where dedupe_key=$1', recovery_key) == 'MARKETING_UNKNOWN'
    async with PostgresStore(pool, other_actor, str(uuid4())).connection() as conn:
        assert await conn.fetchval('select count(*) from tcg.action_required_items') == 0

    async def claim_new(stage):
        job = await store.create(CreateCommand(job_id=uuid4(),actor_user_id=actor,input=JobInput(topic='Local attention fixture')))
        cmd = Command(job_id=job['id'],actor_user_id=actor,stage=stage,expected_input_sha256=job['input_sha256'])
        won, run = await store.claim(cmd, {'fixture': True}, 'a'*64, 'b'*64)
        assert won
        return cmd, run

    for state in ('FAILED','UNKNOWN','NEEDS_REVIEW','AWAITING_MEDIA','PREPARED'):
        cmd, run = await claim_new('design' if state=='AWAITING_MEDIA' else 'research')
        key = 'marketing-run:' + str(run['id'])
        result = await store.finish(cmd,state,{'summary':'private-model-text'}, {})
        assert result['state'] == state
        attention = state in ('FAILED','UNKNOWN','NEEDS_REVIEW')
        rows = await admin.fetch('select * from tcg.action_required_items where dedupe_key=$1', key)
        assert len(rows) == (1 if attention else 0)
        if attention:
            item = rows[0]
            assert item['owner_id'] == actor
            assert item['entity_type'] == 'OWNER' and item['entity_id'] == actor
            assert 'private-model-text' not in str(dict(item))
            assert item['severity'] == ('MEDIUM' if state=='NEEDS_REVIEW' else 'HIGH')
            await admin.execute("update tcg.action_required_items set status='RESOLVED' where dedupe_key=$1",key)
            # A direct duplicate insertion also must not reopen the resolved alert.
            async with store.connection() as conn:
                assert await record_marketing_attention(conn,result) is None
            assert (await store.finish(cmd,'FAILED',{'error_code':'late'},{}))['state'] == state
            assert await admin.fetchval('select count(*) from tcg.action_required_items where dedupe_key=$1',key) == 1
            assert await admin.fetchval('select status from tcg.action_required_items where dedupe_key=$1',key) == 'RESOLVED'
        else:
            assert (await store.finish(cmd,'FAILED',{'error_code':'late'},{}))['state'] == state
            assert await admin.fetchval('select count(*) from tcg.action_required_items where dedupe_key=$1',key) == 0

    cmd, run = await claim_new('research')
    original = api.record_marketing_attention
    async def fail_after_insert(connection, record):
        await original(connection,record)
        raise RuntimeError('local fixture failure after insert')
    api.record_marketing_attention = fail_after_insert
    try:
        try:
            await store.finish(cmd,'FAILED',{'error_code':'fixture'}, {})
            raise AssertionError('Expected insert failure')
        except RuntimeError as exc:
            assert str(exc) == 'local fixture failure after insert'
    finally:
        api.record_marketing_attention = original
    assert (await store.read_stage(cmd,'research'))['state'] == 'RUNNING'
    assert await admin.fetchval('select count(*) from tcg.action_required_items where dedupe_key=$1','marketing-run:'+str(run['id'])) == 0
    assert (await store.finish(cmd,'FAILED',{'error_code':'fixture'},{}))['state'] == 'FAILED'
    print('PASS: actual PostgreSQL terminal attention, owner isolation, no success/media alerts, no duplicate/reopened alerts, late-result protection and atomic rollback')
