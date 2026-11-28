"""A collector-number search never sends the whole catalogue snapshot.

On 28 Nov 2026 a search for "OP15-024" fell back from the indexed R2 browse
to the snapshot query, which passes all 70k reference cards as one parameter.
It took 33 s and returned HTTP 500. The live SQL already bounds such a search
to an index lookup on reference_cards.number_key.
"""
import uuid
from contextlib import asynccontextmanager

import pytest

from app import catalogue_r2_live as live
from app.catalogue_browser import product_query

OWNER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


class Connection:
    def __init__(self):
        self.fetched, self.executed = [], []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetch(self, sql, *args):
        self.fetched.append((sql, args))
        return [{"key": "r:1"}]

    async def fetchrow(self, sql, *args):
        return {"nestloop": "on", "mergejoin": "on", "jit": "on"}

    async def execute(self, sql, *args):
        self.executed.append(sql)


class Snapshot:
    def sql(self, query, params, **scope):
        raise AssertionError("The whole catalogue snapshot must not be used for a number search")


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["OP15-024", "op15 024", "BT21-079", "EB04-008"])
async def test_collector_number_search_runs_the_indexed_live_query(q):
    query, params = product_query(owner_id=OWNER, q=q, system_code="ONE_PIECE_CARD_GAME", category="TCG")
    assert live.COLLECTOR_NUMBER_FILTER in query
    connection = Connection()
    rows = await live.fetch_snapshot(connection, query, params, Snapshot())
    assert rows == [{"key": "r:1"}]
    assert connection.fetched == [(query, tuple(params))]
    assert not any("enable_nestloop" in sql for sql in connection.executed)


@pytest.mark.parametrize("q", ["Usopp", "Luffy OP15", ""])
def test_name_searches_and_plain_pages_carry_no_number_filter(q):
    query, _ = product_query(owner_id=OWNER, q=q, system_code="ONE_PIECE_CARD_GAME", category="TCG")
    assert live.COLLECTOR_NUMBER_FILTER not in query
