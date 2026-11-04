from unittest.mock import AsyncMock

import pytest

from app import catalogue_coverage_context as context


def row(status, count, artwork=0):
    return {'kind': 'CARD', 'status': status, 'system_code': 'POKEMON_TCG',
            'products': count, 'artwork_urls': artwork}


def publication(system, count, **extra):
    return {'provider': system.lower(), 'system_code': system, 'language': 'English',
            'record_count': count, 'generation': 1, 'active': True, **extra}


def test_expanded_catalogue_does_not_claim_prices_artwork_or_owned_copies():
    result = context.catalogue_context([
        row('REFERENCE_AVAILABLE', 39863, 39000), row('EXACT_QUOTE_UNAVAILABLE', 27354, 24901),
        row('NOT_APPLICABLE_DIGITAL', 2480, 2321),
        {'kind': 'SEALED', 'status': 'REFERENCE_AVAILABLE', 'products': 3893, 'artwork_urls': 3889},
    ], [publication('YUGIOH', 45215), publication('DISNEY_LORCANA', 3505),
        publication('MAGIC_THE_GATHERING', 153662, manifest_key='PRIVATE/KEY'),
        publication('SPORTS_CARDS', 1722), publication('FIGURES', 4),
        publication('RIFTBOUND', 99, active=False)], r2_enabled=True)
    assert result['stored_physical_tcg_references'] == 269599
    assert result['sql_physical_card_references'] == 67217
    assert result['r2_physical_tcg_references'] == 202382
    assert result['sql_physical_artwork'] == {
        'references': 67217, 'with_url': 63901, 'missing_url': 3316, 'image_delivery_verified': False}
    assert result['unpublished_tcg_games'] == [
        {'system_code': 'RIFTBOUND', 'game': 'Riftbound', 'status': 'NOT_PUBLISHED'}]
    assert result['global_market_value_coverage'] is None
    assert result['price_coverage_scope'] == 'SQL_PHYSICAL_REFERENCE_CARDS_ONLY'
    assert all(source['market_value_coverage'] == 'NOT_MEASURED' for source in result['published_sources'])
    assert 'PRIVATE/KEY' not in str(result)


def test_disabled_reader_and_overlapping_games_cannot_claim_global_total():
    result = context.catalogue_context([row('REFERENCE_AVAILABLE', 2)], [], r2_enabled=False)
    assert result['stored_physical_tcg_references'] is None
    assert result['r2_physical_tcg_references'] is None
    assert result['unpublished_tcg_games'] == []
    assert result['status'] == 'R2_READER_DISABLED'
    result = context.catalogue_context([row('REFERENCE_AVAILABLE', 2)],
                                       [publication('POKEMON_TCG', 2)], r2_enabled=True)
    assert result['stored_physical_tcg_references'] is None
    assert result['status'] == 'OVERLAPPING_SOURCES_REQUIRE_RECONCILIATION'


@pytest.mark.parametrize('count', [-1, '12', True])
def test_invalid_import_counts_fail_closed(count):
    with pytest.raises(ValueError, match='published catalogue'):
        context.catalogue_context([], [publication('YUGIOH', count)], r2_enabled=True)


def test_duplicate_publications_and_invalid_artwork_do_not_inflate_coverage():
    with pytest.raises(ValueError, match='published catalogue'):
        context.catalogue_context([], [publication('YUGIOH', 2)] * 2, r2_enabled=True)
    with pytest.raises(ValueError, match='artwork'):
        context.catalogue_context([row('REFERENCE_AVAILABLE', 2, 3)], [], r2_enabled=True)


@pytest.mark.asyncio
async def test_capacity_pause_and_publication_failures_are_reported_honestly(monkeypatch):
    monkeypatch.setattr(context.r2_first_service, 'enabled', lambda: True)
    monkeypatch.setattr(context.r2_first_service, 'sources', AsyncMock(return_value=[publication('YUGIOH', 2)]))
    connection = AsyncMock()
    connection.fetchrow.return_value = {'database_bytes': 430394515, 'default_read_only': 'off'}
    result = await context.read_catalogue_context(connection, [row('REFERENCE_AVAILABLE', 2)])
    assert result['automatic_price_refresh']['status'] == 'PAUSED'
    assert result['automatic_price_refresh']['reason'] == 'BULK_REFRESH_DEFERRED_CAPACITY'
    assert result['catalogue']['stored_physical_tcg_references'] == 4
    connection.execute.assert_not_called()
    monkeypatch.setattr(context.r2_first_service, 'sources', AsyncMock(side_effect=RuntimeError('registry unavailable')))
    with pytest.raises(RuntimeError, match='registry unavailable'):
        await context.read_catalogue_context(connection, [])
