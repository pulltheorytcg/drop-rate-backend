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
from .market_guide_fields import choose_bulk_price_field
from .sealed_market import download

SOURCE = 'CARDMARKET_CATALOGUE'
# Provider-published EX-era titles. Scope aliases to both ID and exact title;
# do not strip arbitrary prefixes from modern/promotional/regional releases.
EX_RELEASE_TITLES = {
    'ex1': 'Ruby & Sapphire', 'ex2': 'Sandstorm', 'ex3': 'Dragon',
    'ex4': 'Team Magma vs Team Aqua', 'ex5': 'Hidden Legends',
    'ex6': 'FireRed & LeafGreen', 'ex7': 'Team Rocket Returns',
    'ex8': 'Deoxys', 'ex9': 'Emerald', 'ex10': 'Unseen Forces',
    'ex11': 'Delta Species', 'ex12': 'Legend Maker', 'ex13': 'Holon Phantoms',
    'ex14': 'Crystal Guardians', 'ex15': 'Dragon Frontiers', 'ex16': 'Power Keepers',
}


def release_titles(ref):
    titles = {ref['set_name']}
    if EX_RELEASE_TITLES.get(ref['set_id']) == ref['set_name']:
        titles.add('EX ' + ref['set_name'])
    if ref['set_id'] == 'xy0' and ref['set_name'] == 'Kalos Starter Set':
        titles.add('XY Kalos Starter Set')
    return titles

READ_SQL = '''select r.*,s.name as set_name,s.declared_card_count,
 (p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days') as current_detail_priced,
 b.quotes->0->>'match_basis' as existing_match_basis
 from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
 left join tcg.reference_catalogue_prices b using(provider,system_code,language,provider_id)
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


def product_card_name(product):
    # Attack text and printed numeric level are card metadata. Lv.X is a
    # distinct card type and must survive, along with edition/version suffixes.
    # Cardmarket spells Nidoran's printed gender as [F]/[M], before attack text.
    # Convert that identity marker before removing the final metadata bracket.
    name = re.sub(r'^Nidoran \[([FM])\](?= |$)',
                  lambda m: 'Nidoran ' + ('♀' if m[1] == 'F' else '♂'),
                  product.get('name', ''))
    name = re.sub(r' \[[^\[\]]+\]$', '', name)
    # Cardmarket expands this printed symbol as "δ Delta Species". Retain δ:
    # removing the symbol would confuse ordinary and Delta Species printings.
    name = re.sub(r'δ Delta Species(?= |$)', 'δ', name)
    return re.sub(r' Lv\.[1-9]\d{0,2}$', '', name)


def matched_products(references, singles, packaging):
    expansions = defaultdict(set)
    for product in packaging.values():
        name = product.get('name', '')
        expansion = product.get('idExpansion')
        if (product.get('idCategory') == 54 and product.get('categoryName') == 'Pokémon Theme Decks'
                and name in {'XY Kalos Starter Set: Chespin Theme Deck',
                             'XY Kalos Starter Set: Fennekin Theme Deck',
                             'XY Kalos Starter Set: Froakie Theme Deck'}
                and type(expansion) is int and expansion > 0):
            expansions[normalized('XY Kalos Starter Set')].add(expansion)
        if (product.get('idCategory') == 52 and product.get('categoryName') == 'Pokémon Booster'
                and name.endswith(' Booster') and type(expansion) is int and expansion > 0):
            expansions[normalized(name[:-8])].add(expansion)
    products = defaultdict(list)
    for product in singles.values():
        if product.get('idCategory') == 51 and product.get('categoryName') == 'Pokémon Single':
            name = product_card_name(product)
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
        expansion_ids = set().union(*(expansions.get(normalized(title), set())
                                      for title in release_titles(ref)))
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
            if field == 'trend':
                selected = choose_bulk_price_field(price, field)
                if selected is None:
                    continue
                original, source_field = selected
            else:
                original, source_field = _minor(price.get(field)), field
            gbp = int((Decimal(original)*conversion.rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            if gbp <= 0:
                continue
        except (ValueError,TypeError,ArithmeticError):
            continue
        quotes.append({'source':SOURCE,'product_id':str(product['idProduct']),
            'expansion_id':product['idExpansion'],'source_field':source_field,
            'original_currency':'EUR','original_minor':original,'price_gbp_minor':gbp,
            'observed_at':observed.isoformat(),'finish':label,
            'valuation_role':'MIXED_LANGUAGE_REFERENCE','physical_language_confirmed':False,
            'condition_specific':False,'physical_valuation_eligible':False,
            'match_basis':'UNIQUE_NAME_IN_COMPLETE_RELEASE_CHECKLISTS',
            'collector_number_supplied_by_marketplace':False,
            'reference_identity':{key:ref[key] for key in ('name','set_id','card_number','set_name')},
            'fx_rate_to_gbp':str(conversion.rate),'fx_source':conversion.source,
            'fx_effective_at':conversion.effective_at.isoformat(),'fx_retrieved_at':conversion.retrieved_at.isoformat(),
            **({'guide_window_days':30,'physical_valuation_eligible':False}
               if source_field=='avg30' else {})})
    return quotes




def validate_hidden_fates_scope(references):
    """The bounded operator path accepts the complete physical English subset."""
    expected = {f'sma-SV{number}' for number in range(1, 95)}
    if len(references) != 94 or {r.get('provider_id') for r in references} != expected:
        raise ValueError('Hidden Fates Shiny Vault requires exactly 94 distinct cards')
    for ref in references:
        suffix = ref['provider_id'][4:]
        if ((ref.get('provider'), ref.get('system_code'), ref.get('language'),
             ref.get('set_id'), ref.get('set_name'), ref.get('declared_card_count')) !=
                ('TCGdex', 'POKEMON_TCG', 'English', 'sma', 'Hidden Fates Shiny Vault', 94)
                or ref.get('card_number') != suffix + '/94'):
            raise ValueError('Hidden Fates Shiny Vault identity changed')


def validate_generations_scope(references):
    """Require the complete observed117-card g1 checklist before partitioning."""
    suffixes={str(n) for n in range(1,84)} | {"28a","73a"} | {f"RC{n}" for n in range(1,33)}
    expected={"g1-"+suffix for suffix in suffixes}
    if len(references)!=117 or {r.get("provider_id") for r in references}!=expected:
        raise ValueError("Generations requires exactly117 distinct cards")
    for ref in references:
        suffix=ref["provider_id"][3:]
        if ((ref.get("provider"),ref.get("system_code"),ref.get("language"),
             ref.get("set_id"),ref.get("set_name"),ref.get("declared_card_count")) !=
            ("TCGdex","POKEMON_TCG","English","g1","Generations",117)
            or ref.get("card_number")!=suffix+"/83"):
            raise ValueError("Generations identity changed")


def bounded_references(references, set_id):
    if set_id=="sma":
        validate_hidden_fates_scope(references)
        return references
    if set_id=="g1":
        validate_generations_scope(references)
        return [r for r in references if r["provider_id"].startswith("g1-RC")]
    raise ValueError("Unsupported bounded Pokemon pricing scope")


OUTSIDE_SCOPE_CLAIMS_SQL = """select distinct q->>'product_id' as product_id
 from tcg.reference_catalogue_prices p
 cross join lateral jsonb_array_elements(p.quotes) q
 where p.provider='TCGdex' and p.system_code='POKEMON_TCG' and p.language='English'
 and p.provider_id<>all($1::text[]) and coalesce(p.market_value_minor,0)>0
 and q->>'source'='CARDMARKET_CATALOGUE' and q->>'product_id'=any($2::text[])"""


async def outside_scope_claims(connection, references, matches):
    if not matches:
        return set()
    rows = await connection.fetch(OUTSIDE_SCOPE_CLAIMS_SQL,
        [ref['provider_id'] for ref in references],
        sorted({str(match['idProduct']) for match in matches.values()}))
    return {row['product_id'] for row in rows}

async def refresh_pokemon_catalogue_prices(pool, actor, fx, *, cardtrader_client=None,
                                          reference_set_id=None, dry_run=False):
    # The scheduled default is unchanged. The bounded operator path is
    # deliberately restricted to the one reviewed complete subset.
    if reference_set_id not in (None, 'sma', 'g1') or type(dry_run) is not bool:
        raise ValueError('Unsupported bounded Pokemon pricing scope')

    report = {'checked':0,'matched':0,'priced':0,'provider_failures':0,'inventory_rows_read':0}
    now = datetime.now(timezone.utc)
    scoped = reference_set_id is not None
    if scoped:
        report.update(reference_set_id=reference_set_id, dry_run=dry_run, writes_attempted=0,
                      written=0, outside_scope_conflicts=0, preview=[])
    try:
        references = None
        if scoped:
            async with user_connection(pool,actor,str(uuid4())) as connection:
                references = [dict(row) for row in await connection.fetch(
                    READ_SQL + " and r.set_id=$1", reference_set_id)]
            bounded_references(references,reference_set_id)
            if cardtrader_client is None:
                raise ValueError('Bounded pricing requires its explicit CardTrader identity bridge')
        async with httpx.AsyncClient(timeout=45,follow_redirects=False) as client:
            exports = await asyncio.gather(
                download(client,'productList/products_singles_6.json',rows_key='products',now=now),
                download(client,'productList/products_nonsingles_6.json',rows_key='products',now=now),
                download(client,'priceGuide/price_guide_6.json',rows_key='priceGuides',now=now))
        (singles,_),(packaging,_),(prices,observed) = exports
        if references is None:
            async with user_connection(pool,actor,str(uuid4())) as connection:
                references = [dict(row) for row in await connection.fetch(READ_SQL)]
        matches = matched_products(references,singles,packaging)
        bridged, failed_bridge_sets = {}, set()
        from .pokemon_cardtrader_market import MATCH_BASIS, cardtrader_matches
        if cardtrader_client is not None:
            bridged, bridge_report, failed_bridge_sets = await cardtrader_matches(
                cardtrader_client, references, singles, {} if scoped else matches)
            conflicts = {key for key,value in bridged.items() if key in matches and
                         matches[key]['idProduct']!=value['product']['idProduct']}
            for key in conflicts:
                matches.pop(key,None)
                bridged.pop(key,None)
            bridge_report['cross_source_conflicts'] = len(conflicts)
            report['cardtrader_bridge'] = bridge_report
            report['provider_failures'] += bridge_report['provider_failures']
            for key,value in bridged.items():
                matches.setdefault(key,value['product'])
        else:
            failed_bridge_sets = {r['set_id'] for r in references}
        if scoped:
            report['source_checked']=len(references)
            references=bounded_references(references,reference_set_id)
            # This targeted fill requires the reviewed explicit-number bridge.
            scope_ids={r['provider_id'] for r in references}
            matches = {key: product for key, product in matches.items() if key in bridged and key in scope_ids}
            if report['provider_failures']:
                raise ValueError('Bounded pricing source did not complete')
            async with user_connection(pool,actor,str(uuid4())) as connection:
                conflicts = await outside_scope_claims(connection, references, matches)
            excluded = {key for key, product in matches.items()
                        if str(product['idProduct']) in conflicts}
            report['outside_scope_conflicts'] = len(excluded)
            for key in excluded:
                matches.pop(key, None)
                bridged.pop(key, None)
        report.update(checked=len(references),matched=len(matches))
        if references and not matches:
            raise ValueError('No unambiguous Cardmarket release matches')
        conversion = await fx.quote(base_currency='EUR',quote_currency='GBP',at=observed)
        values = []
        for ref in references:
            if ref["set_id"]=="g1" and "g1" in failed_bridge_sets:
                # An incomplete partition cannot invalidate an existing exact
                # guide or replace it with a weaker name-only bulk match.
                continue
            product = matches.get(ref['provider_id'])
            price = prices.get(str(product['idProduct'])) if product else None
            quotes = quotes_for(ref,product,price,observed,conversion)
            if ref['provider_id'] in bridged:
                for quote in quotes:
                    quote.update(bridged[ref['provider_id']]['proof'])
            if (not quotes and ref['set_id'] in failed_bridge_sets and
                    ref.get('existing_match_basis')==MATCH_BASIS):
                # A failed identity source is not proof of a missing quote.
                # Leave its original price, dates and expiry untouched.
                continue
            if scoped and not quotes:
                # A targeted fill never clears an existing price or evidence.
                continue
            amounts = [q['price_gbp_minor'] for q in quotes]
            values.append((ref['provider'],ref['system_code'],ref['language'],ref['provider_id'],
                quotes,min(amounts) if amounts else None,max(amounts) if amounts else None,
                observed if quotes else None,now,now+timedelta(days=1),
                ref['name'],ref['set_id'],ref['card_number'],ref['set_name']))
        if scoped:
            report['preview'] = [
                {'provider_id': row[3], 'name': row[10], 'card_number': row[12],
                 'market_value_minor': row[5], 'market_value_high_minor': row[6],
                 'quotes': row[4]} for row in values]
            if not dry_run and values:
                from .access_control import require_platform_admin
                from .database_capacity import check_database_capacity
                async with user_connection(pool,actor,str(uuid4())) as connection:
                    await require_platform_admin(connection)
                    capacity = await check_database_capacity(connection)
                    if not capacity.refresh_allowed:
                        raise ValueError('Database capacity blocks bounded pricing writes')
                    current = [dict(row) for row in await connection.fetch(
                        READ_SQL + " and r.set_id=$1", reference_set_id)]
                    current=bounded_references(current,reference_set_id)
                    # Recheck all outside claims inside the same transaction as
                    # persistence; the CLI holds the scheduled maintenance lock.
                    if await outside_scope_claims(connection, current, matches):
                        raise ValueError('Outside-scope pricing claim changed before write')
                    await connection.executemany(WRITE_SQL, values)
                    report['writes_attempted'] = len(values)
                    written = await connection.fetch("""select provider_id from tcg.reference_catalogue_prices
                        where provider='TCGdex' and system_code='POKEMON_TCG' and language='English'
                        and provider_id=any($1::text[]) and checked_at=$2
                        and market_value_minor>0""", [row[3] for row in values], now)
                    report['written'] = len(written)
        elif not dry_run:
            for start in range(0,len(values),100):
                async with user_connection(pool,actor,str(uuid4())) as connection:
                    await connection.executemany(WRITE_SQL,values[start:start+100])
        report['priced'] = sum(row[5] is not None for row in values)
        if 'cardtrader_bridge' in report:
            report['cardtrader_bridge']['priced'] = sum(
                row[5] is not None and row[3] in bridged for row in values)
    except (httpx.HTTPError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        report.update(provider_failures=1,reason=type(exc).__name__)
    return report


