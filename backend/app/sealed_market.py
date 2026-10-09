"""Daily public Cardmarket packaging guides, joined by explicit provider IDs.

These aggregates span languages/conditions. They are reference context, never
exact physical-stock prices, identity approval or a seller's asking price.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

import httpx

from .db import user_connection
from .fx import EcbHistoricalFxProvider
from .reference_market import MAX_AGE, _minor, _time
from .reference_sealed import category_type

SOURCE = 'CARDMARKET_BULK'
REVISION = 2
# Confirmed public first-party game exports. Unsupported games stay explicit.
GAMES = {'POKEMON_TCG': (6, 'Pokémon'), 'ONE_PIECE_CARD_GAME': (18, 'One Piece')}
BASE = 'https://downloads.s3.cardmarket.com/productCatalog/'
WRITE_SQL = '''insert into tcg.reference_sealed_market_prices
 (provider,system_code,language,provider_id,quotes,market_value_minor,market_value_high_minor,
  pricing_updated_at,checked_at,expires_at)
 values($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10)
 on conflict(provider,system_code,language,provider_id) do update set
 quotes=excluded.quotes,market_value_minor=excluded.market_value_minor,
 market_value_high_minor=excluded.market_value_high_minor,pricing_updated_at=excluded.pricing_updated_at,
 checked_at=excluded.checked_at,expires_at=excluded.expires_at
 where tcg.reference_sealed_market_prices.checked_at<=excluded.checked_at'''


async def download(client, path, *, rows_key, now):
    async with client.stream('GET', BASE+path) as response:
        response.raise_for_status()
        body=bytearray()
        async for part in response.aiter_bytes():
            body.extend(part)
            if len(body)>32_000_000:raise ValueError('Bulk guide exceeds limit')
    payload=json.loads(body)
    stamp=_time(payload['createdAt'])
    if not now-timedelta(days=3)<=stamp<=now+timedelta(hours=1):
        raise ValueError('Bulk guide is not current')
    rows=payload[rows_key]
    if not isinstance(rows,list) or not 1<=len(rows)<=200000:
        raise ValueError('Invalid bulk guide')
    indexed={}
    for row in rows:
        product_id=str(row.get('idProduct',''))
        if not product_id.isdigit() or int(product_id)<=0 or product_id in indexed:
            raise ValueError('Invalid or duplicate bulk product ID')
        indexed[product_id]=row
    return indexed,stamp


async def quote_for(reference, products, prices, observed, fx, *, game_name):
    product_id=str((reference.get('evidence') or {}).get('cardmarket_product_id') or '')
    product=products.get(product_id);price=prices.get(product_id)
    if not product or not price:return None
    # These are the exact labels in Cardmarket's public non-singles export;
    # CardTrader calls a Pokémon display a booster box.
    packaging_type={('Pokémon','Pokémon Display'):'BOOSTER_BOX',
                    ('One Piece','One Piece Preconstructed Decks'):'STARTER_DECK'}.get(
        (game_name,product.get('categoryName')),category_type(product.get('categoryName'), {'name':game_name}))
    if (str(price.get('idCategory'))!=str(product.get('idCategory')) or packaging_type!=reference['product_type']):
        return None
    try:
        original=_minor(price.get('trend'))
        conversion=await fx.quote(base_currency='EUR',quote_currency='GBP',at=observed)
        gbp=int((Decimal(original)*conversion.rate).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        if gbp<=0:return None
    except (ValueError,TypeError,InvalidOperation):return None
    return {'source':SOURCE,'product_id':product_id,'source_field':'trend','original_currency':'EUR',
            'original_minor':original,'price_gbp_minor':gbp,'observed_at':observed.isoformat(),
            'finish':'Sealed product guide','valuation_role':'MIXED_LANGUAGE_REFERENCE',
            'physical_language_confirmed':False,'condition_specific':False,
            'fx_rate_to_gbp':str(conversion.rate),'fx_source':conversion.source,
            'fx_effective_at':conversion.effective_at.isoformat(),'fx_retrieved_at':conversion.retrieved_at.isoformat()}


async def refresh_sealed_prices(pool, actor):
    from .catalogue_maintenance import receipt
    now=datetime.now(timezone.utc)
    run_id=await receipt(pool,actor,'SEALED_REFERENCE_PRICES','RUNNING',{})
    report={'checked':0,'priced':0,'unmatched':0,'provider_failures':0,'sources':{},'importer_revision':REVISION}
    status='INCOMPLETE'
    fx=EcbHistoricalFxProvider(timeout_seconds=10)
    try:
        async with httpx.AsyncClient(timeout=45,follow_redirects=False) as client:
            for system,(game_id,game_name) in GAMES.items():
                try:
                    products_result,prices_result=await asyncio.gather(
                        download(client,f'productList/products_nonsingles_{game_id}.json',rows_key='products',now=now),
                        download(client,f'priceGuide/price_guide_{game_id}.json',rows_key='priceGuides',now=now))
                    products,_=products_result;prices,observed=prices_result
                    async with user_connection(pool,actor,str(uuid4())) as connection:
                        rows=await connection.fetch('''select r.* from tcg.reference_sealed_products r
                          join tcg.reference_sets s using(provider,system_code,language,set_id)
                          where r.provider='CardTrader' and r.system_code=$1
                            and (s.release_date is null or s.release_date<=current_date)''',system)
                    # Compute outside transactions; one FX download is reused.
                    values=[]
                    for record in rows:
                        reference=dict(record)
                        quote=await quote_for(reference,products,prices,observed,fx,game_name=game_name)
                        value=quote['price_gbp_minor'] if quote else None
                        values.append((reference['provider'],system,reference['language'],reference['provider_id'],
                                       [quote] if quote else [],value,value,observed if quote else None,
                                       now,now+timedelta(days=1)))
                    for offset in range(0,len(values),100):
                        async with user_connection(pool,actor,str(uuid4())) as connection:
                            await connection.executemany(WRITE_SQL,values[offset:offset+100])
                    priced=sum(v[5] is not None for v in values)
                    report['checked']+=len(values);report['priced']+=priced;report['unmatched']+=len(values)-priced
                    report['sources'][system]={'observed_at':observed.isoformat(),'checked':len(values),'priced':priced}
                except (httpx.HTTPError,ValueError,KeyError,TypeError,RuntimeError) as exc:
                    # Do not erase a cached guide on a provider/FX outage.
                    report['provider_failures']+=1
                    report['sources'][system]={'reason':type(exc).__name__}
        status='COMPLETE' if not report['provider_failures'] else 'INCOMPLETE'
    except asyncio.CancelledError:
        report['reason']='INTERRUPTED';raise
    finally:
        await receipt(pool,actor,'SEALED_REFERENCE_PRICES',status,report,run_id)
    return report
