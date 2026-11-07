"""First-party Cardmarket guides for unambiguous English One Piece printings.

Both checklists must contain exactly one printing for the release/name/number.
Alternate arts, regional expansions and duplicate products are never resolved
by price, array order or a guessed V1/V2 suffix. No inventory writes occur here.
"""
from __future__ import annotations

import asyncio
import html
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

SOURCE = 'CARDMARKET_BULK_SINGLES'
OFFICIAL_BASE_PARALLEL_BASIS = 'OFFICIAL_CHECKLIST_BASE_WITH_SEPARATE_PARALLELS'
# The complete official label (including ST code) is required. Never drop
# colours, EX, region or edition text from arbitrary release names.
STARTER_RELEASE_ALIASES = {
    'ULTRA DECK -The Three Captains- [ST-10]': 'The Three Captains',
    'STARTER DECK -Zoro and Sanji- [ST-12]': 'Zoro & Sanji',
    'ULTRA DECK -The Three Brothers- [ST-13]': 'The Three Brothers',
    'STARTER DECK -Red Edward.Newgate- [ST-15]': 'Edward.Newgate',
    'STARTER DECK -Blue Donquixote Doflamingo- [ST-17]': 'Donquixote Doflamingo',
    'STARTER DECK -Black Smoker- [ST-19]': 'Smoker',
    'STARTER DECK -Yellow Charlotte Katakuri- [ST-20]': 'Charlotte Katakuri',
    'STARTER DECK EX -GEAR5- [ST-21]': 'EX Gear 5',
    'STARTER DECK -Ace & Newgate- [ST-22]': 'EX Ace & Newgate',
}
STARTER_ALIAS_BASIS = 'EXACT_STARTER_RELEASE_ALIAS_UNIQUE_PRINTING'
WRITE_SQL = '''insert into tcg.reference_market_prices
 (provider,system_code,language,provider_id,quotes,market_value_minor,market_value_high_minor,
  pricing_updated_at,checked_at,expires_at,refresh_revision)
 select $1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,2
 from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
 where r.provider=$1 and r.system_code=$2 and r.language=$3 and r.provider_id=$4
   and r.name=$11 and r.set_id=$12 and r.card_number=$13 and s.name=$14
   and (coalesce($5::jsonb->0->>'match_basis','')<>'CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID'
        or r.rarity is not distinct from $5::jsonb->0->>'reference_rarity')
 on conflict(provider,system_code,language,provider_id) do update
 set quotes=excluded.quotes,market_value_minor=excluded.market_value_minor,
 market_value_high_minor=excluded.market_value_high_minor,pricing_updated_at=excluded.pricing_updated_at,
 checked_at=excluded.checked_at,expires_at=excluded.expires_at,refresh_revision=excluded.refresh_revision
 where tcg.reference_market_prices.checked_at<=excluded.checked_at'''


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value)).casefold())


def release_identity(name, *, include_starters=True):
    if name in STARTER_RELEASE_ALIASES:
        return (normalized(STARTER_RELEASE_ALIASES[name]), 'STARTER') if include_starters else None
    starter = re.fullmatch(r'STARTER DECK -(.+)- \[ST-?(\d{2})\]', name, re.I)
    if starter and include_starters:
        return normalized(starter[1]), 'STARTER'
    match = re.fullmatch(r'(?:(?:BOOSTER PACK|EXTRA BOOSTER|PREMIUM BOOSTER)\s*)?-?(.+?)-?\s*\[(OP|EB|PRB)-?(\d{2})(?:-?EB\d{2})?\]', name, re.I)
    if not match:
        return None
    title = normalized(match[1])
    # Published English title differs by this one preposition on Cardmarket.
    if title == '500yearsinthefuture':
        title = '500yearsintothefuture'
    # The official English EB-03 checklist says "ONE PIECE HEROINES
    # EDITION"; Cardmarket's English lot checklist says "Heroines Edition".
    # Require the printed EB03 set code as well: never merge similarly named
    # promos, another release or Asia-region printings by translated title.
    if match[2].upper() == 'EB' and match[3] == '03' and title == 'onepieceheroinesedition':
        title = 'heroinesedition'
    return title, match[2].upper()+match[3]


def expansion_index(products):
    result = defaultdict(set)
    # PRB releases have no Lots rows in the public export. Full English
    # booster/box names independently corroborate these exact named releases.
    premium_titles = {'The Best': ('onepiececardthebest', 'PRB01'),
                      'The Best Vol.2': ('onepiececardthebestvol2', 'PRB02')}
    for product in products.values():
        category = (product.get('idCategory'), product.get('categoryName'))
        suffix = {(1622, 'One Piece Booster'): ' Booster',
                  (1624, 'One Piece Booster Boxes'): ' Booster Box'}.get(category)
        name = str(product.get('name') or '')
        expansion = product.get('idExpansion')
        if suffix and name.endswith(suffix) and type(expansion) is int and expansion > 0:
            key = premium_titles.get(name[:-len(suffix)])
            if key:
                result[key].add(expansion)
        if product.get('idCategory') == 1625 and product.get('categoryName') == 'One Piece Preconstructed Decks':
            starter = re.fullmatch(r'Starter Deck: (.+)', product.get('name',''))
            expansion = product.get('idExpansion')
            if starter and type(expansion) is int and expansion > 0:
                result[(normalized(starter[1]),'STARTER')].add(expansion)
            ultra = {'Ultimate Deck: The Three Captains': 'The Three Captains',
                     'Ultra Deck: The Three Brothers': 'The Three Brothers'}.get(name)
            if ultra and type(expansion) is int and expansion > 0:
                result[(normalized(ultra),'STARTER')].add(expansion)
        # Cardmarket publishes the release name and ID on these set products.
        # A code alone can also refer to a regional release or tournament pack.
        if product.get('categoryName') != 'One Piece Lots':
            continue
        match = re.fullmatch(r'(?:Common|Uncommon|Rare|Super Rare|Full|Common / Uncommon / Rare) Set - (.+) \(((?:OP|EB|PRB)\d{2})\)', product.get('name', ''))
        expansion = product.get('idExpansion')
        if match and type(expansion) is int and expansion > 0:
            result[(normalized(match[1]), match[2])].add(expansion)
    return {key:next(iter(ids)) for key, ids in result.items() if len(ids) == 1}


def official_base_with_parallels(refs):
    """Resolve only a publisher-confirmed base; never assign its guide to parallels.

    Some Bandai checklists contain both ``OP01-001`` and ``OP01-001_p1``.
    They are distinct official printings, not a conflicting base identity.
    Require the official checklist to establish *every* printing in the group,
    and an exact original booster release before accepting the unsuffixed base.
    The resulting Cardmarket guide remains reference-only.
    """
    if len({r.get('provider_id') for r in refs}) < 2:
        return None
    originals = [r for r in refs if r.get('provider') == 'Bandai Official'
                 and r.get('provider_id') == r.get('card_number')
                 and (r.get('evidence') or {}).get('detail_level') == 'OFFICIAL_CHECKLIST'
                 and (r.get('evidence') or {}).get('printing_id') == r.get('provider_id')]
    if len(originals) != 1:
        return None
    base = originals[0]
    number = str(base['card_number'])
    if (not re.fullmatch(r'(?:OP|EB)\d{2}-\d{3}', number)
            or not release_identity(base.get('set_name') or '', include_starters=False)):
        return None
    official_ids = {r['provider_id'] for r in refs
        if r.get('provider') == 'Bandai Official'
        and (r.get('evidence') or {}).get('detail_level') == 'OFFICIAL_CHECKLIST'
        and (r.get('evidence') or {}).get('printing_id') == r.get('provider_id')}
    ids = {r.get('provider_id') for r in refs}
    if not ids <= official_ids:
        return None
    if any(not (printing == number or re.fullmatch(rf'{re.escape(number)}_p[1-9]\d*', str(printing or '')))
           for printing in ids):
        return None
    if any(r.get('set_id') != base['set_id']
           or r.get('card_number') != number
           or r.get('system_code') != 'ONE_PIECE_CARD_GAME'
           or r.get('language') != 'English'
           or normalized(r.get('set_name')) != normalized(base.get('set_name'))
           or normalized(html.unescape(r.get('name') or '')) != normalized(html.unescape(base.get('name') or ''))
           or normalized(r.get('rarity')) != normalized(base.get('rarity'))
           or normalized(r.get('finish')) != normalized(base.get('finish'))
           for r in refs):
        return None
    return base


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
        # printings normally block the match. The only exception is an
        # unsuffixed base independently recorded in the official checklist;
        # its parallel printings never inherit the base marketplace SKU.
        if len({(r['provider_id'],normalized(r['name'])) for r in refs}) == 1:
            ref = refs[0]
        else:
            ref = official_base_with_parallels(refs)
            if ref is None:
                continue
        expansion = expansions.get(release_identity(ref['set_name']))
        candidates = cards.get((expansion, number), []) if expansion else []
        # Bandai's published catalogue occasionally HTML-escapes ampersands
        # ("&amp;") while Cardmarket's export uses the visible card name.
        # Decode text only for comparison; preserve the original reference
        # identity and require a single product in the exact release.
        if len(candidates) == 1 and candidates[0][0] == normalized(html.unescape(ref['name'])):
            if ref['provider_id'] in result and result[ref['provider_id']]['idProduct'] != candidates[0][1]['idProduct']:
                conflicts.add(ref['provider_id'])
            result[ref['provider_id']] = candidates[0][1]
    return {key:value for key,value in result.items() if key not in conflicts}


async def refresh_one_piece_prices(pool, actor, fx, *, official_base_only=False):
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
              where r.provider in ('Bandai Official','Punk Records') and r.system_code='ONE_PIECE_CARD_GAME'
                and (r.language='English' or (r.language='Japanese' and r.provider='Punk Records'))
                and (s.release_date is null or s.release_date<=current_date)''')]
        from .one_piece_japanese_market import matched_japanese_products, japanese_nonenglish_quote
        matches = matched_products(references,singles,packaging)
        english_groups = defaultdict(list)
        for ref in references:
            if (ref['system_code'], ref['language']) == ('ONE_PIECE_CARD_GAME', 'English'):
                english_groups[(ref['set_id'], ref['card_number'])].append(ref)
        official_base_groups = {key for key, refs in english_groups.items()
                                if official_base_with_parallels(refs) is not None}
        jp_matches = matched_japanese_products(references,singles,packaging)
        jp_references = [ref for ref in references if ref['language']=='Japanese']
        report.update(checked=len(references),matched=len(matches)+len(jp_matches))
        starter_refs = [r for r in references if r['language']=='English' and
                        r['set_name'] in STARTER_RELEASE_ALIASES]
        if starter_refs:
            report.update(starter_alias_checked=len(starter_refs),
                          starter_alias_matched=sum(r['provider_id'] in matches for r in starter_refs))
        # Keep the previous lightweight receipt shape for English-only fixture tests.
        if jp_references:
            report.update(japanese_checked=len(jp_references),japanese_matched=len(jp_matches))
        if references and not matches and not jp_matches:
            raise ValueError('No unambiguous Cardmarket release matches')
        conversion = await fx.quote(base_currency='EUR',quote_currency='GBP',at=observed)
        values = []
        for ref in references:
            # Provider ids are reused verbatim across English and Japanese
            # official printings. Never fall through to an English marketplace
            # product just because the Japanese base/region match is missing.
            if ref['language']=='Japanese':
                jp_match = jp_matches.get(ref['provider_id'])
                product = jp_match['product'] if jp_match else None
            elif ref['language']=='English':
                jp_match = None
                product = matches.get(ref['provider_id'])
            else:
                jp_match = None
                product = None
            price = prices.get(str(product['idProduct'])) if product else None
            quote = None
            if jp_match:
                quote = japanese_nonenglish_quote(ref,jp_match,price,observed,conversion)
            elif price and price.get('idCategory') == product['idCategory']:
                try:
                    selected = choose_bulk_price_field(price, 'trend')
                    if selected is None:
                        raise ValueError('No positive trend or eligible 30-day guide')
                    original, source_field = selected
                    gbp = int((Decimal(original)*conversion.rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                    if gbp > 0:
                        quote = {'source':SOURCE,'product_id':str(product['idProduct']),
                            'expansion_id':product['idExpansion'],'source_field':source_field,
                            'original_currency':'EUR','original_minor':original,'price_gbp_minor':gbp,
                            'observed_at':observed.isoformat(),'finish':'Printing guide',
                            'valuation_role':'MIXED_LANGUAGE_REFERENCE','physical_language_confirmed':False,
                            'condition_specific':False,'match_basis':('EXACT_PREMIUM_RELEASE_UNIQUE_PRINTING'
                                if release_identity(ref['set_name'])[1] in {'PRB01','PRB02'}
                                else 'UNIQUE_RELEASE_NAME_NUMBER_IN_BOTH_CHECKLISTS'),
                            'reference_printing_id':ref['provider_id'],'reference_rarity':ref.get('rarity'),
                            'reference_identity':{key:ref[key] for key in ('name','set_id','card_number','set_name')},
                            'fx_rate_to_gbp':str(conversion.rate),'fx_source':conversion.source,
                            'fx_effective_at':conversion.effective_at.isoformat(),
                            'fx_retrieved_at':conversion.retrieved_at.isoformat()}
                except (ValueError,TypeError,ArithmeticError):
                    pass
            if quote and quote.get('source_field') == 'avg30':
                quote.update(guide_window_days=30, physical_valuation_eligible=False)
            if quote and quote.get('match_basis')=='EXACT_PREMIUM_RELEASE_UNIQUE_PRINTING':
                quote['physical_valuation_eligible']=False
            if (quote and ref['language']=='English'
                    and (ref['set_id'], ref['card_number']) in official_base_groups
                    and ref['provider_id']==ref['card_number']):
                quote.update(match_basis=OFFICIAL_BASE_PARALLEL_BASIS,
                             physical_valuation_eligible=False)
            if quote and ref['language']=='English' and ref['set_name'] in STARTER_RELEASE_ALIASES:
                quote.update(match_basis=STARTER_ALIAS_BASIS, physical_valuation_eligible=False)
            value = quote['price_gbp_minor'] if quote else None
            values.append((ref['provider'],ref['system_code'],ref['language'],ref['provider_id'],
                [quote] if quote else [],value,value,observed if quote else None,now,now+timedelta(days=1),
                ref['name'],ref['set_id'],ref['card_number'],ref['set_name']))
        if official_base_only:
            # A one-time recovery must never clear or reprice unrelated
            # references. Persist only positively quoted, publisher-confirmed
            # unsuffixed bases; unmatched and parallel records stay untouched.
            values = [row for row in values if row[4] and
                      row[4][0].get('match_basis')==OFFICIAL_BASE_PARALLEL_BASIS]
            report['recovery_mode']='OFFICIAL_BASE_ONLY'
        for start in range(0,len(values),100):
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await connection.executemany(WRITE_SQL,values[start:start+100])
        report['priced'] = sum(row[5] is not None for row in values)
        if official_base_groups:
            report['official_base_groups_matched'] = sum(
                any(r['set_id']==set_id and r['card_number']==number
                    and r['provider_id']==number and number in matches
                    for r in references if r['language']=='English')
                for set_id, number in official_base_groups)
            report['official_base_priced'] = sum(
                bool(row[4]) and row[4][0].get('match_basis')==OFFICIAL_BASE_PARALLEL_BASIS
                for row in values)
        if starter_refs:
            report['starter_alias_priced'] = sum(
                row[5] is not None and row[2]=='English' and row[13] in STARTER_RELEASE_ALIASES
                for row in values)
        if jp_references:
            report['japanese_priced'] = sum(row[5] is not None and row[2]=='Japanese' for row in values)
            report['english_priced'] = report['priced']-report['japanese_priced']
    except (httpx.HTTPError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        # Provider/FX outages preserve previous usable evidence. Ambiguous
        # identities in a successful export are explicitly cleared above.
        report.update(provider_failures=1,reason=type(exc).__name__)
    return report
