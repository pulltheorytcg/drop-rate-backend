"""Display-only catalogue guides for copies without an exact valuation.

Reading a guide never assigns condition, confirms a printing, prices stock or
supplies a retail recommendation. Use the shared cache, with its real source
date; do not make provider requests while rendering an account.
"""
from __future__ import annotations

import json
import re
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
 (select profile.system_code from tcg.catalogue_product_profiles profile
  where profile.catalogue_id=p.id) as profile_system_code,
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



def _legacy_unlimited_reference(product, language):
    """One observed legacy import; no general numerator or edition guessing."""
    return (language == 'English'
            and clean_language(product.get('language')) in {None, 'English'}
            and all(_text(product.get(key)) == value for key, value in {
                'game': 'pokemon', 'name': 'pikachu', 'set_name': 'base set (unlimited)',
                'card_number': '58', 'variant': 'normal', 'rarity': 'common',
            }.items()))


def catalogue_number_key(product):
    """Expand only the explicit legacy printing before its indexed lookup."""
    if _legacy_unlimited_reference(product, 'English'):
        return collector_key('58/102')
    return collector_key(product.get('card_number'))



MASTERS_SYSTEM = "DRAGON_BALL_SUPER_MASTERS"
# Reviewed ordinary booster imports only. Pre-release labels and combined leader
# faces cannot inherit a guide from the ordinary base checklist.
LEGACY_MASTERS_RELEASES = {
    "supreme rivalry": ("428013","UW04 Booster -Supreme Rivalry-","BT13"),
    "dawn of the z-legends": ("428018","Z01 Booster -DAWN OF THE Z-LEGENDS-","BT18"),
    "power absorbed": ("428020","Z03 Booster -POWER ABSORBED-","BT20"),
    "perfect combination": ("428023","Z06 Booster -PERFECT COMBINATION-","BT23"),
    "prismatic clash": ("428028","UB01 Booster -PRISMATIC CLASH-","BT28"),
    "three glorious fighters": ("428030","UB03 Booster -THREE GLORIOUS FIGHTERS-","BT30"),
}


def catalogue_system(product):
    if product.get("game")=="Dragon Ball Super":
        return MASTERS_SYSTEM if product.get("profile_system_code")==MASTERS_SYSTEM else None
    return SYSTEM_BY_GAME.get(product.get("game"))


def _legacy_masters(product):
    return product.get("game")=="Dragon Ball Super" and catalogue_system(product)==MASTERS_SYSTEM


def _masters_candidates(product,rows,language):
    from .masters_cardtrader_market import rarity_key as masters_rarity
    release=LEGACY_MASTERS_RELEASES.get(_text(product.get("set_name")))
    number=product.get("card_number")
    finish=product.get("variant")
    rarity=masters_rarity(product.get("rarity"))
    if (language!="English" or clean_language(product.get("language"))!="English"
            or not release or not isinstance(number,str)
            or not re.fullmatch(release[2]+r"-[0-9]{3}",number)
            or not product.get("name") or "//" in product["name"]
            or finish not in {"Normal","Foil","Holofoil"} or not rarity
            or (finish=="Normal" and rarity not in {"common","uncommon","rare"})):
        return []
    same_number=[r for r in rows if r.get("provider")=="Bandai Official"
        and r.get("language")=="English" and r.get("set_id")==release[0]
        and r.get("set_name")==release[1] and r.get("card_number")==number]
    if any(masters_rarity(r.get("rarity")) is None for r in same_number):
        return []
    choices=[r for r in same_number if masters_rarity(r.get("rarity"))==rarity]
    if len(choices)!=1:
        return []
    row=choices[0]
    if (row.get("provider_id")!=release[0]+":"+number+".png"
            or bandai_name(product["name"],number)!=bandai_name(row.get("name"),number)):
        return []
    return choices


def _masters_quote_matches(product,row,quote):
    from .masters_cardtrader_market import MATCH_BASIS,rarity_key as masters_rarity
    identity={k:row[k] for k in ("name","set_id","card_number","set_name")}
    finish="Normal" if product.get("variant")=="Normal" else "Holofoil"
    field=quote.get("source_field")
    fields={"trend","avg30"} if finish=="Normal" else {"trend-foil","avg30-foil"}
    if (quote.get("source")!="CARDMARKET_BULK_SINGLES"
            or quote.get("reference_identity")!=identity
            or quote.get("reference_printing_id")!=row["provider_id"]
            or quote.get("reference_rarity")!=row.get("rarity")
            or quote.get("reference_language","English")!="English"
            or quote.get("finish")!=finish or field not in fields
            or quote.get("valuation_role")!="MIXED_LANGUAGE_REFERENCE"
            or quote.get("condition_specific") is not False
            or quote.get("physical_language_confirmed") is not False
            or (quote.get("physical_valuation_eligible") is not None
                and quote.get("physical_valuation_eligible") is not False)
            or not str(quote.get("product_id") or "").isdigit()
            or int(quote["product_id"])<=0
            or type(quote.get("expansion_id")) is not int or quote["expansion_id"]<=0
            or (field.startswith("avg30") and quote.get("guide_window_days")!=30)):
        return False
    basis=quote.get("match_basis")
    if basis=="UNIQUE_RELEASE_AND_PRINTING_IN_BOTH_CHECKLISTS":
        return True
    if basis!=MATCH_BASIS:
        return False
    collector=str(quote.get("cardtrader_collector_number") or "")
    return (quote.get("mapping_source")=="CARDTRADER"
        and quote.get("physical_valuation_eligible") is False
        and type(quote.get("cardtrader_blueprint_id")) is int and quote["cardtrader_blueprint_id"]>0
        and type(quote.get("cardtrader_expansion_id")) is int and quote["cardtrader_expansion_id"]>0
        and quote.get("cardtrader_rarity_source")=="rarity"
        and masters_rarity(quote.get("cardtrader_rarity"))==masters_rarity(row.get("rarity"))
        and masters_rarity(quote.get("cardtrader_version"))==masters_rarity(row.get("rarity"))
        and re.fullmatch(re.escape(row["card_number"])+r"[A-Za-z]{0,3}",collector) is not None)


def reference_candidates(product, rows, language):
    """Exact selected reference, or a uniquely identified ordinary import."""
    system = catalogue_system(product)
    if not system or product.get('blocked'):
        return []
    rows = [r for r in rows if r['system_code'] == system]
    if _legacy_masters(product):
        return _masters_candidates(product,rows,language)
    if _legacy_unlimited_reference(product, language):
        return [r for r in rows if r['provider'] == 'TCGdex' and r['language'] == 'English'
                and r['provider_id'] == 'base1-58' and r['set_id'] == 'base1'
                and _text(r['name']) == 'pikachu' and _text(r['set_name']) == 'base set'
                and collector_key(r['card_number']) == collector_key('58/102')
                and _text(r.get('rarity')) in {'', 'common'}]
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



POKEWALLET_POKEMON_SOURCE = "POKEWALLET_POKEMON_CARDMARKET_CATALOGUE"


def _pokewallet_guide_matches(product, row, quote):
    """Admit only the existing exact-print Japanese regional guide contract."""
    from urllib.parse import urlsplit
    from .pokewallet_pokemon_market import SOURCE_ID, NUMERIC_SET_ID, reference_code
    if (reference_code(row) is None
            or quote.get('reference_language') != 'Japanese'
            or quote.get('reference_printing_id') != row['provider_id']
            or quote.get('reference_identity') != {k: row[k] for k in ('name','set_id','card_number','set_name')}
            or quote.get('match_basis') != 'EXACT_JAPANESE_SET_AND_UNIQUE_COMPLETE_COLLECTOR_FRACTION'
            or quote.get('aggregator') != 'POKEWALLET' or quote.get('market') != 'CARDMARKET'
            or quote.get('valuation_role') != 'MIXED_NON_ENGLISH_REFERENCE'
            or any(quote.get(field) is not False for field in (
                'condition_specific','sold_comparable','physical_language_confirmed','physical_valuation_eligible'))
            or quote.get('source_field') != 'trend'
            or not SOURCE_ID.fullmatch(str(quote.get('source_card_id') or ''))
            or not NUMERIC_SET_ID.fullmatch(str(quote.get('source_set_id') or ''))
            or quote.get('finish') not in {'normal','holo'}):
        return False
    # This guide selects one disclosed finish, not an all-finish price range.
    known_finish = product.get('variant')
    if known_finish in {'Normal','Holofoil','Reverse Holofoil'}:
        if {'Normal':'normal','Holofoil':'holo'}.get(known_finish) != quote['finish']:
            return False
    try:
        url = urlsplit(str(quote.get('source_product_url') or ''))
        return (url.scheme == 'https' and url.hostname in {'cardmarket.com','www.cardmarket.com'}
                and url.username is None and url.password is None and url.port is None
                and not url.query and not url.fragment
                and url.path.casefold().startswith((
                    '/en/pokemon/products/singles/','/it/pokemon/products/singles/',
                    '/de/pokemon/products/singles/','/fr/pokemon/products/singles/',
                    '/es/pokemon/products/singles/')))
    except ValueError:
        return False

def computed_catalogue_guide(row, quotes, language, *, now):
    """Expose the existing daily model for the same exact raw reference only."""
    ordinary = (
        row['provider'] == 'Bandai Official'
        and row['system_code'] == 'DRAGON_BALL_SUPER_MASTERS' and language == 'English'
        and row.get('rarity') in {'Common[C]', 'Uncommon[UC]'}
        and re.fullmatch(r'BT[0-9]+-[0-9]{2,3}', row['card_number'])
        and not re.search(r'_(PR[0-9]*|p[0-9]+)([.]|$)', row['provider_id'], re.I)
    ) or (
        row['system_code'] == 'ONE_PIECE_CARD_GAME' and language in {'English', 'Japanese'}
        and row.get('rarity') in {'C', 'UC', 'Common', 'Uncommon'}
        and row['provider_id'] == row['card_number']
        and re.fullmatch(r'(OP|EB|PRB|ST)[0-9]{2}-[0-9]{3}', row['card_number'])
    )
    models = [q for q in quotes if isinstance(q, dict) and q.get('source') == 'DROP_RATE_COMPUTED_MARKET_V1']
    if not ordinary or len(models) != 1:
        return None
    q = models[0]
    identity = {key: row[key] for key in ('name', 'set_id', 'card_number', 'set_name')}
    try:
        checked = _time(q['observed_at'])
        amount, low, high = q['price_gbp_minor'], q['low_gbp_minor'], q['high_gbp_minor']
        if (q.get('reference_identity') != identity or q.get('reference_printing_id') != row['provider_id']
                or q.get('reference_rarity') != row.get('rarity') or q.get('algorithm_version') != 1
                or q.get('method') != 'MODEL_SAME_SET_STANDARD_RARITY_P25'
                or q.get('verification_basis') != 'RULES_VERIFIED_PEER_MODEL'
                or q.get('observation_type') != 'DERIVED_NOT_SOLD' or q.get('confidence') != 'LOW'
                or q.get('physical_valuation_eligible') is not False or q.get('sold_comparable') is not False
                or q.get('condition_specific') is not False
                or type(q.get('independent_reference_count')) is not int or q['independent_reference_count'] < 5
                or not all(type(v) is int for v in (amount, low, high)) or not 0 < low <= amount <= high
                or not now-timedelta(days=2) <= checked <= now):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return {'status': 'CATALOGUE_GUIDE', 'currency': 'GBP',
            'market_value_minor': amount, 'market_value_high_minor': high,
            'checked_at': checked, 'basis': language + ' · Standard raw printing',
            'label': 'Drop Rate estimate', 'method': q['source'], 'algorithm_version': 1,
            'reason': 'Calculated by the Drop Rate model from current same-set, same-rarity comparisons. Low confidence; not a completed sale or a valuation of this copy’s condition.',
            'reference_id': ':'.join(row[k] for k in ('provider', 'system_code', 'language', 'provider_id')),
            'physical_valuation_eligible': False, 'recommended_retail_minor': None}


def catalogue_guide(product, rows, language, *, now):
    candidates = reference_candidates(product, rows, language)
    identities = {(r['provider'], r['system_code'], r['language'], r['provider_id']) for r in candidates}
    if len(identities) != 1:
        return None
    row = candidates[0]
    identity = {key: row[key] for key in ('name', 'set_id', 'card_number', 'set_name')}
    eligible = []
    legacy_unlimited = _legacy_unlimited_reference(product, language)
    legacy_masters = _legacy_masters(product)
    quotes = (row.get('quotes') or []) + (row.get('catalogue_quotes') or [])
    if legacy_masters:
        quotes=[q for q in quotes if isinstance(q,dict) and _masters_quote_matches(product,row,q)]
        # A second source product or unpriced competing quote cannot lose an
        # identity conflict merely because only one happens to have a value.
        if len(quotes)!=1:
            return None
    if legacy_unlimited:
        # Unlimited and Poketour share the same base ID. Match the complete
        # declared treatment, then reject duplicate/ambiguous source products
        # before considering prices. A broad catalogue guide is not sufficient.
        quotes = [q for q in quotes if isinstance(q, dict)
                  and q.get('source') == 'TCGDEX_CARDMARKET_VARIANT'
                  and q.get('variant_label') == 'Normal · unlimited']
        if len(quotes) != 1:
            return None
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        source = quote.get('source')
        if legacy_unlimited and (
                quote.get('finish') != 'Normal' or quote.get('reference_language') != 'English'
                or quote.get('valuation_role') != 'VARIANT_REFERENCE'
                or quote.get('physical_valuation_eligible') is not False
                or not isinstance(quote.get('variant_id'), str) or not quote['variant_id'].strip()
                or not str(quote.get('product_id') or '').isdigit()
                or int(quote['product_id']) <= 0
                or quote.get('source_field') != 'trend'):
            continue
        if source not in {'TCGDEX_CARDMARKET', 'TCGDEX_CARDMARKET_VARIANT', 'CARDMARKET_CATALOGUE', 'CARDMARKET_BULK_SINGLES', POKEWALLET_POKEMON_SOURCE}:
            continue
        if quote.get('reference_language', language) != language:
            continue
        if source == POKEWALLET_POKEMON_SOURCE and not _pokewallet_guide_matches(product, row, quote):
            continue
        if source in {'CARDMARKET_CATALOGUE', 'CARDMARKET_BULK_SINGLES'}:
            if quote.get('reference_identity') != identity:
                continue
            if source == 'CARDMARKET_BULK_SINGLES' and (quote.get('reference_printing_id') != row['provider_id']
                    or quote.get('reference_rarity') != row.get('rarity')):
                continue
        # An imported finish is known: do not show its alternate foil's price.
        finish = product.get('variant')
        if source.startswith('TCGDEX_') and not legacy_unlimited and finish in {'Normal', 'Holofoil', 'Reverse Holofoil'}:
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
        return computed_catalogue_guide(row, quotes, language, now=now)
    # Match catalogue source precedence: detailed quotes before broad guides.
    detailed = [v for v in eligible if v[2]['source'].startswith('TCGDEX_')]
    eligible = detailed or eligible
    regional = any(v[2].get('valuation_role') == 'MIXED_NON_ENGLISH_REFERENCE' for v in eligible)
    all_finishes = any(v[2]['source'] == 'CARDMARKET_CATALOGUE' for v in eligible)
    pokewallet = any(v[2]['source'] == POKEWALLET_POKEMON_SOURCE for v in eligible)
    return {'status': 'CATALOGUE_GUIDE', 'currency': 'GBP',
            'market_value_minor': min(v[0] for v in eligible),
            'market_value_high_minor': max(v[0] for v in eligible),
            'checked_at': min(v[1] for v in eligible), 'basis': language + ' · Raw catalogue reference',
            'label': ('Normal finish guide' if product['variant']=='Normal' else 'Foil finish guide') if legacy_masters else 'Unlimited edition guide' if legacy_unlimited else 'Regional guide' if regional else 'All-finish guide' if all_finishes else 'Catalogue guide',
            'reason': ('Cardmarket guide for the declared finish across conditions and languages; not a valuation of this copy.' if legacy_masters
                       else 'Cardmarket guide for the Normal unlimited treatment only; not a condition-specific valuation of this copy.' if legacy_unlimited
                       else 'Non-English regional Cardmarket guide via PokéWallet; not a Japanese condition-specific sale.' if regional and pokewallet
                       else 'Non-English regional guide; not a Japanese condition-specific sale.' if regional
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
            system = catalogue_system(product)
            key = catalogue_number_key(product)
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
