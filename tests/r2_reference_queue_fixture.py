"""Shared disposable SQL contract for fair, exact-source artwork retries."""
from app.r2_reference_images import PENDING_REFERENCE_IMAGES_SQL

SETUP = """
create schema r2_queue_test;
create table r2_queue_test.reference_cards (
 provider text,system_code text,language text,provider_id text,image_url text,
 primary key(provider,system_code,language,provider_id));
create table r2_queue_test.reference_image_mirrors (
 provider text,system_code text,language text,provider_id text,source_url text,
 status text,failure_count integer,next_retry_at timestamptz,
 primary key(provider,system_code,language,provider_id));
insert into r2_queue_test.reference_cards
select 'TCGdex','POKEMON_TCG','English',n::text,
 'https://assets.tcgdex.net/en/test/'||n||'/high.webp'
from generate_series(1,10000) n;
insert into r2_queue_test.reference_image_mirrors
select provider,system_code,language,provider_id,image_url,'RETRY',2,
 now()-(200-provider_id::integer)*interval '1 minute'
from r2_queue_test.reference_cards where provider_id::integer between 100 and 108;
insert into r2_queue_test.reference_image_mirrors
select provider,system_code,language,provider_id,image_url,
 case when provider_id='109' then 'RETRY' else 'VERIFIED' end,
 case when provider_id='109' then 2 else 0 end,
 case when provider_id='109' then now()+interval '1 day' else null end
from r2_queue_test.reference_cards where provider_id in ('109','110');
"""

QUERY = PENDING_REFERENCE_IMAGES_SQL.replace('tcg.', 'r2_queue_test.').replace('$1', '20')
STEPS = [
    QUERY,
    "delete from r2_queue_test.reference_cards where provider_id::integer not between 100 and 110;" + QUERY,
    "update r2_queue_test.reference_cards set image_url='https://assets.tcgdex.net/en/new/high.webp' where provider_id='109';" + QUERY,
    "update r2_queue_test.reference_image_mirrors set next_retry_at=now()+interval '1 day' where status='RETRY';" + QUERY,
]


def verify(results):
    mixed, retries, changed, future = results
    assert len(mixed) == 20
    assert [row['provider_id'] for row in mixed[:4]] == ['100','101','102','103']
    assert sum(row['failure_count'] > 0 for row in mixed) == 4
    assert not {'109','110'} & {row['provider_id'] for row in mixed}
    assert len(retries) == 9 and all(row['failure_count'] == 2 for row in retries)
    assert len(changed) == 10
    assert next(row for row in changed if row['provider_id']=='109')['failure_count'] == 0
    assert len(future) == 1 and future[0]['provider_id'] == '109'
    assert future[0]['failure_count'] == 0
