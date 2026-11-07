"""Exercise the production catalogue review predicate in disposable PostgreSQL.

Synthetic source identities only; no provider calls or production connections.
"""
import asyncio
import json
from uuid import uuid4

from app.inventory_catalogue_reference import PRODUCTS_SQL
from catalogue_r2_cache_postgres import PGliteConnection

SCHEMA = """
create schema tcg;
create table tcg.catalogue_products(id uuid primary key,product_type text,language text,
 game text,variant text,card_number text,name text,set_name text);
create table tcg.catalogue_product_profiles(catalogue_id uuid,system_code text);
create table tcg.provider_catalogue_mappings(catalogue_id uuid,match_status text,
 verification_basis text,confidence numeric,provider_entity_type text,provider_language text,
 provider_variant_key text,metadata jsonb,source_provider text,provider_id text,system_code text);
create table tcg.market_source_mappings(catalogue_id uuid,source text,match_status text);
create table tcg.reference_sets(provider text,system_code text,language text,set_id text,
 release_date date,name text);
create table tcg.reference_cards(provider text,system_code text,language text,provider_id text,
 set_id text,card_number text,name text);
"""

async def main():
    db = await PGliteConnection.open()
    try:
        await db.execute(SCHEMA)
        ident = uuid4()
        await db.execute("insert into tcg.catalogue_products values($1,'CARD','Japanese','One Piece','Normal','OP01-001','Synthetic','Synthetic')", ident)
        await db.execute("insert into tcg.reference_sets values('Punk Records','ONE_PIECE_CARD_GAME','Japanese','synthetic','2020-01-01','Synthetic')")
        await db.execute("insert into tcg.reference_cards values('Punk Records','ONE_PIECE_CARD_GAME','Japanese','OP01-001','synthetic','OP01-001','Synthetic')")
        fields = ('match_status','verification_basis','confidence','provider_entity_type',
                  'provider_language','provider_variant_key','metadata','source_provider','provider_id','system_code')
        good = ['REVIEW','DETERMINISTIC_EXACT',1,'CARD_PRINTING','Japanese','Normal',
                json.dumps({'media_approval_status':'PENDING','media_asset_id':str(uuid4())}),
                'Punk Records','OP01-001','ONE_PIECE_CARD_GAME']
        async def blocked(values):
            await db.execute('delete from tcg.provider_catalogue_mappings')
            await db.execute('insert into tcg.provider_catalogue_mappings values('+','.join(f'${i}' for i in range(1,12))+')',ident,*values)
            return (await db.fetchrow(PRODUCTS_SQL,[ident]))['blocked']
        assert not await blocked(good), 'Complete media-only review should permit separate reference display'
        for field in ('verification_basis','confidence','provider_entity_type','provider_language','provider_variant_key'):
            values=good.copy();values[fields.index(field)]=None
            assert await blocked(values), f'Missing {field} must block reference display'
        for metadata in (None,{}, {'media_asset_id':str(uuid4())}, {'media_approval_status':None,'media_asset_id':str(uuid4())}, {'media_approval_status':'PENDING'}):
            values=good.copy();values[6]=json.dumps(metadata) if metadata is not None else None
            assert await blocked(values), f'Incomplete media evidence must block: {metadata}'
        for field,value in (('match_status','REJECTED'),('confidence',0.99),('provider_language','English'),('provider_variant_key','Parallel'),('verification_basis','UNVERIFIED')):
            values=good.copy();values[fields.index(field)]=value
            assert await blocked(values), f'Conflicting {field} must block'
        assert not await blocked(good)
        await db.execute("insert into tcg.market_source_mappings values($1,'CARDMARKET','REVIEW')",ident)
        assert (await db.fetchrow(PRODUCTS_SQL,[ident]))['blocked']
        print('PASS: complete media-only reference allowed; null/missing/conflicting identity and media evidence blocked; unresolved market review still blocked')
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
