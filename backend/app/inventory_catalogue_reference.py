"""Display-only catalogue guides for copies without an exact valuation.

Reading a guide never assigns condition, confirms a printing, prices stock or
supplies a retail recommendation. Use the shared cache, with its real source
date; do not make provider requests while rendering an account.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID

from .cardmarket_valuations import bandai_name, rarity_key
from .language import clean_language
from .one_piece_market import normalized, release_identity
from .recognition_games import SYSTEM_BY_GAME, collector_key
from .reference_market import _text, _time

# A media review is NOT proof that a market source is invalid. Allow only
# display-only references when every pending mapping is a fully deterministic,
# language/printing-specific identity backed by an actual source checklist.
# Do not update match_status; the priced physical-copy resolver retains its
# stricter REVIEW veto in REFERENCE_VALUES_SQL.
#
# Explicit REJECTED mappings, non-media reviews, unknown identities, conflicting
# languages, and missing source IDs still block ALL price displays. The later
# reference_candidates() + catalogue_guide() also reject ambiguous printings
# and quote/source/FX/age mismatches. Neither supplies retail recommendations.
PRODUCTS_SQL = """select p.*,
 exists(select 1 from tcg.provider_catalogue_mappings m where m.catalogue_id=p.id
   and m.match_status in ('REVIEW','REJECTED')
   and not (
     p.product_type='CARD' and p.language='Japanese'
     and m.match_status='REVIEW'
     and m.verification_basis='DETERMINISTIC_EXACT'
     and m.confidence=1
     and m.provider_entity_type='CARD_PRINTING'
     and m.provider_language=p.language
     and m.provider_variant_key=p.variant
     and m.metadata->>'media_approval_status'='PENDING'
     and nullif(m.metadata->>'media_asset_id','') is not null
     and (
       (p.game='One Piece' and m.source_provider='Punk Records'
        and m.provider_id=p.card_number)
       or
       (p.game='Pokemon' and m.source_provider='TCGdex')
     )
     and exists (
       select 1 from tcg.reference_cards r
       join tcg.reference_sets s
         on (s.provider,s.system_code,s.language,s.set_id)=
            (r.provider,r.system_code,r.language,r.set_id)
       where (r.provider,r.system_code,r.language,r.provider_id)=
         (m.source_provider,m.system_code,m.provider_language,m.provider_id)
         and r.card_number=p.card_number
         and (s.release_date is null or s.release_date<=current_date)
         and (
           (p.game='One Piece' and r.system_code='ONE_PIECE_CARD_GAME')
           or (p.game='Pokemon' and r.system_code='POKEMON_TCG'
             and lower(r.name)=lower(p.name) and lower(s.name)=lower(p.set_name))
         )
     )
   ))
 or exists(select 1 from tcg.market_source_mappings m where m.catalogue_id=p.id
   and m.source='CARDMARKET' and m.match_status in ('REVIEW','REJECTED')) as blocked
 from tcg.catalogue_products p where p.id=any($1::uuid[])"""

# The existing global number-key index bounds this lookup. Unpriced siblings
# are retained: quote availability must never select a printing.
CACHE_SQL = """select k.catalogue_id,r.provider,r.system_code,r.language,r.provider_id,
 r.set_id,r.name,r.card_number,r.rarity,s.name as set_name,
 coalesce(m.quotes,'[]'::jsonb) as quotes,
 coalesce(b.quotes,'[]'::jsonb) as catalogue_quotes
 from tcg.reference_cards r
 join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices m using(provider,system_code,language,provider_id)
 left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
 join jsonb_to_recordset($1::jsonb) k(catalogue_id text,system_code text,number_key text)
   on r.system_code=k.system_code and r.number_key=k.number_key
 where s.release_date is null or s.release_date<=current_date"""


def reference_candidates(product, rows, language):
    """Exact selected reference, or a uniquely identified ordinary import."""
    system = SYSTEM_BY_GAME.get(product.get('game'))
    if not system or product.get('blocked'):
        return []
    rows = [r for r in rows if r['system_code'] == system]
    selected = [r for r in rows if r['language'] == language
                and (product.get('variant'), product.get('name'), product.get('set_name'),
                     product.get('card_number'), product.get('rarity')) ==
                    (r['provider_id'], r['name'], r['set_name'], r['card_number'], r.get('rarity') or 'Unknown')]
    if selected:
        return selected
    if system == 'POKEMON_TCG' and product.get('variant') in {'Normal', 'Holofoil', 'Reverse Holofoil'}:
        return [r for r in rows if r['provider'] == 'TCGdex' and r['language'] == language
                and _text(product.get('name')) == _text(r['name'])
                and _text(product.get('set_name')) == _text(r['set_name'])
                and collector_key(product.get('card_number')) == collector_key(r['card_number'])
                and (_text(product.get('rarity')) in {'', 'unknown'} or not r.get('rarity')
                     or _text(product['rarity']) == _text(r['rarity']))]
    if system != 'ONE_PIECE_CARD_GAME' or product.get('variant') not in {'Normal', 'Foil', 'Holofoil'}:
        return []
    # Legacy Japanese imports often retain an English name. Require the exact
    # English base identity AND the Japanese cache's explicit counterpart link.
    english = []
    title = normalized(product.get('set_name'))
    if title == '500yearsinthefuture':
        title = '500yearsintothefuture'
    for row in rows:
        release = release_identity(row['set_name'], include_starters=False)
        rarity = rarity_key(row.get('rarity'))
        expected = {'C': 'Normal', 'UC': 'Normal', 'L': 'Normal', 'R': 'Foil', 'SR': 'Foil', 'SEC': 'Foil'}.get(rarity)
        if (row['provider'] == 'Punk Records' and row['language'] == 'English'
                and row['provider_id'] == row['card_number'] and release and release[0] == title
                and collector_key(product.get('card_number')) == collector_key(row['card_number'])
                and bandai_name(product.get('name'), product.get('card_number')) == bandai_name(row['name'], row['card_number'])
                and rarity_key(product.get('rarity')) == rarity
                and ('Foil' if product.get('variant') == 'Holofoil' else product.get('variant')) == expected):
            english.append(row)
    if len(english) != 1:
        return []
    if language == 'English':
        return english
    if language != 'Japanese':
        return []
    en = english[0]
    return [r for r in rows if r['provider'] == en['provider'] and r['language'] == 'Japanese'
            and r['provider_id'] == en['provider_id'] and r['card_number'] == en['card_number']
            and rarity_key(r.get('rarity')) == rarity_key(en.get('rarity'))
            and any(q.get('match_basis') == 'OFFICIAL_JP_EN_BASE_ID_AND_UNIQUE_NONENGLISH_MARKET_PRODUCT'
                    and q.get('english_checklist_provider_id') == en['provider_id']
                    and q.get('english_checklist_set_id') == en['set_id']
                    for q in r.get('quotes') or [] if isinstance(q, dict))]


def catalogue_guide(product, rows, language, *, now):
    candidates = reference_candidates(product, rows, language)
    identities = {(r['provider'], r['system_code'], r['language'], r['provider_id']) for r in candidates}
    if len(identities) != 1:
        return None
    row = candidates[0]
    identity = {key: row[key] for key in ('name', 'set_id', 'card_number', 'set_name')}
    eligible = []
    for quote in (row.get('quotes') or []) + (row.get('catalogue_quotes') or []):
        if not isinstance(quote, dict):
            continue
        source = quote.get('source')
        if source not in {'TCGDEX_CARDMARKET', 'TCGDEX_CARDMARKET_VARIANT', 'CARDMARKET_CATALOGUE', 'CARDMARKET_BULK_SINGLES'}:
            continue
        if quote.get('reference_language', language) != language:
            continue
        if source in {'CARDMARKET_CATALOGUE', 'CARDMARKET_BULK_SINGLES'}:
            if quote.get('reference_identity') != identity:
                continue
            if source == 'CARDMARKET_BULK_SINGLES' and (quote.get('reference_printing_id') != row['provider_id']
                    or quote.get('reference_rarity') != row.get('rarity')):
                continue
        # An imported finish is known: do not show its alternate foil's price.
        finish = product.get('variant')
        if source.startswith('TCGDEX_') and finish in {'Normal', 'Holofoil', 'Reverse Holofoil'}:
            if source != 'TCGDEX_CARDMARKET' or quote.get('finish') != finish:
                continue
        if language == 'Japanese' and source == 'CARDMARKET_BULK_SINGLES' and quote.get('valuation_role') != 'MIXED_NON_ENGLISH_REFERENCE':
            continue
        try:
            amount, original = quote['price_gbp_minor'], quote['original_minor']
            checked = _time(quote['observed_at'])
            rate = Decimal(str(quote['fx_rate_to_gbp']))
            if (type(amount) is not int or type(original) is not int or amount <= 0 or original <= 0
                    or quote.get('original_currency') != 'EUR' or quote.get('fx_source') != 'ECB_EURO_REFERENCE_RATES'
                    or not rate.is_finite() or rate <= 0 or not now-timedelta(days=7) <= checked <= now
                    or int((Decimal(original)*rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) != amount):
                continue
        except (ValueError, TypeError, KeyError, InvalidOperation):
            continue
        eligible.append((amount, checked, quote))
    if not eligible:
        return None
    # Match catalogue source precedence: detailed quotes before broad guides.
    detailed = [v for v in eligible if v[2]['source'].startswith('TCGDEX_')]
    eligible = detailed or eligible
    regional = any(v[2].get('valuation_role') == 'MIXED_NON_ENGLISH_REFERENCE' for v in eligible)
    all_finishes = any(v[2]['source'] == 'CARDMARKET_CATALOGUE' for v in eligible)
    return {'status': 'CATALOGUE_GUIDE', 'currency': 'GBP',
            'market_value_minor': min(v[0] for v in eligible),
            'market_value_high_minor': max(v[0] for v in eligible),
            'checked_at': min(v[1] for v in eligible), 'basis': language + ' · Raw catalogue reference',
            'label': 'Regional guide' if regional else 'All-finish guide' if all_finishes else 'Catalogue guide',
            'reason': ('Non-English regional guide; not a Japanese condition-specific sale.' if regional
                       else 'Catalogue range across finishes, conditions and languages; not a valuation of this copy.' if all_finishes
                       else 'Cardmarket catalogue guide across conditions and languages; not a valuation of this copy.'),
            'reference_id': ':'.join(next(iter(identities))),
            'physical_valuation_eligible': False, 'recommended_retail_minor': None}


async def add_catalogue_references(connection, items, *, now):
    """Only augment missing raw-copy displays, never compatibility money fields."""
    pending = [i for i in items if i.get('catalogue_id') and i.get('product_type') == 'CARD'
               and i.get('market_value_minor') is None and not i.get('grading_company')
               and not i.get('grade') and not i.get('seal_status')
               and not (i.get('catalogue_reference') or {}).get('market_value_minor')]
    if not pending:
        return items
    products, references = {}, defaultdict(list)
    ids = list(dict.fromkeys(UUID(str(i['catalogue_id'])) for i in pending))
    for start in range(0, len(ids), 100):
        batch = [dict(r) for r in await connection.fetch(PRODUCTS_SQL, ids[start:start+100])]
        lookups = []
        for product in batch:
            products[str(product['id'])] = product
            system = SYSTEM_BY_GAME.get(product.get('game'))
            key = collector_key(product.get('card_number'))
            if system and key and not product.get('blocked'):
                lookups.append({'catalogue_id': str(product['id']), 'system_code': system, 'number_key': key})
        if lookups:
            for row in await connection.fetch(CACHE_SQL, json.dumps(lookups)):
                references[str(row['catalogue_id'])].append(dict(row))
    for item in pending:
        product = products.get(str(item['catalogue_id']))
        if not product:
            continue
        language = clean_language(item.get('language')) or clean_language(product.get('language'))
        canonical_language = clean_language(product.get('language'))
        if not language or (canonical_language and canonical_language != language):
            continue
        guide = catalogue_guide(product, references[str(item['catalogue_id'])], language, now=now)
        if guide:
            item['catalogue_reference'] = guide
    return items
