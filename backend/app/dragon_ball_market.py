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


def release_identity(system, name, *, include_starters=True, include_supplemental=True):
    if system == MASTERS:
        match = re.fullmatch(r'(?:(?:Series \d+|[A-Z]+\d+) )?Booster -(.+)-', name, re.I)
        if not match and include_starters:
            match = re.fullmatch(r'(?:Series \d+|[A-Z]+\d+) Starter(?: \d+)? -(.+)-', name, re.I)
    elif system == FUSION:
        match = re.fullmatch(r'BOOSTER PACK -(.+)- \[FB\d{2}\]', name, re.I)
        if not match and include_starters:
            match = re.fullmatch(r'STARTER DECK -(.+)- \[FS\d{2}\]', name, re.I)
        if not match and include_supplemental:
            # The full release label and its printed code must agree. These
            # reprint checklists remain reference-only, like starter decks.
            match = re.fullmatch(r'(MANGA BOOSTER (\d{2})) \[SB\2\]', name, re.I)
            if not match:
                match = re.fullmatch(r'(STORY BOOSTER (\d{2})) \[ST\2\]', name, re.I)
    else:
        return None
    return (system, normalized(next(group for group in match.groups() if group is not None))) if match else None


def expansion_index(packaging):
    groups = defaultdict(set)
    for product in packaging.values():
        category, name = product.get('categoryName'), product.get('name', '')
        match = None
        if category == 'DBS Set':
            match = re.fullmatch(r'(.+): (?:Common|Uncommon|Rare|Super Rare|Special Rare|Secret Rare|Full) Set', name)
            system = MASTERS
        elif category == 'Dragon Ball Super Boosters' and product.get('idCategory') == 1050:
            match = re.fullmatch(r'(.+) Booster( \[Fusion World\])?', name)
            system = FUSION if match and match[2] else MASTERS
        elif category == 'Dragon Ball Super Booster Boxes' and product.get('idCategory') == 1052:
            match = re.fullmatch(r'(.+) Booster Box( \[Fusion World\])?', name)
            system = FUSION if match and match[2] else MASTERS
        elif product.get('idCategory') == 1053 and category == 'Dragon Ball Super Starter Decks':
            match = re.fullmatch(r'Starter Deck: (.+?)( \[Fusion World\])?', name)
            system = FUSION if match and match[2] else MASTERS
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
        match = re.fullmatch(r'(.+) \(((?:FB|FS|SB|ST)\d{2}-\d{3})\) \[Fusion World\]', name)
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
              where r.provider='Bandai Official'
                and (r.language='English' or
                     (r.language='Japanese' and r.system_code='DRAGON_BALL_SUPER_FUSION_WORLD'
                      and r.set_id between '584001' and '584011'))
                and r.system_code in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD')
                and (s.release_date is null or s.release_date<=current_date)''')]
        from .dragon_ball_japanese_fb01_market import (
            matched_japanese_fb01, japanese_fb01_quote,
        )
        from .dragon_ball_japanese_multi_market import (
            RELEASES, match_regional_boosters, regional_booster_quote,
            regional_coverage_report,
        )
        from .dragon_ball_masters_missing_market import (
            RELEASES as MASTERS_HIGH_GAP_RELEASES,
            exact_masters_supplemental_matches, supplemental_coverage,
        )
        matches = matched_products(references,singles,packaging)
        supplemental_matches = exact_masters_supplemental_matches(
            references,singles,packaging
        )
        # A conflicting source identity cannot be resolved by whichever
        # adapter has a populated price; fail this printing closed.
        conflicts={
            key for key,product in supplemental_matches.items()
            if key in matches and matches[key]['idProduct']!=product['idProduct']
        }
        for key in conflicts:
            matches.pop(key,None)
            supplemental_matches.pop(key,None)
        for key,product in supplemental_matches.items():
            matches.setdefault(key,product)
        jp_matches = matched_japanese_fb01(references,singles,packaging)
        multi_matches = match_regional_boosters(references,singles,packaging)
        jp_references = [ref for ref in references if ref['language']=='Japanese']
        jp_fb01_refs = [ref for ref in jp_references if ref['set_id']=='584001']
        jp_multiset_refs = [ref for ref in jp_references if ref['set_id']!='584001']
        report.update(checked=len(references),matched=len(matches)+len(jp_matches)+len(multi_matches))
        masters_refs=[
            r for r in references if r['language']=='English'
            and r['system_code']==MASTERS and r['set_id'] in MASTERS_HIGH_GAP_RELEASES
        ]
        if masters_refs:
            report['masters_supplemental_checked']=len(masters_refs)
            report['masters_supplemental_matched']=len(supplemental_matches)
            report['masters_supplemental_conflicts']=len(conflicts)
            report['masters_supplemental_by_release']=supplemental_coverage(
                masters_refs,supplemental_matches,prices
            )
        if jp_fb01_refs:
            report.update(japanese_fb01_checked=len(jp_fb01_refs),
                          japanese_fb01_matched=len(jp_matches))
        if jp_multiset_refs:
            report.update(japanese_multiset_checked=len(jp_multiset_refs),
                          japanese_multiset_base_candidates=sum(
                              r.get('provider_id')==r.get('set_id')+':'+str(r.get('card_number'))
                              for r in jp_multiset_refs),
                          japanese_multiset_matched=len(multi_matches),
                          japanese_multiset_by_release=regional_coverage_report(
                              jp_multiset_refs,multi_matches,prices))
        if references and not matches and not jp_matches and not multi_matches:
            raise ValueError('No unambiguous Cardmarket Dragon Ball release matches')
        conversion = await fx.quote(base_currency='EUR',quote_currency='GBP',at=observed)
        values = []
        for ref in references:
            jp_match = jp_matches.get(ref['provider_id']) if ref['language']=='Japanese' else None
            multi_match = multi_matches.get(ref['provider_id']) if ref['language']=='Japanese' else None
            product = (
                jp_match['product'] if jp_match else
                multi_match['product'] if multi_match else
                matches.get((ref['system_code'],ref['provider_id']))
            )
            if jp_match:
                quote = japanese_fb01_quote(
                    ref,jp_match,prices.get(str(product['idProduct'])),observed,conversion)
                quotes = [quote] if quote else []
            elif multi_match:
                quote = regional_booster_quote(
                    ref,multi_match,prices.get(str(product['idProduct'])),observed,conversion)
                quotes = [quote] if quote else []
            else:
                quotes = guide_quotes(
                    ref,product,prices.get(str(product['idProduct'])),observed,conversion
                ) if product else []
            # Never replace an unpriced Japanese reference with a null value
            # when this narrowly scoped regional expansion has no match.
            if ref['language']=='Japanese' and not quotes:
                continue
            amounts = [q['price_gbp_minor'] for q in quotes]
            values.append((ref['provider'],ref['system_code'],ref['language'],ref['provider_id'],quotes,
                min(amounts) if amounts else None,max(amounts) if amounts else None,observed if quotes else None,
                now,now+timedelta(days=1),ref['name'],ref['set_id'],ref['card_number'],ref['set_name']))
        for start in range(0,len(values),100):
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await connection.executemany(WRITE_SQL,values[start:start+100])
        report['priced'] = sum(v[5] is not None for v in values)
        if jp_fb01_refs:
            report['japanese_fb01_priced'] = sum(
                v[5] is not None and v[2]=='Japanese' and v[3].startswith('584001:')
                for v in values
            )
        if jp_multiset_refs:
            report['japanese_multiset_priced'] = sum(
                v[5] is not None and v[2]=='Japanese' and v[3][:6] in
                {r[1] for r in RELEASES.values()}
                for v in values
            )
            for code, (en_set, jp_set, *_other) in RELEASES.items():
                report['japanese_multiset_by_release'][code]['priced'] = sum(
                    v[5] is not None and v[2]=='Japanese' and v[3].startswith(jp_set+':')
                    for v in values
                )
        if masters_refs:
            for set_id in MASTERS_HIGH_GAP_RELEASES:
                report['masters_supplemental_by_release'][set_id]['priced']=sum(
                    v[5] is not None and v[2]=='English' and
                    v[1]==MASTERS and v[3].startswith(set_id+':')
                    for v in values
                )
            report['masters_supplemental_priced']=sum(
                data['priced'] for data in report['masters_supplemental_by_release'].values()
            )
        if jp_references:
            report['english_priced'] = report['priced'] - report.get('japanese_fb01_priced',0) - report.get('japanese_multiset_priced',0)
    except (httpx.HTTPError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        report.update(provider_failures=1,reason=type(exc).__name__)
    return report
