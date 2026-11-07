"""Bounded read-only diagnosis of the existing OP-17 single-pack providers.

No database, secret output, mapping approval or price writes. Run only as an
explicit operator diagnostic; it is not an ingestion schedule.
"""
import asyncio
import json

from app.cardtrader_client import CardTraderClient
from app.cardtrader_recognition import discover_one_piece_cardtrader_sealed_candidates
from app.ebay_sealed_pricing import _fetch_uk_sold
from app.settings import get_settings
from scripts.bootstrap_cardtrader_sealed_market import _observation, _eligible_marketplace_rows


async def sold():
    try:
        result=await _fetch_uk_sold(dict(set_code='OP-17',language='Japanese',sealed_product_type='BOOSTER_PACK'))
        return {'source':'EBAY_SOLD', **result}
    except Exception as exc:
        return {'source':'EBAY_SOLD','error_type':type(exc).__name__,'status_code':getattr(exc,'status_code',None)}


async def cardtrader():
    try:
        client=CardTraderClient(api_token=get_settings().cardtrader_api_token)
        observation=_observation(product_code='OP-17',set_name="World's Strongest Warriors [OP-17]",language='Japanese')
        candidates=await discover_one_piece_cardtrader_sealed_candidates(observation,client,max_expansions=2,max_candidates=12)
        matches=[]
        for candidate in candidates:
            if candidate.get('sealed_product_type')!='BOOSTER_PACK':
                continue
            rows=await client.list_marketplace_products(blueprint_id=int(candidate['provider_id']),language='jp')
            eligible=_eligible_marketplace_rows(rows)
            matches.append({'provider_id':candidate['provider_id'],'name':candidate.get('name'),
                'rows':len(rows),'eligible':len(eligible),'sample_fields':sorted(rows[0]) if rows else []})
        return {'source':'CARDTRADER','candidates':matches}
    except Exception as exc:
        return {'source':'CARDTRADER','error_type':type(exc).__name__,'status_code':getattr(exc,'status_code',None)}


async def run():
    for result in await asyncio.gather(sold(),cardtrader()):
        print('SELLER_MARKET_DIAGNOSTIC '+json.dumps(result,default=str),flush=True)


if __name__=='__main__':
    try:
        asyncio.run(asyncio.wait_for(run(),90))
    except TimeoutError:
        print('SELLER_MARKET_DIAGNOSTIC {"status":"TIMEOUT","persisted":false}',flush=True)
