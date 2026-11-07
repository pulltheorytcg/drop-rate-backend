"""Run only against the disposable CI database, never production."""
import asyncio
import os
from urllib.parse import urlsplit

import asyncpg
from r2_reference_queue_fixture import SETUP, STEPS, QUERY, verify


async def main():
    dsn = os.environ['ARTWORK_TEST_DSN']
    parsed = urlsplit(dsn)
    assert parsed.hostname in {'localhost','127.0.0.1'} and parsed.path == '/artwork_test'
    db = await asyncpg.connect(dsn)
    try:
        await db.execute(SETUP)
        results = []
        for step in STEPS:
            # Execute fixture mutations separately; asyncpg fetch accepts one statement.
            assert step.endswith(QUERY)
            prefix = step[:-len(QUERY)]
            if prefix:
                await db.execute(prefix)
            results.append([dict(row) for row in await db.fetch(QUERY)])
        verify(results)
    finally:
        await db.close()
    print('PASS: bounded retry reservation, new work, future backoff, changed sources')


asyncio.run(main())
