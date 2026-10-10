"""Cardmarket's own daily Dragon Ball guides, matched to complete checklists.

Masters and Fusion World share Cardmarket game 13, but not release identities.
No product order, price order, parallel suffix or translated name is guessed.
"""
from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

import httpx

from .db import user_connection
from .one_piece_market import SOURCE, WRITE_SQL, normalized
from .reference_market import _minor
from .sealed_market import download

MASTERS = 'DRAGON_BALL_SUPER_MASTERS'
FUSION = 'DRAGON_BALL_SUPER_FUSION_WORLD'


def release_identity(system, name):
    if system == MASTERS:
        match = re.fullmatch(r'(?:[A-Z]+\d+ )?Booster -(.+)-', name, re.I)
    elif system == FUSION:
        match = re.fullmatch(r'BOOSTER PACK -(.+)- \[FB\d{2}\]', name, re.I)
    else:
        return None
    return (system, normalized(match[1])) if match else None


def expansion_index(packaging):
    groups = defaultdict(set)
    for product in packaging.values():
        category, name = product.get('categoryName'), product.get('name', '')
        match = None
        if category == 'DBS Set':
            match = re.fullmatch(r'(.+): (?:Common|Uncommon|Rare|Super Rare|Special Rare|Secret Rare|Full) Set', name)
            system = MASTERS
        elif category == 'Dragon Ball Super Boosters':
            match = re.fullmatch(r'(.+) Booster \[Fusion World\]', name)
            system = FUSION
        expansion = product.get('idExpansion')
        if match and type(expansion) is int and expansion > 0:
            groups[(system, normalized(match[1]))].add(expansion)
    return {key:next(iter(ids)) for key,ids in groups.items() if len(ids)==1}


def matched_products(references, singles, packaging):
    expansions = expansion_index(packaging)
    products = defaultdict(list)
    for product in singles.values():
        if product.get('idCategory') != 1049 or product.get('categoryName') != 'Dragon Ball Super Singles':
            continue
        name = product.get('name', '')
        match = re.fullmatch(r'(.+) \((F[BS]\d{2}-\d{3})\) \[Fusion World\]', name)
        system = FUSION if match else MASTERS
        products[(system, product.get('idExpansion'), normalized(match[1] if match else name))].append(
            (match[2] if match else None, product))
    groups = defaultdict(list)
    numbers = defaultdict(list)
    for ref in references:
        if ref.get('provider') != 'Bandai Official' or ref.get('language') != 'English':
            continue
        system = ref.get('system_code')
        if system not in {MASTERS,FUSION}:
            continue
        groups[(system,ref['set_id'],normalized(ref['name']))].append(ref)
        numbers[(system,ref['set_id'],ref['card_number'])].append(ref)
    result = {}
    for (system,_,name),refs in groups.items():
        if len(refs) != 1:
            continue
        ref = refs[0]
        if len(numbers[(system,ref['set_id'],ref['card_number'])]) != 1:
            continue
        expansion = expansions.get(release_identity(system,ref['set_name']))
        candidates = products.get((system,expansion,name),[]) if expansion else []
        if len(candidates) != 1:
            continue
        number,product = candidates[0]
        if system == FUSION and number != ref['card_number']:
            continue
        result[(system,ref['provider_id'])] = product
    return result


def guide_quotes(ref, product, price, observed, conversion):
    if not price or price.get('idCategory') != product['idCategory']:
        return []
    quotes = []
    for field,finish in (('trend','Normal'),('trend-foil','Holofoil')):
        try:
            original = _minor(price.get(field))
            gbp = int((Decimal(original)*conversion.rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            if gbp <= 0:
                continue
        except (ValueError,TypeError,ArithmeticError):
            continue
        quotes.append({'source':SOURCE,'product_id':str(product['idProduct']),
            'expansion_id':product['idExpansion'],'source_field':field,'finish':finish,
            'original_currency':'EUR','original_minor':original,'price_gbp_minor':gbp,
            'observed_at':observed.isoformat(),'valuation_role':'MIXED_LANGUAGE_REFERENCE',
            'physical_language_confirmed':False,'condition_specific':False,
            'match_basis':'UNIQUE_RELEASE_AND_PRINTING_IN_BOTH_CHECKLISTS',
            'reference_printing_id':ref['provider_id'],'reference_rarity':ref.get('rarity'),
            'reference_identity':{k:ref[k] for k in ('name','set_id','card_number','set_name')},
            'fx_rate_to_gbp':str(conversion.rate),'fx_source':conversion.source,
            'fx_effective_at':conversion.effective_at.isoformat(),
            'fx_retrieved_at':conversion.retrieved_at.isoformat()})
    return quotes


async def refresh_dragon_ball_prices(pool, actor, fx):
    report = {'checked':0,'matched':0,'priced':0,'provider_failures':0}
    now = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=45,follow_redirects=False) as client:
            (singles,_),(packaging,_),(prices,observed) = await asyncio.gather(
                download(client,'productList/products_singles_13.json',rows_key='products',now=now),
                download(client,'productList/products_nonsingles_13.json',rows_key='products',now=now),
                download(client,'priceGuide/price_guide_13.json',rows_key='priceGuides',now=now))
        async with user_connection(pool,actor,str(uuid4())) as connection:
            references = [dict(r) for r in await connection.fetch('''select r.*,s.name as set_name
              from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
              where r.provider='Bandai Official' and r.language='English'
                and r.system_code in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD')
                and (s.release_date is null or s.release_date<=current_date)''')]
        matches = matched_products(references,singles,packaging)
        report.update(checked=len(references),matched=len(matches))
        if references and not matches:
            raise ValueError('No unambiguous Cardmarket Dragon Ball release matches')
        conversion = await fx.quote(base_currency='EUR',quote_currency='GBP',at=observed)
        values = []
        for ref in references:
            product = matches.get((ref['system_code'],ref['provider_id']))
            quotes = guide_quotes(ref,product,prices.get(str(product['idProduct'])),observed,conversion) if product else []
            amounts = [q['price_gbp_minor'] for q in quotes]
            values.append((ref['provider'],ref['system_code'],ref['language'],ref['provider_id'],quotes,
                min(amounts) if amounts else None,max(amounts) if amounts else None,observed if quotes else None,
                now,now+timedelta(days=1),ref['name'],ref['set_id'],ref['card_number'],ref['set_name']))
        for start in range(0,len(values),100):
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await connection.executemany(WRITE_SQL,values[start:start+100])
        report['priced'] = sum(v[5] is not None for v in values)
    except (httpx.HTTPError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        report.update(provider_failures=1,reason=type(exc).__name__)
    return report
