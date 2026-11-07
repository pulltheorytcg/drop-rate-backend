"""The exact Seller Hub category requests must retain a safe bounded index."""
from datetime import date
import json
from uuid import UUID

import pytest

from app import catalogue_r2_browse as browse
from app.catalogue_browser import SOURCE_CTE, product_query
from test_catalogue_r2_browse import fixture


OWNER = UUID('10000000-0000-0000-0000-000000000001')
DEFAULTS = [
    dict(category='TCG', product_type='CARD'),
    dict(category='SPORTS', system_code='SPORTS_CARDS', product_type='CARD'),
    dict(category='COMICS', system_code='COMICS', product_type='COMIC'),
    dict(category='MANGA', system_code='MANGA', product_type='COMIC'),
    dict(category='FIGURES', system_code='FIGURES', product_type='FIGURE'),
]


def category_index():
    data = fixture()
    data['reference_sealed_products'].append(dict(
        provider='Bandai Official', system_code='ONE_PIECE_CARD_GAME',
        language='English', set_id='OP15', provider_id='sealed-pack',
        name='Krieg Sealed Pack', product_type='BOOSTER_PACK', image_url=None,
        source_url=None))
    for number, system, kind, name, status in (
        (20, 'MARVEL_COMICS', 'COMIC', 'Hero Marvel', 'VERIFIED'),
        (21, 'DC_COMICS', 'COMIC', 'Hero DC', 'VERIFIED'),
        (22, 'OTHER_COMICS', 'COMIC', 'Hero Indie', 'VERIFIED'),
        (23, 'SPORTS_CARDS', 'CARD', 'Hero Sports', 'VERIFIED'),
        (24, 'SPORTS_CARDS', 'CARD', 'Hero Private Sports', 'NEEDS_REVIEW'),
        (25, 'FIGURES', 'FIGURE', 'Hero Figure', 'VERIFIED'),
        (26, 'FIGURES', 'FIGURE', 'Hero Private Figure', 'NEEDS_REVIEW'),
    ):
        ident = f'10000000-0000-0000-0000-{number:012d}'
        data['catalogue_products'].append(dict(
            id=ident, product_type=kind, game=system, name=name,
            set_name='Hero Series', card_number='1', variant='First',
            rarity='Standard', language='English'))
        data['catalogue_product_profiles'].append(dict(
            catalogue_id=ident, collectible_type=kind, system_code=system,
            set_code='hero-series', release_date='2026-02-01',
            identity_status=status))
    return browse.build_browse_index(data, today=date(2026, 11, 3))


def selected(options, *, index=None, limit=40, offset=0, **kwargs):
    query, params = product_query(owner_id=OWNER, limit=limit, offset=offset, **options)
    sql, args, mode = browse.indexed_catalogue_query(query, params, index or category_index(), **kwargs)
    # The complete original filters, ordering and account-scoped overlays
    # remain authoritative in PostgreSQL after static identity selection.
    assert sql.endswith(query[len(SOURCE_CTE):])
    assert args[:len(params)] == params
    assert 'tcg.inventory_items' in sql and 'tcg.reference_market_prices' in sql
    rows = json.loads(args[-1])
    assert all('owner_id' not in row and 'market_value_minor' not in row for row in rows)
    return rows, mode


@pytest.mark.parametrize('options,expected', list(zip(DEFAULTS, [
    {'OP15-001', 'OP15-001_p1'}, {'Hero Sports'},
    {'Hero Marvel', 'Hero DC', 'Hero Indie'}, {'Volume 1'}, {'Hero Figure'},
])))
def test_actual_category_defaults_never_dispatch_as_text(monkeypatch, options, expected):
    def unexpected(*args, **kwargs):
        raise AssertionError('A category filter is not a text search')
    monkeypatch.setattr(browse, '_system_text_search_page', unexpected)
    monkeypatch.setattr(browse, '_category_text_search_page', unexpected)
    rows, mode = selected(options)
    assert mode == 'FILTERED_NEWEST'
    assert {row['provider_id'] or row['name'] for row in rows} == expected


@pytest.mark.parametrize('options,expected', [
    (dict(category='TCG', system_code='ONE_PIECE_CARD_GAME'),
     {'OP15-001', 'OP15-001_p1', 'sealed-pack'}),
    (dict(category='TCG', system_code='ONE_PIECE_CARD_GAME', product_type='CARD'),
     {'OP15-001', 'OP15-001_p1'}),
    (dict(category='TCG', system_code='ONE_PIECE_CARD_GAME', product_type='SEALED'),
     {'sealed-pack'}),
    (dict(category='COMICS', system_code='DC_COMICS', product_type='COMIC'),
     {'Hero DC'}),
    (dict(category='TCG', system_code='SPORTS_CARDS', product_type='CARD'), set()),
    (dict(category='FIGURES', system_code='FIGURES', product_type='CARD'), set()),
])
def test_category_static_filters_keep_system_and_type_intersection(options, expected):
    rows, mode = selected(options)
    assert mode == 'FILTERED_NEWEST'
    assert {row['provider_id'] or row['name'] for row in rows} == expected


@pytest.mark.parametrize('options,q,expected', [
    (DEFAULTS[0], 'Krieg', {'OP15-001', 'OP15-001_p1'}),
    (DEFAULTS[1], 'Hero', {'Hero Sports'}),
    (DEFAULTS[2], 'Hero', {'Hero Marvel', 'Hero DC', 'Hero Indie'}),
    (DEFAULTS[3], 'Volume', {'Volume 1'}),
    (DEFAULTS[4], 'Hero', {'Hero Figure'}),
    (dict(category='TCG', system_code='ONE_PIECE_CARD_GAME'),
     'Krieg', {'OP15-001', 'OP15-001_p1', 'sealed-pack'}),
    (dict(category='TCG', system_code='ONE_PIECE_CARD_GAME', product_type='SEALED'),
     'Krieg', {'sealed-pack'}),
    (dict(category='COMICS', system_code='DC_COMICS', product_type='COMIC'),
     'Hero', {'Hero DC'}),
    (dict(category='TCG', system_code='SPORTS_CARDS', product_type='CARD'),
     'Hero', set()),
])
def test_category_text_retains_every_matching_identity_before_sql_pagination(options, q, expected):
    rows, mode = selected(dict(options, q=q), limit=1, offset=1)
    assert mode == 'SEARCH_CATEGORY_TEXT'
    assert {row['provider_id'] or row['name'] for row in rows} == expected


@pytest.mark.parametrize('category,q,expected', [
    ('TCG', 'Krieg', {'OP15-001', 'OP15-001_p1', 'sealed-pack'}),
    ('SPORTS', 'Hero', {'Hero Sports'}),
    ('COMICS', 'Hero', {'Hero Marvel', 'Hero DC', 'Hero Indie'}),
    ('MANGA', 'Volume', {'Volume 1'}),
    ('FIGURES', 'Hero', {'Hero Figure'}),
])
def test_category_text_without_redundant_system_or_type(category, q, expected):
    rows, mode = selected(dict(category=category, q=q))
    assert mode in ('SEARCH_CATEGORY_TEXT', 'SEARCH_SYSTEM_TEXT')
    assert {row['provider_id'] or row['name'] for row in rows} == expected


def test_category_text_treats_apostrophe_percent_and_underscore_as_literal():
    data = fixture()
    for row in data['reference_cards']:
        row['name'] = "Krieg's %_ edition"
    index = browse.build_browse_index(data, today=date(2026, 11, 3))
    rows, mode = selected(dict(DEFAULTS[0], q="Krieg's %_"), index=index)
    assert mode == 'SEARCH_CATEGORY_TEXT'
    assert {row['provider_id'] for row in rows} == {'OP15-001', 'OP15-001_p1'}


@pytest.mark.parametrize('changes', [
    dict(q='OP15-001'), dict(q='クリエグ'), dict(q='Krieg  edition'),
    dict(owned='owned'), dict(owned='not_owned'),
    dict(keys=['c:10000000-0000-0000-0000-000000000001']),
    dict(language='English'), dict(set_id='OP15'), dict(provider='Bandai Official'),
    dict(sort='value_asc'), dict(sort='name'), dict(offset=513),
])
def test_category_text_unsupported_shapes_retain_sql_fallback(changes):
    options = dict(DEFAULTS[0], q='Krieg', system_code='ONE_PIECE_CARD_GAME')
    options.update(changes)
    query, params = product_query(owner_id=OWNER, **options)
    with pytest.raises(ValueError):
        browse.indexed_catalogue_query(query, params, category_index(), owned={})


def test_category_text_candidate_bound_and_full_query_verification():
    options = dict(DEFAULTS[0], q='Krieg', system_code='ONE_PIECE_CARD_GAME')
    query, params = product_query(owner_id=OWNER, **options)
    with pytest.raises(ValueError, match='shortlist bound'):
        browse.indexed_catalogue_query(query, params, category_index(), max_candidates=1)
    changed = query.replace(' order by case when false then 0',
                            ' and e.catalogue_id is not null order by case when false then 0', 1)
    assert changed != query
    with pytest.raises(ValueError, match='verified SQL'):
        browse.indexed_catalogue_query(changed, params, category_index())


def test_category_static_unknown_predicate_retains_sql_fallback():
    query, params = product_query(owner_id=OWNER, **DEFAULTS[2])
    changed = query.replace(' order by e.release_date desc',
                            ' and e.catalogue_id is not null order by e.release_date desc', 1)
    with pytest.raises(ValueError, match='query shape'):
        browse.indexed_catalogue_query(changed, params, category_index())
