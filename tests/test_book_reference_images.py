"""Historical publisher covers retain release, identity and transport checks."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest

from app import catalogue_browser as browser
from app.book_artwork import reviewed_catalogue_entries
from test_book_catalogue import cover_book
from test_book_connector_import import run_sql


HISTORICAL = [row for row in reviewed_catalogue_entries() if row['release_date'] is None]


@pytest.mark.parametrize('release,year,language,visible', [
    ('current_date', 'extract(year from current_date)::integer', 'English', True),
    ('current_date+1', '1991', 'English', False),
    ('null', '1991', 'English', True),
    ('null', 'extract(year from current_date)::integer', 'English', False),
    ('null', 'extract(year from current_date)::integer+1', 'English', False),
    ('null', 'null', 'English', False),
    ('null', '1991', 'Japanese', False),
])
def test_actual_postgres_image_query_respects_known_past_year_and_language(tmp_path, release, year, language, visible):
    cid = '4eb42b1d-e39e-5ba9-8894-f0a5d0d33a9a'
    # Fixed test values only; execute the production query in disposable PG.
    setup = f"""insert into tcg.catalogue_products(id,identity_key,product_type,language)
        values('{cid}','fixture','COMIC','English');
      insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type,identity_status,release_date)
        values('{cid}','DC_COMICS','COMIC','STRUCTURED',{release});
      insert into tcg.comic_printing_details(catalogue_id,system_code,release_year,identity_status)
        values('{cid}','DC_COMICS',{year},'STRUCTURED');"""
    sql = browser.BOOK_REFERENCE_IMAGE_SQL.replace('$1', f"'{cid}'::uuid").replace('$2', "'DC_COMICS'").replace('$3', f"'{language}'")
    result = run_sql(tmp_path, [sql], setup=setup)
    assert result['results'][0]['ok'], result
    assert bool(result['results'][0]['rows']) is visible


async def invoke(monkeypatch, book, language='English'):
    connection = SimpleNamespace(fetchrow=AsyncMock(return_value=book))
    @asynccontextmanager
    async def user_connection(*args):
        yield connection
    thumbnail = AsyncMock(return_value=SimpleNamespace(data=b'fixture-cover', content_type='image/jpeg'))
    monkeypatch.setattr(browser, 'user_connection', user_connection)
    monkeypatch.setattr(browser, 'reference_thumbnail', thumbnail)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object())),
                              state=SimpleNamespace(request_id='book-cover-regression'))
    response = await browser.reference_image(request, SimpleNamespace(user_id=uuid4()), {},
        provider='Official Publisher', system_code=book['system_code'], language=language,
        provider_id=str(book['catalogue_id']), reference_kind='book', size='grid')
    assert connection.fetchrow.await_args.args == (browser.BOOK_REFERENCE_IMAGE_SQL,
        book['catalogue_id'], book['system_code'], language)
    return response, thumbnail


@pytest.mark.asyncio
@pytest.mark.parametrize('row', HISTORICAL, ids=lambda row: row['id'])
async def test_each_reviewed_historical_comic_can_use_its_exact_publisher_cover(monkeypatch, row):
    assert len(HISTORICAL) == 5
    response, thumbnail = await invoke(monkeypatch, cover_book(row))
    assert response.status_code == 200 and response.body == b'fixture-cover'
    assert response.media_type == 'image/jpeg'
    thumbnail.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('change,language', [
    ({'release_year': date.today().year}, 'English'),
    ({'release_year': date.today().year + 1}, 'English'),
    ({'release_year': None}, 'English'),
    ({'profile_status': 'NEEDS_REVIEW'}, 'English'),
    ({'issue_number': 'wrong edition'}, 'English'),
    ({}, 'Japanese'),
])
async def test_historical_route_keeps_release_and_exact_identity_guards(monkeypatch, change, language):
    book = deepcopy(cover_book(HISTORICAL[0])); book.update(change)
    with pytest.raises(HTTPException) as exc:
        await invoke(monkeypatch, book, language)
    assert exc.value.status_code == 404
    browser.reference_thumbnail.assert_not_awaited()
