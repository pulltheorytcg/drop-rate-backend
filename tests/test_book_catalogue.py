import json
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.book_catalogue import publisher_page, with_book_details
from app.book_market import eligibility
from scripts.seed_book_catalogue import load_seed, seed_sql


def test_starter_has_released_unique_editions_without_physical_or_price_claims():
    data = load_seed()
    assert len(data['entries']) == 14
    assert sum(row['book']['system_code'] == 'MANGA' for row in data['entries']) == 10
    for row in data['entries']:
        assert row['book']['printing_number'] is None
        assert row['book']['cover_code'] is None
        assert eligibility({'book_printing': {**row['book'], 'identity_status': row['identity_status'],
                                            'profile_status': row['identity_status']}}) == 'BOOK_PRINTING_REVIEW_REQUIRED'
    sql = seed_sql(data)
    for table in ('inventory_items', 'media_assets', 'pricing_snapshots', 'reference_market_history', 'shopify_inventory_links'):
        assert table not in sql


@pytest.mark.parametrize('url', ['https://www.viz.com.evil.test/manga-books/manga/1',
    'javascript:alert(1)', 'https://www.dc.com@evil.test/comics/a',
    'https://www.marvel.com:444/comics/issue/1', 'https://www.dc.com/comics/a?next=evil',
    'https://www.viz.com/other/1'])
def test_publisher_links_reject_unapproved_origins(url):
    assert publisher_page(url) is None


@pytest.mark.asyncio
async def test_book_details_do_not_expose_private_metadata_prices_or_approve_cover():
    row = load_seed()['entries'][0]
    catalogue_id = UUID(row['id'])
    details = {**row['book'], 'catalogue_id': catalogue_id,
        'identity_status': 'STRUCTURED', 'profile_status': 'STRUCTURED',
        'attributes': json.dumps({'publisher': 'VIZ Media', 'book_format': 'MANGA',
            'identity_source': 'OFFICIAL_PUBLISHER_CATALOGUE', 'source_url': row['source_url'],
            'cover_source_url': row['cover_source_url'], 'submitted_by_user_id': 'private',
            'condition': 'Mint', 'market_value_minor': 99999})}
    connection = AsyncMock(); connection.fetch.return_value = [details]
    original = {'catalogue_id': catalogue_id, 'product_type': 'COMIC', 'language': 'English',
                'display_image_url': None, 'market_value_minor': None}
    result = (await with_book_details(connection, [original]))[0]
    assert result['book_details'] == {**row['book'], 'language': 'English'}
    assert result['publisher_source_url'] == row['source_url']
    assert result['market_value_minor'] is None and result['display_image_url'] is None
    assert 'private' not in str(result) and 'cover_source_url' not in str(result)
    assert original.get('book_details') is None
    details['identity_status'] = 'NEEDS_REVIEW'
    result = (await with_book_details(connection, [original]))[0]
    assert 'publisher_source_url' not in result


@pytest.mark.asyncio
async def test_nonbook_pages_do_not_read_book_tables():
    connection = AsyncMock()
    assert await with_book_details(connection, [{'product_type': 'CARD'}]) == [{'product_type': 'CARD'}]
    connection.fetch.assert_not_awaited()
