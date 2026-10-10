"""Daily, labelled Cardmarket guide estimates using exact cached print evidence.

Guide statistics never become individual sold comparisons. Source condition and
language remain unspecified; a guide is never applied to a slab or worn copy.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from .access_control import require_platform_admin
from .catalogue_valuations import IDENTITY_SQL, TARGET_SQL, WRITE_SQL
from .db import user_connection
from .market_adapters import NormalizedMarketObservation, stable_source_record_key
from .market_ingestion import _insert_observation
from .pricing_engine import ComparableTarget, MarketObservation, calculate_price
from .reference_library import number_key
from .reference_market import SOURCE, _text, _time

CATALOGUE_METHOD = 'CATALOGUE_CARDMARKET_V1'
INVENTORY_METHOD = 'CARDMARKET_GUIDE_V1'
REVISION = 4
MAX_AGE = timedelta(days=7)
LIMITATION = 'EU price guide across languages and conditions; not a condition-adjusted UK sold value.'
GUIDE_WRITE_SQL = WRITE_SQL.replace('\n on conflict',
    '\n and tcg.cardmarket_reference_current($17::jsonb)\n on conflict')

REFERENCES_SQL = '''select p.id as catalogue_id,r.provider,r.system_code,r.provider_id,r.set_id,
 r.language as reference_language,r.name as reference_name,s.name as reference_set_name,
 r.card_number as reference_number,r.rarity as reference_rarity,m.quotes
 from tcg.catalogue_products p join tcg.reference_cards r
 on p.product_type='CARD' and p.game='Pokemon' and r.provider='TCGdex'
 and r.system_code='POKEMON_TCG' and lower(p.name)=lower(r.name)
 join tcg.reference_sets s on (s.provider,s.system_code,s.language,s.set_id)=
 (r.provider,r.system_code,r.language,r.set_id)
 left join tcg.reference_market_prices m on (m.provider,m.system_code,m.language,m.provider_id)=
 (r.provider,r.system_code,r.language,r.provider_id)
 where p.id=any($1::uuid[]) and lower(p.set_name)=lower(s.name)
 and (s.release_date is null or s.release_date<=current_date)
 and not exists(select 1 from tcg.provider_catalogue_mappings link
   where link.catalogue_id=p.id and link.source_provider=r.provider
   and link.provider_language=r.language and link.match_status in ('REVIEW','REJECTED'))
 and not exists(select 1 from tcg.market_source_mappings link
   where link.catalogue_id=p.id and link.source='CARDMARKET' and link.match_status in ('REVIEW','REJECTED'))'''

BANDAI_REFERENCES_SQL = '''select p.id as catalogue_id,r.provider,r.system_code,r.provider_id,r.set_id,
 r.language as reference_language,r.name as reference_name,s.name as reference_set_name,
 r.card_number as reference_number,r.rarity as reference_rarity,m.quotes
 from tcg.catalogue_products p join tcg.reference_cards r
 on p.product_type='CARD' and r.language='English'
 and ((p.game='One Piece' and r.system_code='ONE_PIECE_CARD_GAME' and r.provider in ('Punk Records','Bandai Official'))
   or (p.game='Dragon Ball Super' and r.system_code='DRAGON_BALL_SUPER_MASTERS' and r.provider='Bandai Official')
   or (p.game='Dragon Ball Super Fusion World' and r.system_code='DRAGON_BALL_SUPER_FUSION_WORLD' and r.provider='Bandai Official'))
 and upper(replace(p.card_number,' ',''))=r.card_number
 join tcg.reference_sets s on (s.provider,s.system_code,s.language,s.set_id)=
 (r.provider,r.system_code,r.language,r.set_id)
 left join tcg.reference_market_prices m on (m.provider,m.system_code,m.language,m.provider_id)=
 (r.provider,r.system_code,r.language,r.provider_id)
 where p.id=any($1::uuid[]) and (s.release_date is null or s.release_date<=current_date)
 and not exists(select 1 from tcg.provider_catalogue_mappings link
   where link.catalogue_id=p.id and link.provider_language=r.language and link.match_status in ('REVIEW','REJECTED'))
 and not exists(select 1 from tcg.market_source_mappings link
   where link.catalogue_id=p.id and link.source='CARDMARKET' and link.match_status in ('REVIEW','REJECTED'))'''

INVENTORY_SQL = f'''select i.*,p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,
 {IDENTITY_SQL} as current_identity_digest,ps.evidence as current_evidence,
 ps.algorithm_version as current_algorithm,ps.sold_observation_count as current_sold_count,
 ps.market_value_minor as snapshot_market_value_minor
 from tcg.inventory_items i join tcg.catalogue_products p on p.id=i.catalogue_id
 join tcg.owners o on o.id=i.owner_id and o.active
 left join tcg.pricing_snapshots ps on ps.id=i.latest_pricing_snapshot_id
   and ps.inventory_id=i.id and ps.catalogue_id=i.catalogue_id and ps.owner_id=i.owner_id
 where i.catalogue_id=$1 and i.status in ('DRAFT','INSPECTION','APPROVED')
 and not exists(select 1 from tcg.market_source_mappings link
   where link.catalogue_id=p.id and link.source='CARDMARKET' and link.match_status in ('REVIEW','REJECTED'))
 and not exists(select 1 from tcg.provider_catalogue_mappings link
   where link.catalogue_id=p.id and link.provider_language=i.language
   and link.match_status in ('REVIEW','REJECTED'))
 order by i.id for update of i'''
INVENTORY_ITEM_SQL = INVENTORY_SQL.replace('where i.catalogue_id=$1',
    'where i.catalogue_id=$1 and i.id=$2 and i.owner_id=$3')


def guide_values(product, references, *, now):
    """Require unique full set/name/collector-number/finish evidence per locale."""
    if product.get('product_type') != 'CARD':
        return []
    if product.get('game') != 'Pokemon':
        return bandai_guide_values(product,references,now=now)
    finish = product.get('variant')
    if finish not in {'Normal', 'Holofoil', 'Reverse Holofoil'}:
        return []
    canonical_language = _text(product.get('language'))
    candidates = {}
    for ref in references:
        language = ref.get('reference_language')
        if (ref.get('provider') != 'TCGdex' or ref.get('system_code') != 'POKEMON_TCG'
                or language not in {'English', 'Japanese'}
                or canonical_language not in {'', 'unknown', _text(language)}
                or _text(product.get('name')) != _text(ref.get('reference_name'))
                or _text(product.get('set_name')) != _text(ref.get('reference_set_name'))
                or (_text(product.get('rarity')) not in {'','unknown'} and _text(ref.get('reference_rarity')) not in {'','unknown'}
                    and _text(product['rarity']) != _text(ref['reference_rarity']))
                or not number_key(product.get('card_number'))
                or number_key(product.get('card_number')) != number_key(ref.get('reference_number'))):
            continue
        # Keep all exact reference candidates, including unpriced duplicates.
        # Price availability cannot resolve an ambiguous printing.
        candidates.setdefault(language, {}).setdefault(ref['provider_id'], []).append(ref)
    values = []
    for language, identities in candidates.items():
        if len(identities) != 1:
            continue
        rows = next(iter(identities.values()))
        quotes = {}
        for ref in rows:
            for quote in ref.get('quotes') or []:
                if not isinstance(quote,dict):continue
                if quote.get('source') != SOURCE or quote.get('finish') != finish:
                    continue
                try:
                    observed = _time(quote['observed_at'])
                    original = quote['original_minor'];gbp = quote['price_gbp_minor']
                    rate = Decimal(str(quote['fx_rate_to_gbp']))
                    if (quote.get('original_currency') != 'EUR'
                            or quote.get('source_field') not in {'trend','trend-holo'}
                            or type(original) is not int or type(gbp) is not int
                            or original <= 0 or gbp <= 0 or not rate.is_finite() or rate <= 0
                            or not quote.get('variant_id') or not str(quote.get('product_id', '')).isdigit()
                            or int(quote['product_id']) <= 0
                            or quote.get('fx_source') != 'ECB_EURO_REFERENCE_RATES'
                            or not now-MAX_AGE <= observed <= now
                            or int((Decimal(original)*rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) != gbp):
                        continue
                    _time(quote['fx_effective_at']);_time(quote['fx_retrieved_at'])
                except (ValueError, TypeError, KeyError, InvalidOperation):
                    continue
                quotes[json.dumps(quote, sort_keys=True)] = quote
        if len(quotes) != 1:
            continue
        quote = next(iter(quotes.values()));ref = rows[0]
        values.append(_guide_value(ref,quote,language,finish,now=now))
    return values


def _guide_value(ref,quote,language,finish,*,now):
    observed = _time(quote['observed_at'])
    observation = MarketObservation(source='CARDMARKET', observation_type='PRICE_GUIDE',
        observed_at=observed, price_gbp_minor=quote['price_gbp_minor'],
        evidence_quality=.65, source_country='EU')
    result = calculate_price([observation], target=ComparableTarget(), as_of=now)
    result = replace(result, confidence=min(result.confidence, .60), auto_publish_eligible=False,
                     block_reasons=tuple(dict.fromkeys((*result.block_reasons, 'REFERENCE_ESTIMATE'))))
    evidence = {'method':CATALOGUE_METHOD, 'input_sale_count':0, 'source':'CARDMARKET',
        'valuation_kind':'REFERENCE_ESTIMATE', 'limitation':LIMITATION,
        'condition_breakdown_available':False, 'language_breakdown_available':False,
        'reference':{key:ref[key] for key in ('provider','system_code','provider_id','set_id','reference_language',
            'reference_name','reference_set_name','reference_number')}, 'quote':quote}
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return {'language':language, 'result':result, 'evidence':evidence, 'evidence_digest':digest,
        'evidence_checked_at':observed,
        'basis_key':hashlib.sha256(json.dumps([CATALOGUE_METHOD,language,finish]).encode()).hexdigest()}


def rarity_key(value):
    text=str(value or '').strip().upper()
    match=re.fullmatch(r'.+\[([A-Z]+)\]',text)
    if match:return match[1]
    return {'COMMON':'C','UNCOMMON':'UC','RARE':'R','SUPER RARE':'SR','SECRET RARE':'SEC',
            'LEADER':'L'}.get(text,text)


def bandai_name(value,collector):
    """Ignore only a repeated, matching collector number in an import title."""
    from .one_piece_market import normalized
    text=str(value or '').strip();number=str(collector or '').strip().upper()
    if re.fullmatch(r'[A-Z]{1,3}\d{2}-\d{3}',number):
        suffix=re.fullmatch(r'(.+?)\s+\(([A-Z0-9-]+)\)',text,re.I)
        if suffix and suffix[2].upper() in {number,number.rsplit('-',1)[1]}:
            text=suffix[1]
        else:
            suffix=re.fullmatch(r'(.+?)\s+-\s+([A-Z]{1,3}\d{2}-\d{3})',text,re.I)
            if suffix and suffix[2].upper()==number:text=suffix[1]
    return normalized(text)


def bandai_guide_values(product,references,*,now):
    from . import dragon_ball_market as db
    from .one_piece_market import SOURCE as BULK_SOURCE,normalized,release_identity
    systems={'One Piece':'ONE_PIECE_CARD_GAME','Dragon Ball Super':db.MASTERS,
             'Dragon Ball Super Fusion World':db.FUSION}
    system=systems.get(product.get('game'))
    if not system or _text(product.get('language')) not in {'','unknown','english'}:
        return []
    candidates={}
    for ref in references:
        release=(release_identity(ref.get('reference_set_name','')) if system=='ONE_PIECE_CARD_GAME'
                 else db.release_identity(system,ref.get('reference_set_name','')))
        title=release[0] if system=='ONE_PIECE_CARD_GAME' and release else release[1] if release else None
        canonical_title=normalized(product.get('set_name'))
        if canonical_title=='500yearsinthefuture':canonical_title='500yearsintothefuture'
        if (ref.get('system_code')!=system or ref.get('reference_language')!='English'
                or ref.get('provider') not in ({'Punk Records','Bandai Official'} if system=='ONE_PIECE_CARD_GAME' else {'Bandai Official'})
                or not title or title!=canonical_title
                or bandai_name(product.get('name'),product.get('card_number'))!=bandai_name(ref.get('reference_name'),ref.get('reference_number'))
                or not number_key(product.get('card_number'))
                or number_key(product.get('card_number'))!=number_key(ref.get('reference_number'))):
            continue
        candidates[(ref['provider'],ref['provider_id'],ref['set_id'])]=ref
    # An unpriced duplicate is still a duplicate. Never choose by availability.
    if len(candidates)!=1:return []
    ref=next(iter(candidates.values()))
    rarity=rarity_key(ref.get('reference_rarity'))
    if rarity and rarity_key(product.get('rarity')) not in {'','UNKNOWN',rarity}:return []
    finish=product.get('variant')
    if system=='ONE_PIECE_CARD_GAME':
        # Physical-copy fallback is deliberately limited to the ordinary base
        # printing of a booster, with its published rarity. Reference quotes
        # can still display for exact special printings without pricing stock.
        if ref['provider_id']!=ref['reference_number']:return []
        expected={'C':'Normal','UC':'Normal','L':'Normal','R':'Foil','SR':'Foil','SEC':'Foil'}.get(rarity)
        if not expected or ('Foil' if finish=='Holofoil' else finish)!=expected:return []
        fields={'trend'};quote_finish='Printing guide'
    else:
        quote_finish={'Normal':'Normal','Foil':'Holofoil','Holofoil':'Holofoil'}.get(finish)
        if not quote_finish:return []
        # The export can retain tiny default-column values for intrinsically
        # foil rarities. An imported "Normal" on these needs identity review,
        # not a fabricated nonfoil estimate or a silent finish correction.
        if quote_finish=='Normal' and rarity in {'SR','SPR','SCR','SEC','GDR'}:return []
        fields={'trend'} if quote_finish=='Normal' else {'trend-foil'}
    identity={'name':ref['reference_name'],'set_id':ref['set_id'],
              'card_number':ref['reference_number'],'set_name':ref['reference_set_name']}
    quotes={}
    for quote in ref.get('quotes') or []:
        if (not isinstance(quote,dict) or quote.get('source')!=BULK_SOURCE
                or quote.get('finish')!=quote_finish or quote.get('source_field') not in fields
                or quote.get('reference_printing_id')!=ref['provider_id']
                or quote.get('reference_identity')!=identity
                or quote.get('reference_rarity')!=ref.get('reference_rarity')
                or quote.get('match_basis') not in {'UNIQUE_RELEASE_NAME_NUMBER_IN_BOTH_CHECKLISTS','UNIQUE_RELEASE_AND_PRINTING_IN_BOTH_CHECKLISTS'}):
            continue
        try:
            original=quote['original_minor'];gbp=quote['price_gbp_minor'];rate=Decimal(str(quote['fx_rate_to_gbp']))
            observed=_time(quote['observed_at'])
            if (quote.get('original_currency')!='EUR' or type(original) is not int or type(gbp) is not int
                    or original<=0 or gbp<=0 or not rate.is_finite() or rate<=0
                    or not str(quote.get('product_id','')).isdigit() or int(quote['product_id'])<=0
                    or type(quote.get('expansion_id')) is not int or quote['expansion_id']<=0
                    or quote.get('fx_source')!='ECB_EURO_REFERENCE_RATES'
                    or not now-MAX_AGE<=observed<=now
                    or int((Decimal(original)*rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))!=gbp):continue
            _time(quote['fx_effective_at']);_time(quote['fx_retrieved_at'])
        except (ValueError,TypeError,KeyError,InvalidOperation):continue
        quotes[json.dumps(quote,sort_keys=True)]=quote
    if len(quotes)!=1:return []
    return [_guide_value(ref,next(iter(quotes.values())),'English',finish,now=now)]


def inventory_eligible(item, value, *, now):
    if (item.get('status') not in {'DRAFT','INSPECTION','APPROVED'} or not item.get('identity_confirmed')
            or item.get('grading_company') or item.get('grade') or item.get('seal_status')
            or item.get('product_type') != 'CARD' or item.get('condition') not in {'Near Mint','NM'}
            or item.get('language') != value['language']
            or item.get('current_identity_digest') != value['identity_digest']):
        return False
    evidence = item.get('current_evidence') or {}
    # Never replace current exact eBay sold evidence with a lower-specificity guide.
    has_ebay = (item.get('current_algorithm') == 'drop-rate-market-v4'
        and any(s.get('source') == 'EBAY' for s in evidence.get('sources', []))
        and (evidence.get('method') == 'LIVE_EBAY_MARKET_V1' or (item.get('current_sold_count') or 0) >= 5)
        and item.get('market_value_minor') == item.get('snapshot_market_value_minor')
        and item.get('market_value_minor') is not None
        and item.get('pricing_updated_at') is not None
        and item['pricing_updated_at'] >= now-MAX_AGE)
    if has_ebay:
        return False
    return not (evidence.get('method') == INVENTORY_METHOD
                and evidence.get('catalogue_snapshot_id') == str(value['snapshot_id'])
                and evidence.get('physical_basis') == physical_basis(item)
                and item.get('market_value_minor') == value['result'].market_value_minor
                and item.get('pricing_updated_at') == value['evidence_checked_at'])


def physical_basis(item):
    return {key: str(item.get(key) or '') for key in
            ('catalogue_id','condition','language','grading_company','grade','seal_status')}


async def apply_inventory_guide(connection, item, value, *, now):
    if not inventory_eligible(item, value, now=now):
        return False
    from .pricing import _policy_from_row
    policy = await connection.fetchrow('select * from tcg.pricing_policies where owner_id=$1', item['owner_id'])
    quote = value['evidence']['quote']
    result = calculate_price([MarketObservation(source='CARDMARKET', observation_type='PRICE_GUIDE',
        observed_at=value['evidence_checked_at'], price_gbp_minor=quote['price_gbp_minor'],
        source_country='EU', evidence_quality=.65)],
        target=ComparableTarget(condition=item['condition'],language=item['language']),
        policy=_policy_from_row(policy) if policy else None,
        current_store_price_minor=item.get('store_price_minor'), as_of=now)
    evidence = {**value['evidence'], 'method':INVENTORY_METHOD,
        'catalogue_snapshot_id':str(value['snapshot_id']), 'catalogue_identity_digest':value['identity_digest'],
        'physical_basis':physical_basis(item), 'sources':[{'source':'CARDMARKET',
            'observation_type':'PRICE_GUIDE','estimate_minor':result.market_value_minor,
            'sold_observation_count':0,'newest_observation_at':value['evidence_checked_at'].isoformat()}]}
    snapshot = await connection.fetchval('''insert into tcg.pricing_snapshots
      (inventory_id,catalogue_id,owner_id,market_value_minor,recommended_retail_minor,quick_sale_minor,
       target_acquisition_minor,confidence,source_count,observation_count,sold_observation_count,
       volatility_pct,newest_observation_at,algorithm_version,evidence,auto_publish_eligible,block_reasons)
      values($1,$2,$3,$4,$5,$6,$7,$8,1,1,0,0,$9,$10,$11::jsonb,false,$12::jsonb) returning id''',
      item['id'],item['catalogue_id'],item['owner_id'],result.market_value_minor,result.recommended_retail_minor,
      result.quick_sale_minor,result.target_acquisition_minor,min(result.confidence,.60),value['evidence_checked_at'],
      result.algorithm_version,json.dumps(evidence),json.dumps(list(dict.fromkeys((*result.block_reasons,'REFERENCE_ESTIMATE')))))
    # Catalogue identity is read-only for the API role. Recheck its digest in
    # the guarded write instead of requesting an UPDATE-requiring row lock.
    updated = await connection.fetchval(f'''update tcg.inventory_items i set market_value_minor=$1,
      recommended_retail_minor=$2,latest_pricing_snapshot_id=$3,pricing_updated_at=$4,
      updated_at=now(),version=i.version+1 where i.id=$5 and i.owner_id=$6 and i.version=$7
      and i.catalogue_id=$8 and exists(select 1 from tcg.catalogue_products p
        where p.id=i.catalogue_id and {IDENTITY_SQL}=$9)
      and tcg.cardmarket_reference_current($10::jsonb) returning i.id''',
      result.market_value_minor,result.recommended_retail_minor,snapshot,value['evidence_checked_at'],
      item['id'],item['owner_id'],item['version'],item['catalogue_id'],value['identity_digest'],value['evidence'])
    if updated is None:
        raise ValueError('Inventory changed during guide application')
    return True


async def apply_cached_inventory_guide(connection, inventory_id, owner_id, catalogue_id):
    """Use already saved public evidence during intake/manual recalculation."""
    from types import SimpleNamespace
    now=datetime.now(timezone.utc)
    # The caller already locks this item. Do not also lock another owner's copy
    # here: simultaneous recalculations would acquire row locks out of order.
    rows=await connection.fetch(INVENTORY_ITEM_SQL,catalogue_id,inventory_id,owner_id)
    item=next((dict(row) for row in rows if row['id']==inventory_id and row['owner_id']==owner_id),None)
    if item is None:return None
    guide=await connection.fetchrow('''select * from tcg.catalogue_market_snapshots
      where catalogue_id=$1 and identity_digest=$2 and basis_language=$3
      and evidence->>'method'='CATALOGUE_CARDMARKET_V1'
      and tcg.cardmarket_reference_current(evidence)
      and evidence_checked_at between $4::timestamptz-interval '7 days' and $4
      order by evidence_checked_at desc,calculated_at desc,id limit 1''',
      catalogue_id,item['current_identity_digest'],item.get('language'),now)
    if guide is None:return None
    value={'language':guide['basis_language'],'identity_digest':guide['identity_digest'],
           'snapshot_id':guide['id'],'evidence':guide['evidence'],
           'evidence_checked_at':guide['evidence_checked_at'],
           'result':SimpleNamespace(market_value_minor=guide['market_value_minor'])}
    await apply_inventory_guide(connection,item,value,now=now)
    # A disallowed physical basis must not return a historical guide as current.
    if (not item['identity_confirmed'] or item.get('grading_company') or item.get('grade')
            or item.get('seal_status') or item.get('condition') not in {'Near Mint','NM'}):return None
    return await connection.fetchrow('''select s.* from tcg.inventory_items i
      join tcg.pricing_snapshots s on s.id=i.latest_pricing_snapshot_id
      where i.id=$1 and i.owner_id=$2 and s.owner_id=i.owner_id and s.inventory_id=i.id
      and s.catalogue_id=i.catalogue_id and i.market_value_minor=s.market_value_minor
      and s.evidence->>'method'='CARDMARKET_GUIDE_V1'
      and s.evidence->>'catalogue_snapshot_id'=$3''',inventory_id,owner_id,str(guide['id']))


async def refresh_cardmarket_values(pool, actor):
    from .catalogue_maintenance import receipt
    run = await receipt(pool,actor,'CARDMARKET_VALUES','RUNNING',{})
    report = {'importer_revision':REVISION,'catalogue_products_checked':0,'guide_bases':0,
              'snapshots_inserted':0,'inventory_updated':0,'provider_calls':0,'store_price_updates':0}
    status='INCOMPLETE';cursor=None;now=datetime.now(timezone.utc)
    try:
        while True:
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await require_platform_admin(connection)
                products=[dict(row) for row in await connection.fetch(TARGET_SQL,cursor)]
                if not products:break
                references=[dict(row) for row in await connection.fetch(REFERENCES_SQL,[p['catalogue_id'] for p in products])]
                references.extend(dict(row) for row in await connection.fetch(BANDAI_REFERENCES_SQL,[p['catalogue_id'] for p in products]))
            for product in products:
                report['catalogue_products_checked']+=1
                values=guide_values(product,[r for r in references if r['catalogue_id']==product['catalogue_id']],now=now)
                for value in values:
                    result=value['result'];report['guide_bases']+=1
                    async with user_connection(pool,actor,str(uuid4())) as connection:
                        await require_platform_admin(connection)
                        snapshot=await connection.fetchval(GUIDE_WRITE_SQL,product['catalogue_id'],product['identity_digest'],
                            value['basis_key'],None,value['language'],None,None,None,result.market_value_minor,
                            result.recommended_retail_minor,result.confidence,result.algorithm_version,None,
                            value['evidence_checked_at'],now.date(),value['evidence_digest'],value['evidence'])
                        report['snapshots_inserted']+=bool(snapshot)
                        if snapshot is None:
                            snapshot=await connection.fetchval('''select id from tcg.catalogue_market_snapshots
                              where catalogue_id=$1 and identity_digest=$2 and basis_key=$3 and calculation_day=$4
                              and evidence_digest=$5 and tcg.cardmarket_reference_current(evidence)''',product['catalogue_id'],product['identity_digest'],
                              value['basis_key'],now.date(),value['evidence_digest'])
                        if snapshot is None:continue
                        value.update(snapshot_id=snapshot,identity_digest=product['identity_digest'])
                        quote=value['evidence']['quote']
                        await _insert_observation(connection,NormalizedMarketObservation(
                            source='CARDMARKET',catalogue_id=str(product['catalogue_id']),
                            source_record_key=stable_source_record_key('CARDMARKET',str(product['catalogue_id']),value['evidence_digest']),
                            observation_type='PRICE_GUIDE',observed_at=value['evidence_checked_at'],
                            price_minor=quote['original_minor'],currency='EUR',price_gbp_minor=quote['price_gbp_minor'],
                            fx_rate_to_gbp=float(quote['fx_rate_to_gbp']),source_country='EU',evidence_quality=.65,
                            metadata=value['evidence']).validate())
                        items=await connection.fetch(INVENTORY_SQL,product['catalogue_id'])
                        for item in items:
                            report['inventory_updated']+=await apply_inventory_guide(connection,dict(item),value,now=now)
            cursor=products[-1]['catalogue_id']
        status='COMPLETE'
    finally:
        await receipt(pool,actor,'CARDMARKET_VALUES',status,report,run)
    return report
