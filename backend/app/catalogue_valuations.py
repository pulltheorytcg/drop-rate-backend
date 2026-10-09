"""Owner-independent v4 catalogue values from immutable exact UK sold evidence.

No inventory rows or seller policy are read. Recalculation is not a new market
lookup: provider-evidence timestamps remain unchanged when the feed is paused.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4

from .access_control import require_platform_admin
from .db import user_connection
from .live_market_refresh import identity_key,select_comps,value_comps

DIMENSIONS=('condition','grading_company','grade','language','seal_status')
IDENTITY_SQL="md5(concat_ws(chr(31),p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language))"
TARGET_SQL=f'''select p.id as catalogue_id,p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language,
 {IDENTITY_SQL} as identity_digest,pr.set_code,pr.identity_status as profile_identity_status,
 sd.identity_status as sealed_identity_status,
 (select a.value_code from tcg.catalogue_taxonomy_assignments a where a.catalogue_id=p.id
   and a.scope_kind='SEALED' and a.dimension_code='SEALED_TYPE' and a.verification_status='VERIFIED'
   order by a.created_at desc limit 1) as sealed_product_type
 from tcg.catalogue_products p left join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
 left join tcg.sealed_product_details sd on sd.catalogue_id=p.id
 where ($1::uuid is null or p.id>$1) order by p.id limit 100'''
OBSERVATIONS_SQL='''select * from (
 select o.*,row_number() over(partition by catalogue_id,condition,grading_company,grade,language,seal_status
   order by observed_at desc,id) as position
 from tcg.market_observations o where catalogue_id=any($1::uuid[]) and source='EBAY'
  and observation_type='SOLD' and source_country='GB' and currency='GBP'
  and observed_at>=$2 and observed_at<=$3 and ingested_at<=$3
  and metadata->>'selection_rule'='FIVE_NEWEST_EXACT_COMPARABLE_SALES'
  and metadata->>'marketplace'='EBAY_GB'
 ) eligible where position<=100'''
PROVIDER_CHECK_SQL='''select distinct on(metadata->>'identity_key') metadata->>'identity_key' as identity_key,completed_at
 from tcg.market_ingestion_runs where source='EBAY' and status='SUCCEEDED'
 and metadata->>'job'='LIVE_EBAY_MARKET_V1' and metadata->>'comparable_count'='5'
 and (metadata->>'updated')::int>0 and completed_at>=$1 and completed_at<=$2
 order by metadata->>'identity_key',completed_at desc'''
WRITE_SQL=f'''insert into tcg.catalogue_market_snapshots
 (catalogue_id,identity_digest,basis_key,basis_condition,basis_language,grading_company,grade,seal_status,
 market_value_minor,recommended_retail_minor,confidence,algorithm_version,oldest_sale_at,evidence_checked_at,
 calculation_day,evidence_digest,evidence)
 select p.id,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb
 from tcg.catalogue_products p where p.id=$1 and {IDENTITY_SQL}=$2
 on conflict(catalogue_id,identity_digest,basis_key,calculation_day,evidence_digest) do nothing
 returning id'''


def catalogue_values(product,observations,*,now,provider_checks=None):
    groups=defaultdict(list)
    for row in observations:
        if (str(row['catalogue_id'])!=str(product['catalogue_id']) or row.get('source')!='EBAY'
                or row.get('observation_type')!='SOLD' or row.get('source_country')!='GB' or row.get('currency')!='GBP'
                or not now-timedelta(days=90)<=row['observed_at']<=now
                or row['ingested_at']>now
                or row.get('metadata',{}).get('selection_rule')!='FIVE_NEWEST_EXACT_COMPARABLE_SALES'
                or row.get('metadata',{}).get('marketplace')!='EBAY_GB'):
            continue
        dimensions=tuple(row.get(field) for field in DIMENSIONS)
        groups[dimensions].append(row)
    values=[]
    for dimensions,rows in groups.items():
        physical=dict(zip(DIMENSIONS,dimensions))
        if physical['language'] not in {'English','Japanese'} or physical['language']!=product['language']:
            continue
        target={**product,**physical,'store_price_minor':None}
        if product['product_type']=='CARD':
            if not product['variant'] or not product['card_number'] or not (physical['condition'] or (physical['grading_company'] and physical['grade'])):
                continue
        elif not (product['game']=='One Piece' and physical['seal_status']=='SEALED'
                  and product.get('profile_identity_status')==product.get('sealed_identity_status')=='VERIFIED'
                  and product.get('sealed_product_type')=='BOOSTER_PACK' and product.get('set_code')):
            continue
        candidates=[];evidence_by_id={}
        # Deduplicate listing IDs before matching; newest ingested evidence wins.
        for row in sorted(rows,key=lambda r:(r['ingested_at'],r['observed_at']),reverse=True):
            metadata=row['metadata'];item_id=str(metadata.get('provider_item_id') or '')
            if not item_id or item_id in evidence_by_id:continue
            evidence_by_id[item_id]=row
            candidates.append({'item_id':item_id,'title':metadata.get('title',''),
               'date_sold':row['observed_at'].isoformat(),'sale_price':str(Decimal(row['price_gbp_minor'])/100),
               'shipping_price':str(Decimal(row['shipping_gbp_minor'])/100) if row.get('shipping_gbp_minor') is not None else None,
               'currency':'GBP','condition_raw':row.get('condition'),'item_link':metadata.get('url')})
        comps=select_comps({'site':'EBAY_GB','currency':'GBP','results':candidates},target,now)
        if len(comps)!=5:continue
        result=value_comps(comps,target,now=now)
        selected=[evidence_by_id[comp['item_id']] for comp in comps]
        # An unchanged sale is deduplicated in the immutable observations table.
        # A successful exact-identity ingestion receipt proves it was rechecked;
        # simply rerunning this calculation does not. No inventory lookup occurs.
        checked=min(r['ingested_at'] for r in selected)
        provider_check=(provider_checks or {}).get(identity_key(dict(target,identity_confirmed=True)))
        if provider_check and checked<provider_check<=now:checked=provider_check
        if checked<now-timedelta(days=7):continue
        evidence={'method':'CATALOGUE_EBAY_V4','input_sale_count':5,'source':'EBAY_GB',
                  'sale_price_excludes_shipping':True,'observation_ids':[str(r['id']) for r in selected],
                  'comps':[dict(c,sold_at=c['sold_at'].isoformat()) for c in comps],
                  'sold_observations_after_outliers':result.sold_observation_count}
        basis_key=hashlib.sha256(json.dumps(dimensions).encode()).hexdigest()
        digest=hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
        values.append(dict(physical,result=result,evidence=evidence,basis_key=basis_key,evidence_digest=digest,
                           oldest_sale_at=min(r['observed_at'] for r in selected),
                           evidence_checked_at=checked))
    return values


async def refresh_catalogue_values(pool,actor):
    from .catalogue_maintenance import receipt
    run_id=await receipt(pool,actor,'CATALOGUE_VALUES','RUNNING',{})
    report={'catalogue_products_checked':0,'valued_products':0,'value_bases':0,'snapshots_inserted':0,
            'missing_exact_evidence':0,'inventory_rows_read':0,'provider_calls':0}
    now=datetime.now(timezone.utc);cursor=None;status='INCOMPLETE'
    try:
        async with user_connection(pool,actor,str(uuid4())) as connection:
            await require_platform_admin(connection)
            checks={r['identity_key']:r['completed_at'] for r in await connection.fetch(PROVIDER_CHECK_SQL,now-timedelta(days=7),now)}
        while True:
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await require_platform_admin(connection)
                products=[dict(row) for row in await connection.fetch(TARGET_SQL,cursor)]
                if not products:break
                observations=await connection.fetch(OBSERVATIONS_SQL,[p['catalogue_id'] for p in products],
                                                     now-timedelta(days=90),now)
            by_product=defaultdict(list)
            for row in observations:by_product[row['catalogue_id']].append(dict(row))
            prepared=[]
            for product in products:
                values=catalogue_values(product,by_product[product['catalogue_id']],now=now,provider_checks=checks)
                report['catalogue_products_checked']+=1
                report['valued_products']+=bool(values);report['missing_exact_evidence']+=not values
                report['value_bases']+=len(values)
                for value in values:
                    result=value['result']
                    prepared.append((product['catalogue_id'],product['identity_digest'],value['basis_key'],value['condition'],
                       value['language'],value['grading_company'],value['grade'],value['seal_status'],result.market_value_minor,
                       result.recommended_retail_minor,result.confidence,result.algorithm_version,value['oldest_sale_at'],
                       value['evidence_checked_at'],now.date(),value['evidence_digest'],value['evidence']))
            async with user_connection(pool,actor,str(uuid4())) as connection:
                await require_platform_admin(connection)
                for args in prepared:
                    report['snapshots_inserted']+=bool(await connection.fetchval(WRITE_SQL,*args))
            cursor=products[-1]['catalogue_id']
        status='COMPLETE'
    finally:
        await receipt(pool,actor,'CATALOGUE_VALUES',status,report,run_id)
    return report
