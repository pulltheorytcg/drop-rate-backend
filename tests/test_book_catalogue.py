import json
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.book_catalogue import publisher_page, with_book_details
from app.book_artwork import book_cover_reference, publisher_cover_url, reviewed_covers
from app.book_market import eligibility
from app.recognition_images import _trusted_reference_url
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
        'profile_release_date': row['release_date'],
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
    assert result['artwork_kind'] == 'PUBLISHER_REFERENCE'
    assert 'reference_kind=book' in result['reference_image_path']
    assert result['book_market_status'] == 'PRINTING_REVIEW_REQUIRED'
    assert 'LH_Sold=1' in result['book_sold_search_url']
    assert 'private' not in str(result) and 'cover_source_url' not in str(result)
    assert original.get('book_details') is None
    details['identity_status'] = 'NEEDS_REVIEW'
    result = (await with_book_details(connection, [original]))[0]
    assert 'publisher_source_url' not in result
    assert 'reference_image_path' not in result


def cover_book(row):
    return {**row['book'], 'catalogue_id': UUID(row['id']),
        'identity_status': 'STRUCTURED', 'profile_status': 'STRUCTURED',
        'profile_release_date': row['release_date'],
        'attributes': {'publisher': row['book']['publisher'], 'book_format': row['book']['book_format'],
            'identity_source': 'OFFICIAL_PUBLISHER_CATALOGUE', 'source_url': row['source_url'],
            'cover_rights_status': 'PENDING'}}


def test_all_fourteen_reviewed_covers_match_exact_edition_and_safe_transport():
    assert len(reviewed_covers()) == 14
    for row in load_seed()['entries']:
        cover = book_cover_reference(cover_book(row), row['language'])
        assert cover and cover['catalogue_id'] == row['id']
        assert publisher_cover_url(cover['image_url']) and _trusted_reference_url(cover['image_url'])
        assert min(cover['observed_width'], cover['observed_height']) >= 200
        assert len(cover['observed_sha256']) == 64


@pytest.mark.parametrize('change', [
    {'catalogue_id': UUID(int=9)}, {'issue_number': '999'}, {'printing_number': 2},
    {'cover_code': 'Variant B'}, {'profile_status': 'NEEDS_REVIEW'},
    {'identity_status': 'LEGACY_UNREVIEWED'}, {'profile_release_date': '2099-01-01'},
    {'attributes': {'source_url': 'https://www.dc.com/comics/wrong'}},
    {'attributes': {'cover_rights_status': 'REVOKED'}},
    {'attributes': {'cover_source_status': 'INACTIVE'}},
])
def test_reference_cover_never_crosses_identity_or_revocation(change):
    row = load_seed()['entries'][0]; book = cover_book(row)
    if 'attributes' in change:
        book['attributes'].update(change['attributes'])
    else:
        book.update(change)
    assert book_cover_reference(book, 'English') is None
    assert book_cover_reference(cover_book(row), 'Japanese') is None


@pytest.mark.parametrize('url', [
    'https://dw9to29mmj727.cloudfront.net.evil.test/products/1569319014.jpg',
    'https://user@dw9to29mmj727.cloudfront.net/products/1569319014.jpg',
    'https://dw9to29mmj727.cloudfront.net:8443/products/1569319014.jpg',
    'https://other.cloudfront.net/products/1569319014.jpg',
    'https://static.dc.com/2024-09/../private.jpg',
    'https://static.dc.com/2024-09/cover.jpg?url=https://127.0.0.1',
    'http://cdn.marvel.com/u/prod/marvel/i/mg/4/10/6596e0f7d0718/clean.jpg',
    'https://cdn.marvel.com/u/prod/marvel/i/mg/4/10/6596e0f7d0718/clean.jpg#x',
])
def test_cover_sources_reject_unreviewed_hosts_paths_and_queries(url):
    assert not publisher_cover_url(url)
    assert not _trusted_reference_url(url)


@pytest.mark.asyncio
async def test_approved_copy_artwork_keeps_priority_over_reference_cover():
    row = load_seed()['entries'][0]
    connection = AsyncMock(); connection.fetch.return_value = [cover_book(row)]
    original = {'catalogue_id': UUID(row['id']), 'product_type': 'COMIC', 'language': 'English',
        'display_image_url': 'https://cdn.shopify.com/approved-copy.jpg', 'market_value_minor': 1234}
    result = (await with_book_details(connection, [original]))[0]
    assert result['display_image_url'] == original['display_image_url']
    assert result['market_value_minor'] == 1234 and result['book_market_status'] == 'AVAILABLE'
    assert 'reference_image_path' not in result and 'artwork_kind' not in result


@pytest.mark.asyncio
async def test_nonbook_pages_do_not_read_book_tables():
    connection = AsyncMock()
    assert await with_book_details(connection, [{'product_type': 'CARD'}]) == [{'product_type': 'CARD'}]
    connection.fetch.assert_not_awaited()
