"""First-party Cardmarket guides for unambiguous English One Piece printings.

Both checklists must contain exactly one printing for the release/name/number.
Alternate arts, regional expansions and duplicate products are never resolved
by price, array order or a guessed V1/V2 suffix. No inventory writes occur here.
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

SOURCE = 'CARDMARKET_BULK_SINGLES'
WRITE_SQL = '''insert into tcg.reference_market_prices
 (provider,system_code,language,provider_id,quotes,market_value_minor,market_value_high_minor,
  pricing_updated_at,checked_at,expires_at,refresh_revision)
 select $1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,2
 from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
 where r.provider=$1 and r.system_code=$2 and r.language=$3 and r.provider_id=$4
   and r.name=$11 and r.set_id=$12 and r.card_number=$13 and s.name=$14
 on conflict(provider,system_code,language,provider_id) do update
 set quotes=excluded.quotes,market_value_minor=excluded.market_value_minor,
 market_value_high_minor=excluded.market_value_high_minor,pricing_updated_at=excluded.pricing_updated_at,
 checked_at=excluded.checked_at,expires_at=excluded.expires_at,refresh_revision=excluded.refresh_revision
 where tcg.reference_market_prices.checked_at<=excluded.checked_at'''


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value)).casefold())


def release_identity(name):
    match = re.fullmatch(r'(?:(?:BOOSTER PACK|EXTRA BOOSTER|PREMIUM BOOSTER)\s*)?-?(.+?)-?\s*\[(OP|EB|PRB)-?(\d{2})(?:-?EB\d{2})?\]', name, re.I)
    if not match:
        return None
    title = normalized(match[1])
    # Published English title differs by this one preposition on Cardmarket.
    if title == '500yearsinthefuture':
        title = '500yearsintothefuture'
    return title, match[2].upper()+match[3]


def expansion_index(products):
    result = defaultdict(set)
    for product in products.values():
        # Cardmarket publishes the release name and ID on these set products.
        # A code alone can also refer to a regional release or tournament pack.
        if product.get('categoryName') != 'One Piece Lots':
            continue
        match = re.fullmatch(r'(?:Common|Uncommon|Rare|Super Rare|Full|Common / Uncommon / Rare) Set - (.+) \(((?:OP|EB|PRB)\d{2})\)', product.get('name', ''))
        expansion = product.get('idExpansion')
        if match and type(expansion) is int and expansion > 0:
            result[(normalized(match[1]), match[2])].add(expansion)
    return {key:next(iter(ids)) for key, ids in result.items() if len(ids) == 1}


def matched_products(references, singles, packaging):
    expansions = expansion_index(packaging)
    cards = defaultdict(list)
    for product in singles.values():
        match = re.fullmatch(r'(.+) \(((?:[A-Z]+\d{2}|P)-\d{3})\)', product.get('name', ''))
        if product.get('idCategory') == 1621 and product.get('categoryName') == 'One Piece Single' and match:
            cards[(product.get('idExpansion'), match[2])].append((normalized(match[1]), product))
    groups = defaultdict(list)
    for ref in references:
        if (ref.get('provider') not in {'Bandai Official','Punk Records'}
                or (ref.get('system_code'), ref.get('language')) != ('ONE_PIECE_CARD_GAME','English')):
            continue
        groups[(ref['set_id'], ref['card_number'])].append(ref)
    result = {}
    conflicts = set()
    for (_, number), refs in groups.items():
        # Multiple providers can carry the same exact printing. Distinct
        # printing IDs or conflicting names must still block the match.
        if len({(r['provider_id'],normalized(r['name'])) for r in refs}) != 1:
            continue
        ref = refs[0]
        expansion = expansions.get(release_identity(ref['set_name']))
        candidates = cards.get((expansion, number), []) if expansion else []
        if len(candidates) == 1 and candidates[0][0] == normalized(ref['name']):
            if ref['provider_id'] in result and result[ref['provider_id']]['idProduct'] != candidates[0][1]['idProduct']:
                conflicts.add(ref['provider_id'])
            result[ref['provider_id']] = candidates[0][1]
    return {key:value for key,value in result.items() if key not in conflicts}


async def refresh_one_piece_prices(pool, actor, fx):
    report = {'checked':0, 'matched':0, 'priced':0, 'provider_failures':0}
    now = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            exports = await asyncio.gather(
                download(client,'productList/products_singles_18.json',rows_key='products',now=now),
                download(client,'productList/products_nonsingles_18.json',rows_key='products',now=now),
                download(client,'priceGuide/price_guide_18.json',rows_key='priceGuides',now=now))
        (singles,_),(packaging,_),(prices,observed) = exports
        async with user_connection(pool,actor,str(uuid4())) as connection:
            references = [dict(row) for row in await connection.fetch('''select r.*,s.name as set_name
              from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
              where r.provider in ('Bandai Official','Punk Records') and r.system_code='ONE_PIECE_CARD_GAME' and r.language='English'
                and (s.release_date is null or s.release_date<=current_date)''')]
        matches = matched_products(references,singles,packaging)
        report.update(checked=len(references),matched=len(matches))
        if references and not matches:
            raise ValueError('No unambiguous Cardmarket release matches')
        conversion = await fx.quote(base_currency='EUR',quote_currency='GBP',at=observed)
        values = []
        for ref in references:
            product = matches.get(ref['provider_id'])
            price = prices.get(str(product['idProduct'])) if product else None
            quote = None
            if price and price.get('idCategory') == product['idCategory']:
                try:
                    original = _minor(price.get('trend'))
                    gbp = int((Decimal(original)*conversion.rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                    if gbp > 0:
                        quote = {'source':SOURCE,'product_id':str(product['idProduct']),
                            'expansion_id':product['idExpansion'],'source_field':'trend',
                            'original_currency':'EUR','original_minor':original,'price_gbp_minor':gbp,
                            'observed_at':observed.isoformat(),'finish':'Printing guide',
                            'valuation_role':'MIXED_LANGUAGE_REFERENCE','physical_language_confirmed':False,
                            'condition_specific':False,'match_basis':'UNIQUE_RELEASE_NAME_NUMBER_IN_BOTH_CHECKLISTS',
                            'reference_printing_id':ref['provider_id'],'reference_rarity':ref.get('rarity'),
                            'reference_identity':{key:ref[key] for key in ('name','set_id','card_number','set_name')},
                            'fx_rate_to_gbp':str(conversion.rate),'fx_source':conversion.source,
                            'fx_effective_at':conversion.effective_at.isoformat(),
                            'fx_retrieved_at':conversion.retrieved_at.isoformat()}
                except (ValueError,TypeError,ArithmeticError):
                    pass
            value = quote['price_gbp_minor'] if quote else None
            values.append((ref['provider'],ref['system_code'],ref['language'],ref['provider_id'],
                [quote] if quote else [],value,value,observed if quote else None,now,now+timedelta(days=1),
                ref['name'],ref['set_id'],ref['card_number'],ref['set_name']))
        for start in range(0,len(values),100):
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await connection.executemany(WRITE_SQL,values[start:start+100])
        report['priced'] = sum(row[5] is not None for row in values)
    except (httpx.HTTPError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        # Provider/FX outages preserve previous usable evidence. Ambiguous
        # identities in a successful export are explicitly cleared above.
        report.update(provider_failures=1,reason=type(exc).__name__)
    return report
