"""Reconcile SQL coverage with published metadata without fetching R2 objects.

Publication counts are stored source printing references, including future
releases. They are not distinct card names, inventory, or measured valuations.
Only public aggregate fields leave this module; private manifest keys do not.
"""
from datetime import datetime, timezone

from .database_capacity import check_database_capacity
from . import r2_first_service


def catalogue_context(rows, publications, *, r2_enabled):
    legacy = [dict(row) for row in rows if row['kind'] == 'CARD'
              and row['status'] != 'NOT_APPLICABLE_DIGITAL']
    legacy_total = sum(row['products'] for row in legacy)
    legacy_systems = {row['system_code'] for row in legacy}
    seen = set()
    imported = []
    overlap = False
    for publication in publications:
        if not publication.get('active', False):
            continue
        identity = tuple(publication[key] for key in ('provider', 'system_code', 'language'))
        count = publication['record_count']
        if identity in seen or type(count) is not int or count < 0:
            raise ValueError('Invalid published catalogue count')
        seen.add(identity)
        system = publication['system_code']
        # Counts from separate stores cannot silently double-count a game.
        overlap |= system in legacy_systems
        imported.append({
            'provider': publication['provider'], 'system_code': system,
            'game': r2_first_service.GAMES.get(system, system),
            'language': publication['language'], 'stored_references': count,
            'generation': publication['generation'],
            'category': 'TCG' if system in r2_first_service.TCG_GAMES else 'OTHER',
            'pricing_feed': 'NOT_IMPORTED', 'artwork_feed': 'NOT_IMPORTED',
            'market_value_coverage': 'NOT_MEASURED',
        })
    tcg_total = sum(row['stored_references'] for row in imported if row['category'] == 'TCG')
    artwork_known = all('artwork_urls' in row for row in legacy)
    artwork = sum(row.get('artwork_urls', 0) for row in legacy)
    if any(type(row.get('artwork_urls', 0)) is not int
           or not 0 <= row.get('artwork_urls', 0) <= row['products'] for row in legacy):
        raise ValueError('Invalid artwork coverage count')
    return {
        'status': ('R2_READER_DISABLED' if not r2_enabled else
                   'OVERLAPPING_SOURCES_REQUIRE_RECONCILIATION' if overlap else 'CURRENT'),
        'count_unit': 'SOURCE_PRINTING_FINISH_REFERENCE',
        'sql_physical_card_references': legacy_total,
        'r2_physical_tcg_references': tcg_total if r2_enabled else None,
        'stored_physical_tcg_references': None if overlap or not r2_enabled else legacy_total + tcg_total,
        'r2_reader_enabled': r2_enabled,
        'published_sources': sorted(imported, key=lambda row: (row['system_code'], row['provider'], row['language'])),
        'unpublished_tcg_games': [
            {'system_code': system, 'game': name, 'status': 'NOT_PUBLISHED'}
            for system, name in sorted(r2_first_service.TCG_GAMES.items())
            if r2_enabled and not any(row['system_code'] == system for row in imported)
        ],
        'sql_physical_artwork': {
            'references': legacy_total, 'with_url': artwork if artwork_known else None,
            'missing_url': legacy_total - artwork if artwork_known else None,
            'image_delivery_verified': False,
        },
        'price_coverage_scope': 'SQL_PHYSICAL_REFERENCE_CARDS_ONLY',
        'global_market_value_coverage': None,
        'note': ('Stored references include future releases and printing/finish variants. '
                 'New metadata imports do not establish artwork, market values or owned stock. '
                 'SQL price-reference percentages exclude these imports and are not a global market-value percentage.'),
    }


async def read_catalogue_context(connection, rows):
    publications = await r2_first_service.sources(connection)
    capacity = await check_database_capacity(connection)
    return {
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'catalogue': catalogue_context(rows, publications, r2_enabled=r2_first_service.enabled()),
        'automatic_price_refresh': {
            'status': 'CAPACITY_PERMITS_REFRESH' if capacity.refresh_allowed else 'PAUSED',
            **capacity.report(),
            'note': ('Capacity eligibility does not prove provider availability or job completion. '
                     'Expired evidence is excluded from current price-reference coverage.'),
        },
    }
