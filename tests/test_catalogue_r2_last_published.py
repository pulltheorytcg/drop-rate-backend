"""Trading-card browse pages keep the last published list while a republish is pending.

When the shared catalogue changes, the publication row's generation moves ahead
of the published one until the maintenance worker republishes. Until 28 Nov 2026
every reader refused the older list for that whole period and catalogue pages
fell back to 7-21 s SQL. Browse pages may now keep the last published list,
within strict limits. Everything else still refuses it.
"""
import ast
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app import catalogue_r2_live as live
from test_catalogue_r2_live import fixture

OWNER = 'owner-a'
LISTED = '30000000-0000-0000-0000-000000000001'
NEW = '30000000-0000-0000-0000-0000000000ff'
BROWSER = Path(__file__).resolve().parents[1] / 'backend/app/catalogue_browser.py'
LIBRARY = Path(__file__).resolve().parents[1] / 'backend/app/reference_library.py'
COLLECTIBLES = Path(__file__).resolve().parents[1] / 'backend/app/r2_collectible_browse.py'


class Connection:
    def __init__(self, state, owned=(LISTED,), fail_owned=False):
        self.state, self.owned, self.fail_owned = state, list(owned), fail_owned
        self.owner_queries = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, sql):
        assert sql == live.STATE_SQL
        return self.state

    async def fetch(self, sql, *args):
        assert sql == live.OWNER_LISTED_PRODUCTS_SQL
        self.owner_queries.append(args)
        if self.fail_owned:
            raise RuntimeError('inventory read failed')
        return [{'catalogue_id': value} for value in self.owned]


@pytest.fixture
def published(monkeypatch):
    """A loaded, verified generation-1 snapshot that lists one product."""
    manifest, raw = fixture()
    snapshot = live.assemble(manifest, [raw])
    product = {name: None for name, _ in live.RELATIONS['catalogue_products']}
    product.update(id=LISTED, product_type='CARD', game='Pokemon', name='Listed card')
    snapshot.rows['catalogue_products'].append(product)
    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED', 'true')
    monkeypatch.delenv('TCG_R2_LIVE_CATALOGUE_LAST_PUBLISHED_SECONDS', raising=False)
    monkeypatch.setattr(live, '_current', snapshot)
    monkeypatch.setattr(live, '_loading', None)
    monkeypatch.setattr(live, '_behind', None)
    monkeypatch.setattr(live, '_listed_products', None)
    monkeypatch.setattr(live, '_last_published_logged', {})
    return snapshot, manifest


def state(manifest, *, generation=3, published_generation=1):
    return dict(generation=generation, published_generation=published_generation, manifest=manifest)


@pytest.mark.asyncio
async def test_current_publication_is_returned_without_an_owner_query(published):
    snapshot, manifest = published
    connection = Connection(state(manifest, generation=1))
    assert await live.read(connection) is snapshot
    assert await live.read(connection, last_published_owner=OWNER) is snapshot
    assert connection.owner_queries == []


@pytest.mark.asyncio
async def test_strict_readers_still_refuse_a_publication_that_is_behind(published):
    _, manifest = published
    connection = Connection(state(manifest))
    assert await live.read(connection) is None
    assert await live.read(connection, last_published_owner=None) is None
    assert connection.owner_queries == []


@pytest.mark.asyncio
async def test_browse_keeps_last_published_list_when_all_owner_stock_is_listed(published, caplog):
    snapshot, manifest = published
    connection = Connection(state(manifest))
    with caplog.at_level('WARNING'):
        assert await live.read(connection, last_published_owner=OWNER) is snapshot
        assert await live.read(connection, last_published_owner=OWNER) is snapshot
    assert connection.owner_queries == [(OWNER,), (OWNER,)]
    lines = [r.getMessage() for r in caplog.records if 'LAST_PUBLISHED' in r.getMessage()]
    # Rate limited, and only generations: no owner, query or key.
    assert lines == ['CATALOGUE_R2_LIVE_LAST_PUBLISHED_SERVED published_generation=1 '
                     'generations_behind=2 behind_seconds=0']
    assert OWNER not in lines[0]


@pytest.mark.asyncio
async def test_owner_with_a_product_newer_than_the_list_gets_current_sql(published):
    _, manifest = published
    assert await live.read(Connection(state(manifest), owned=(LISTED, NEW)),
                           last_published_owner=OWNER) is None
    # An owner with no stock at all has nothing an older list could misreport.
    snapshot, _ = published
    assert await live.read(Connection(state(manifest), owned=()),
                           last_published_owner=OWNER) is snapshot


@pytest.mark.asyncio
async def test_failed_ownership_read_fails_closed(published, caplog):
    _, manifest = published
    with caplog.at_level('WARNING'):
        assert await live.read(Connection(state(manifest), fail_owned=True),
                               last_published_owner=OWNER) is None
    assert any('CATALOGUE_R2_LIVE_FALLBACK type=RuntimeError' in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_window_is_bounded_and_resets_once_the_publication_is_current(published, monkeypatch, caplog):
    snapshot, manifest = published
    clock = [1000.0]
    monkeypatch.setattr(live.time, 'monotonic', lambda: clock[0])
    connection = Connection(state(manifest))
    assert await live.read(connection, last_published_owner=OWNER) is snapshot
    clock[0] += 7199
    assert await live.read(connection, last_published_owner=OWNER) is snapshot
    clock[0] += 1
    with caplog.at_level('WARNING'):
        assert await live.read(connection, last_published_owner=OWNER) is None
    assert any('CATALOGUE_R2_LIVE_LAST_PUBLISHED_EXPIRED' in r.getMessage() for r in caplog.records)
    # A strict read while behind also starts the clock: the window is measured
    # from when this process first saw the publication fall behind.
    connection.state = state(manifest, generation=1)
    assert await live.read(connection) is snapshot and live._behind is None
    connection.state = state(manifest)
    assert await live.read(connection) is None
    clock[0] += 7199
    assert await live.read(connection, last_published_owner=OWNER) is snapshot
    clock[0] += 1
    assert await live.read(connection, last_published_owner=OWNER) is None


@pytest.mark.parametrize('value,expected', [
    (None, 7200), ('0', 0), ('600', 600), ('86400', 86400),
    ('86401', 0), ('-1', 0), ('soon', 0), ('', 0),
])
def test_window_setting_is_bounded_and_invalid_values_turn_it_off(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv('TCG_R2_LIVE_CATALOGUE_LAST_PUBLISHED_SECONDS', raising=False)
    else:
        monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_LAST_PUBLISHED_SECONDS', value)
    assert live.last_published_seconds() == expected


@pytest.mark.asyncio
async def test_zero_window_restores_the_previous_behaviour(published, monkeypatch):
    _, manifest = published
    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_LAST_PUBLISHED_SECONDS', '0')
    connection = Connection(state(manifest))
    assert await live.read(connection, last_published_owner=OWNER) is None
    assert connection.owner_queries == []


@pytest.mark.asyncio
async def test_only_the_verified_published_set_can_stand_in(published, monkeypatch):
    snapshot, manifest = published
    # A loaded snapshot of another generation is not the published one.
    monkeypatch.setattr(live, 'configured_object_storage', lambda: None)
    assert await live.read(Connection(state(manifest, generation=5, published_generation=2)),
                           last_published_owner=OWNER) is None
    # Never published at all.
    assert await live.read(Connection(dict(generation=4, published_generation=None, manifest=None)),
                           last_published_owner=OWNER) is None
    # A different manifest for the same generation is refused too.
    other = dict(manifest, parts=[dict(manifest['parts'][0], sha256='0' * 64)])
    assert await live.read(Connection(state(other)), last_published_owner=OWNER) is None
    assert await live.read(Connection(state(manifest)), last_published_owner=OWNER) is snapshot


@pytest.mark.asyncio
async def test_cold_process_loads_the_published_set_while_behind(published, monkeypatch):
    snapshot, manifest = published
    monkeypatch.setattr(live, '_current', None)
    monkeypatch.setattr(live, 'configured_object_storage', lambda: object())

    async def download(found, storage):
        assert found['generation'] == 1
        return snapshot

    async def warm(function, rows, today):
        return function(rows, today=today)

    monkeypatch.setattr(live, 'download', download)
    monkeypatch.setattr(live.asyncio, 'to_thread', warm)
    connection = Connection(state(manifest))
    assert await live.read(connection, last_published_owner=OWNER) is None
    await live._loading
    assert await live.read(connection, last_published_owner=OWNER) is snapshot
    # A strict reader never starts a load for a publication that is behind.
    monkeypatch.setattr(live, '_current', None)
    monkeypatch.setattr(live, '_loading', None)
    assert await live.read(connection) is None and live._loading is None


@pytest.mark.parametrize('systems,options,allowed', [
    (['POKEMON_TCG'], {}, True),
    (['POKEMON_TCG'], {'category': 'TCG'}, True),
    (['NARUTO_KAYOU', 'NARUTO_BANDAI_LEGACY'], {'category': 'TCG'}, True),
    ([], {}, False),                                   # unscoped global browse
    (['POKEMON_TCG'], {'keys': []}, False),            # saved-key selections
    (['POKEMON_TCG'], {'keys': ['r:abc']}, False),
    (['POKEMON_TCG'], {'category': 'SPORTS'}, False),
    (['SPORTS_CARDS'], {}, False),
    (['FIGURES'], {}, False),
    (['MANGA'], {}, False),
    (['MARVEL_COMICS', 'DC_COMICS', 'OTHER_COMICS'], {}, False),
    (['POKEMON_TCG', 'SPORTS_CARDS'], {}, False),
])
def test_only_trading_card_scoped_pages_qualify(systems, options, allowed):
    assert live.last_published_scope(OWNER, systems, **options) == (OWNER if allowed else None)
    assert live.last_published_scope(None, systems, **options) is None


def test_owner_stock_query_matches_the_browse_overlay_and_the_r2_exclusion():
    sql = ' '.join(live.OWNER_LISTED_PRODUCTS_SQL.split())
    assert "i.owner_id=$1" in sql
    assert "i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')" in sql
    # Products R2 leaves out by design are not "missing from the list".
    assert "private_profile.system_code in ('SPORTS_CARDS','FIGURES')" in sql
    assert "private_profile.identity_status is distinct from 'VERIFIED'" in sql
    assert ' '.join(live.chunk_sql('catalogue_products').split()).count(
        "private_profile.identity_status is distinct from 'VERIFIED'") == 1


def _read_calls(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == 'read'
            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'catalogue_r2_live']


def test_only_the_three_browse_endpoints_opt_in():
    browse = _read_calls(BROWSER)
    assert len(browse) == 3
    assert all([k.arg for k in call.keywords] == ['last_published_owner'] for call in browse)
    source = BROWSER.read_text(encoding='utf-8')
    assert source.count('catalogue_r2_live.last_published_scope(') == 2
    assert 'category=category, keys=key_list))' in source
    # Recognition/reference library and Sports/Figures browse stay strict.
    for path in (LIBRARY, COLLECTIBLES):
        calls = _read_calls(path)
        assert calls and all(not call.keywords for call in calls), path.name
        assert 'last_published' not in path.read_text(encoding='utf-8')
