"""Unit/route-boundary checks. SQL behaviour is tested separately on real PG."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import owner_imports
from app.import_catalogue_search import CATALOGUE_SEARCH_SQL, search_tokens


@pytest.mark.parametrize(('term','expected'), [
    ('OP14-041 The Azure Sea\'s Seven',['op14','041','the','azure','sea','s','seven']),
    ('041 Phantasmal Flames',['041','phantasmal','flames']),
    ('  223/193   MEGA Dream ex ',['223','193','mega','dream','ex']),
    ('041 Pokémon TCG: Classic',['041','pokémon','tcg','classic']),
    ('OP14–041 Japanese',['op14','041','japanese']),
    ('Ｐｉｋａｃｈｕ',['pikachu']),
    ('Luffy Luffy',['luffy']),
    ('%%%___',[]),
    ('\t\n',[]),
])
def test_literal_cross_field_tokens(term, expected):
    assert search_tokens(term)==expected


def test_search_statement_never_joins_private_stock_or_builds_sql_from_input():
    assert 'from tcg.catalogue_products p' in CATALOGUE_SEARCH_SQL
    assert 'unnest($3::text[])' in CATALOGUE_SEARCH_SQL
    assert 'strpos(' in CATALOGUE_SEARCH_SQL
    assert 'not exists' in CATALOGUE_SEARCH_SQL
    assert 'limit 16' in CATALOGUE_SEARCH_SQL
    for forbidden in ['inventory_items','owners','insert into','update tcg','delete from']:
        assert forbidden not in CATALOGUE_SEARCH_SQL.lower()


def test_route_binds_terms_and_uses_verified_user_context(monkeypatch):
    user_id=uuid4()
    calls=[]
    class Connection:
        async def fetch(self, sql, *args):
            calls.append((sql,args))
            return [{'id':uuid4(),'name':'Fixture card','game':'One Piece',
                     'set_name':'Fixture Set','card_number':'OP14-041',
                     'variant':'Foil','language':'Japanese','product_type':'CARD'}]
    @asynccontextmanager
    async def user_connection(pool,actor,request_id):
        assert actor==user_id and request_id=='import-search-test'
        yield Connection()
    monkeypatch.setattr(owner_imports,'user_connection',user_connection)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                            state=SimpleNamespace(request_id='import-search-test'))
    result=asyncio.run(owner_imports.search_existing_catalogue_for_import(
        request,SimpleNamespace(user_id=user_id),q='OP14-041 Fixture Set',product_type='CARD'))
    assert len(result['items'])==1
    assert calls==[(CATALOGUE_SEARCH_SQL,('OP14-041 Fixture Set','CARD',['op14','041','fixture','set']))]


@pytest.mark.parametrize(('q','kind'), [('%%__','CARD'),('   ','CARD'),('valid','invalid')])
def test_empty_and_invalid_searches_do_not_open_db(monkeypatch,q,kind):
    def unexpected(*args,**kwargs):
        raise AssertionError('Invalid search opened a database connection')
    monkeypatch.setattr(owner_imports,'user_connection',unexpected)
    assert asyncio.run(owner_imports.search_existing_catalogue_for_import(
        SimpleNamespace(),SimpleNamespace(),q=q,product_type=kind))=={'items':[]}
