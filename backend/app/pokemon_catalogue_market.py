"""Database-wide Cardmarket guides for Pokémon checklists missing cross-IDs.

The public export omits collector numbers. Match only a complete release whose
name occurs exactly once in BOTH checklists. Duplicate arts/editions cannot be
resolved by a cheap price, product ordering or the presence of a quote. These
mixed-language/condition guides are never inputs to physical-copy valuations.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

import httpx

from .db import user_connection
from .reference_market import _minor
from .sealed_market import download

SOURCE = 'CARDMARKET_CATALOGUE'
READ_SQL = '''select r.*,s.name as set_name,s.declared_card_count
 from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
 where r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language='English'
 and (s.release_date is null or s.release_date<=current_date)'''
WRITE_SQL = '''insert into tcg.reference_catalogue_prices
 (provider,system_code,language,provider_id,quotes,market_value_minor,market_value_high_minor,
  pricing_updated_at,checked_at,expires_at)
 select $1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10
 from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
 where r.provider=$1 and r.system_code=$2 and r.language=$3 and r.provider_id=$4
 and r.name=$11 and r.set_id=$12 and r.card_number=$13 and s.name=$14
 on conflict(provider,system_code,language,provider_id) do update set
 quotes=excluded.quotes,market_value_minor=excluded.market_value_minor,
 market_value_high_minor=excluded.market_value_high_minor,pricing_updated_at=excluded.pricing_updated_at,
 checked_at=excluded.checked_at,expires_at=excluded.expires_at
 where tcg.reference_catalogue_prices.checked_at<=excluded.checked_at'''


def normalized(value):
    value = unicodedata.normalize('NFKC', str(value)).casefold()
    return re.sub(r'[^\w]', '', value.replace('♀', 'female').replace('♂', 'male'))


def matched_products(references, singles, packaging):
    expansions = defaultdict(set)
    for product in packaging.values():
        name = product.get('name', '')
        expansion = product.get('idExpansion')
        if (product.get('idCategory') == 52 and product.get('categoryName') == 'Pokémon Booster'
                and name.endswith(' Booster') and type(expansion) is int and expansion > 0):
            expansions[normalized(name[:-8])].add(expansion)
    products = defaultdict(list)
    for product in singles.values():
        if product.get('idCategory') == 51 and product.get('categoryName') == 'Pokémon Single':
            # The bracket is an attack description, not a printing/edition suffix.
            name = re.sub(r' \[[^\[\]]+\]$', '', product.get('name', ''))
            products[(product.get('idExpansion'), normalized(name))].append(product)
    groups = defaultdict(list)
    sets = defaultdict(set)
    for ref in references:
        if (ref.get('provider'), ref.get('system_code'), ref.get('language')) != ('TCGdex','POKEMON_TCG','English'):
            continue
        groups[(ref['set_id'], normalized(ref['name']))].append(ref)
        sets[ref['set_id']].add(ref['provider_id'])
    result = {}
    for (set_id, name), refs in groups.items():
        if len(refs) != 1:
            continue
        ref = refs[0]
        declared = ref.get('declared_card_count')
        if type(declared) is not int or declared <= 0 or len(sets[set_id]) < declared:
            continue
        expansion_ids = expansions.get(normalized(ref['set_name']), set())
        if len(expansion_ids) != 1:
            continue
        candidates = products.get((next(iter(expansion_ids)), name), [])
        if len(candidates) == 1:
            result[ref['provider_id']] = candidates[0]
    return result


def quotes_for(ref, product, price, observed, conversion):
    if not product or not price or price.get('idCategory') != 51 or str(price.get('idProduct')) != str(product['idProduct']):
        return []
    quotes = []
    for field, label in (('trend','Printing guide'), ('trend-holo','Alternative foil guide')):
        try:
            original = _minor(price.get(field))
            gbp = int((Decimal(original)*conversion.rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            if gbp <= 0:
                continue
        except (ValueError,TypeError,ArithmeticError):
            continue
        quotes.append({'source':SOURCE,'product_id':str(product['idProduct']),
            'expansion_id':product['idExpansion'],'source_field':field,
            'original_currency':'EUR','original_minor':original,'price_gbp_minor':gbp,
            'observed_at':observed.isoformat(),'finish':label,
            'valuation_role':'MIXED_LANGUAGE_REFERENCE','physical_language_confirmed':False,
            'condition_specific':False,'physical_valuation_eligible':False,
            'match_basis':'UNIQUE_NAME_IN_COMPLETE_RELEASE_CHECKLISTS',
            'collector_number_supplied_by_marketplace':False,
            'reference_identity':{key:ref[key] for key in ('name','set_id','card_number','set_name')},
            'fx_rate_to_gbp':str(conversion.rate),'fx_source':conversion.source,
            'fx_effective_at':conversion.effective_at.isoformat(),'fx_retrieved_at':conversion.retrieved_at.isoformat()})
    return quotes


async def refresh_pokemon_catalogue_prices(pool, actor, fx):
    report = {'checked':0,'matched':0,'priced':0,'provider_failures':0,'inventory_rows_read':0}
    now = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=45,follow_redirects=False) as client:
            exports = await asyncio.gather(
                download(client,'productList/products_singles_6.json',rows_key='products',now=now),
                download(client,'productList/products_nonsingles_6.json',rows_key='products',now=now),
                download(client,'priceGuide/price_guide_6.json',rows_key='priceGuides',now=now))
        (singles,_),(packaging,_),(prices,observed) = exports
        async with user_connection(pool,actor,str(uuid4())) as connection:
            references = [dict(row) for row in await connection.fetch(READ_SQL)]
        matches = matched_products(references,singles,packaging)
        report.update(checked=len(references),matched=len(matches))
        if references and not matches:
            raise ValueError('No unambiguous Cardmarket release matches')
        conversion = await fx.quote(base_currency='EUR',quote_currency='GBP',at=observed)
        values = []
        for ref in references:
            product = matches.get(ref['provider_id'])
            price = prices.get(str(product['idProduct'])) if product else None
            quotes = quotes_for(ref,product,price,observed,conversion)
            amounts = [q['price_gbp_minor'] for q in quotes]
            values.append((ref['provider'],ref['system_code'],ref['language'],ref['provider_id'],
                quotes,min(amounts) if amounts else None,max(amounts) if amounts else None,
                observed if quotes else None,now,now+timedelta(days=1),
                ref['name'],ref['set_id'],ref['card_number'],ref['set_name']))
        for start in range(0,len(values),100):
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await connection.executemany(WRITE_SQL,values[start:start+100])
        report['priced'] = sum(row[5] is not None for row in values)
    except (httpx.HTTPError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        report.update(provider_failures=1,reason=type(exc).__name__)
    return report
