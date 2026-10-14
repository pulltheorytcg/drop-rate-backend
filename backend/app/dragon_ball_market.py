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

# Exact provider release-title discrepancies seen in the first-party export.
# This affects catalogue guide matching only, not physical valuation rules.
REFERENCE_RELEASE_ALIASES = {
    (MASTERS, '428024', 'Z07 Booster -BEYOND GENERATIONS-'): 'Beyond Generation',
    (MASTERS, '428025', 'Z08 Booster -LEGEND OF THE DRAGON BALLS-'): 'Legends of the Dragon Balls',
    (MASTERS, '428031', 'UB04 Booster -IMPACT BEYOND DIMENSIONS-'): 'Impact Beyond Dimension',
    (MASTERS, '428301', 'Series 1 Starter -THE AWAKING-'): 'The Awakening',
    (FUSION, '583011', 'BOOSTER PACK -BRIGHTNESS OF HOPE- [FB11]'): 'Brigtness Of Hope',
}


def reference_expansion(ref, expansions):
    identity = release_identity(ref['system_code'], ref['set_name'])
    ids = {expansions[identity]} if identity in expansions else set()
    alias = REFERENCE_RELEASE_ALIASES.get((ref['system_code'], ref['set_id'], ref['set_name']))
    if alias:
        alias_key = (ref['system_code'], normalized(alias))
        if alias_key in expansions:
            ids.add(expansions[alias_key])
    return next(iter(ids)) if len(ids) == 1 and None not in ids else None



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


def expansion_index(packaging, *, include_ambiguous=False):
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
    return {key:next(iter(ids)) if len(ids)==1 else None
            for key,ids in groups.items() if len(ids)==1 or include_ambiguous}


def matched_products(references, singles, packaging):
    expansions = expansion_index(packaging, include_ambiguous=True)
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
        expansion = reference_expansion(ref, expansions)
        candidates = products.get((system,expansion,name),[]) if expansion else []
        if len(candidates) != 1:
            continue
        number,product = candidates[0]
        if system == FUSION and number != ref['card_number']:
            continue
        result[(system,ref['provider_id'])] = product
    return result


def numbered_fusion_matches(references, singles, packaging):
    """Match repeated character names only when both sources give exact numbers.

    All official printings and all market products with a number participate
    in collision detection, including unpriced variants and conflicting names.
    Masters has no comparable number field in its ordinary export.
    """
    expansions = expansion_index(packaging, include_ambiguous=True)
    refs_by_number = defaultdict(list)
    products_by_number = defaultdict(list)
    for ref in references:
        if (ref.get('provider'), ref.get('system_code'), ref.get('language')) == (
                'Bandai Official', FUSION, 'English'):
            refs_by_number[(ref['set_id'], ref['card_number'])].append(ref)
    for product in singles.values():
        if (product.get('idCategory'), product.get('categoryName')) != (
                1049, 'Dragon Ball Super Singles'):
            continue
        label = str(product.get('name') or '')
        numbers = re.findall(r'\b(?:FB|FS|SB|ST)\d{2}-\d{3}\b', label)
        for number in set(numbers):
            # Count extra suffixes too. They cannot silently disappear from
            # uniqueness checks merely because only the base row has a price.
            products_by_number[(product.get('idExpansion'), number)].append(product)
    result = {}
    for (set_id, number), refs in refs_by_number.items():
        if len(refs) != 1:
            continue
        ref = refs[0]
        if ref.get('provider_id') != set_id + ':' + str(number):
            continue
        expansion = reference_expansion(ref, expansions)
        candidates = products_by_number.get((expansion, number), []) if expansion else []
        if len(candidates) != 1:
            continue
        product = candidates[0]
        match = re.fullmatch(r'(.+) \(((?:FB|FS|SB|ST)\d{2}-\d{3})\) \[Fusion World\]',
                             product.get('name', ''))
        if match and match[2] == number and normalized(match[1]) == normalized(ref['name']):
            result[(FUSION, ref['provider_id'])] = product
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
            'match_basis':('EXACT_RELEASE_ALIAS_AND_UNIQUE_PRINTING'
                if (ref['system_code'],ref['set_id'],ref['set_name']) in REFERENCE_RELEASE_ALIASES
                else 'UNIQUE_RELEASE_AND_PRINTING_IN_BOTH_CHECKLISTS'),
            'reference_printing_id':ref['provider_id'],'reference_rarity':ref.get('rarity'),
            'reference_identity':{k:ref[k] for k in ('name','set_id','card_number','set_name')},
            'fx_rate_to_gbp':str(conversion.rate),'fx_source':conversion.source,
            'fx_effective_at':conversion.effective_at.isoformat(),
            'fx_retrieved_at':conversion.retrieved_at.isoformat()})
    if (ref['system_code'],ref['set_id'],ref['set_name']) in REFERENCE_RELEASE_ALIASES:
        for quote in quotes:
            quote['physical_valuation_eligible'] = False
    return quotes


async def refresh_dragon_ball_prices(pool, actor, fx, *, cardtrader_client=None):
    report = {'checked':0,'matched':0,'priced':0,'provider_failures':0}
    now = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=45,follow_redirects=False) as client:
            (singles,_),(packaging,_),(prices,observed) = await asyncio.gather(
                download(client,'productList/products_singles_13.json',rows_key='products',now=now),
                download(client,'productList/products_nonsingles_13.json',rows_key='products',now=now),
                download(client,'priceGuide/price_guide_13.json',rows_key='priceGuides',now=now))
        async with user_connection(pool,actor,str(uuid4())) as connection:
            references = [dict(r) for r in await connection.fetch('''select r.*,s.name as set_name,
                p.quotes->0->>'match_basis' as existing_match_basis
              from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
              left join tcg.reference_market_prices p using(provider,system_code,language,provider_id)
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
            EXPANSION_RELEASES, EXPANSION_BASIS,
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
        numbered_matches = numbered_fusion_matches(references, singles, packaging)
        numbered_conflicts = {key for key, product in numbered_matches.items()
                              if key in matches and matches[key]['idProduct'] != product['idProduct']}
        for key in numbered_conflicts:
            matches.pop(key, None)
            numbered_matches.pop(key, None)
        numbered_recoveries = {key: product for key, product in numbered_matches.items() if key not in matches}
        matches.update(numbered_recoveries)
        from .dragon_ball_leader_market import paired_leader_matches, MATCH_BASIS as LEADER_BASIS
        leader_matches = paired_leader_matches(references, singles, packaging)
        leader_conflicts = {key for key, match in leader_matches.items()
                            if key in matches and matches[key]['idProduct'] != match['product']['idProduct']}
        # Reject both faces if any adapter disagrees about their common product.
        conflicting_pairs = {leader_matches[key]['pair'] for key in leader_conflicts}
        leader_products = {match['product']['idProduct']: match for match in leader_matches.values()}
        for key, product in list(matches.items()):
            leader = leader_products.get(product['idProduct'])
            if leader and key not in {(MASTERS, face) for face in leader['reference_face_ids']}:
                conflicting_pairs.add(leader['pair'])
                matches.pop(key, None)
        for key, match in list(leader_matches.items()):
            if match['pair'] in conflicting_pairs:
                matches.pop(key, None)
                leader_matches.pop(key)
        leader_recoveries = {key: match for key, match in leader_matches.items() if key not in matches}
        matches.update({key: match['product'] for key, match in leader_recoveries.items()})
        if leader_matches or conflicting_pairs:
            report.update(masters_leader_faces_matched=len(leader_recoveries),
                          masters_leader_pairs_conflicting=len(conflicting_pairs))
        if any(r['system_code']==FUSION and r['language']=='English' for r in references):
            report.update(fusion_numbered_recovered=len(numbered_recoveries),
                          fusion_numbered_conflicts=len(numbered_conflicts))
        from .masters_cardtrader_market import cardtrader_matches, MATCH_BASIS as BRIDGE_BASIS
        bridged, failed_bridge_sets = {}, {r['set_id'] for r in references}
        if cardtrader_client is not None:
            candidates, bridge_report, failed_bridge_sets = await cardtrader_matches(
                cardtrader_client, references, singles, packaging, matches)
            # A later adapter cannot revive an identity already rejected by
            # two earlier sources. Also reject reused IDs across printings.
            rejected = conflicts | numbered_conflicts | leader_conflicts
            bridge_conflicts = {key for key, match in candidates.items() if key in matches
                                and matches[key]['idProduct'] != match['product']['idProduct']}
            claims = defaultdict(set)
            for key, product in matches.items():
                claims[product['idProduct']].add(key)
            for key, match in candidates.items():
                allowed = {(MASTERS, face) for face in match['proof'].get('reference_face_ids', [])} or {key}
                other_claims = claims[match['product']['idProduct']] - allowed
                if other_claims:
                    bridge_conflicts.update({key, *other_claims})
            rejected_printings = {match['printing'] for key, match in candidates.items()
                                  if key in rejected | bridge_conflicts}
            bridge_conflicts.update(key for key, match in candidates.items()
                                    if match['printing'] in rejected_printings)
            for key in bridge_conflicts:
                matches.pop(key, None)
            bridged = {key: match for key, match in candidates.items()
                       if key not in rejected | bridge_conflicts and key not in matches}
            matches.update({key: match['product'] for key, match in bridged.items()})
            bridge_report.update(recovered=len(bridged), cross_source_conflicts=len(bridge_conflicts))
            report['cardtrader_masters_bridge'] = bridge_report
            report['provider_failures'] += bridge_report['provider_failures']
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
                if (ref['set_id'] in EXPANSION_RELEASES and
                        (ref['system_code'], ref['provider_id']) in supplemental_matches):
                    for quote in quotes:
                        quote.update(match_basis=EXPANSION_BASIS, physical_valuation_eligible=False)
                if (ref['system_code'], ref['provider_id']) in numbered_recoveries:
                    for quote in quotes:
                        quote.update(match_basis='EXACT_FUSION_RELEASE_NAME_NUMBER_REFERENCE',
                                     physical_valuation_eligible=False)
                leader = leader_recoveries.get((ref['system_code'], ref['provider_id']))
                if leader:
                    for quote in quotes:
                        quote.update(match_basis=LEADER_BASIS, physical_valuation_eligible=False,
                                     reference_face_ids=leader['reference_face_ids'],
                                     reference_face=leader['reference_face'])
                bridge = bridged.get((ref['system_code'], ref['provider_id']))
                if bridge:
                    for quote in quotes:
                        quote.update(bridge['proof'])
            if (not quotes and ref['set_id'] in failed_bridge_sets and
                    ref.get('existing_match_basis') == BRIDGE_BASIS):
                # Provider failure is not negative evidence. Preserve the
                # original quote and dates; never turn stale data into fresh.
                continue
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
        if 'cardtrader_masters_bridge' in report:
            report['cardtrader_masters_bridge']['priced'] = sum(
                v[5] is not None and (v[1], v[3]) in bridged for v in values)
            report['cardtrader_masters_bridge']['leader_faces_priced'] = sum(
                v[5] is not None and 'reference_face_ids' in
                bridged.get((v[1], v[3]), {}).get('proof', {}) for v in values)
        if leader_recoveries:
            report['masters_leader_faces_priced'] = sum(
                v[5] is not None and (v[1], v[3]) in leader_recoveries for v in values
            )
        if 'fusion_numbered_recovered' in report:
            report['fusion_numbered_priced'] = sum(
                v[5] is not None and (v[1], v[3]) in numbered_recoveries for v in values
            )
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
                    and (v[1],v[3]) in supplemental_matches
                    for v in values
                )
            report['masters_supplemental_priced']=sum(
                data['priced'] for data in report['masters_supplemental_by_release'].values()
            )
            report['masters_expansion_priced'] = sum(
                report['masters_supplemental_by_release'][set_id]['priced']
                for set_id in EXPANSION_RELEASES
            )
        if jp_references:
            report['english_priced'] = report['priced'] - report.get('japanese_fb01_priced',0) - report.get('japanese_multiset_priced',0)
    except (httpx.HTTPError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        report.update(provider_failures=1,reason=type(exc).__name__)
    return report
