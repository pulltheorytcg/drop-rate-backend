"""Extend disposable seller PostgreSQL suite: collecting vs selling remain separate."""
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from fastapi import HTTPException
from app import owner_inventory as api

async def verify_collection_selling(db,pool,request,user,access,foreign):
    root=Path(__file__).resolve().parents[1]
    for name in ('202609230016_harden_inventory_physical_state.sql','202609240005_inventory_physical_state_separation.sql'):
        await db.execute((root/'database/migrations'/name).read_text())
    card,raw,other,slab,approved=[uuid4() for _ in range(5)]
    await db.execute("insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language) values($1,'listing-fixture','CARD','One Piece','Fixture card','Fixture set','OP99-001','','C','Japanese')",card)
    await db.execute("insert into tcg.catalogue_product_profiles(catalogue_id,system_code,identity_status) values($1,'ONE_PIECE_CARD_GAME','VERIFIED')",card)
    await db.executemany("insert into tcg.inventory_items(id,owner_id,catalogue_id,inventory_code,status,sale_intent,language,grading_company,grade) values($1,$2,$3,$4,$5,'PERSONAL_COLLECTION','Japanese',$6,$7)",[(raw,access['owner_id'],card,'INV-LIST-RAW','DRAFT',None,None),(other,foreign,card,'INV-LIST-OTHER','DRAFT',None,None),(slab,access['owner_id'],card,'INV-LIST-SLAB','DRAFT','PSA','10'),(approved,access['owner_id'],card,'INV-LIST-APPROVED','APPROVED',None,None)])
    before=await db.fetch('select * from tcg.inventory_items where id=any($1::uuid[]) order by id',[raw,other,slab,approved])
    with patch.object(api,'request_shopify_sync',return_value=False):
        for identifier,payload,status in ((raw,api.ListingRequest(version=1,store_price_minor=1000),422),(raw,api.ListingRequest(version=1,store_price_minor=1000,condition='Mint-ish'),422),(other,api.ListingRequest(version=1,store_price_minor=1000,condition='Near Mint'),404),(slab,api.ListingRequest(version=1,store_price_minor=1000,condition='Near Mint'),422),(approved,api.ListingRequest(version=1,store_price_minor=1000,condition='Near Mint'),409)):
            try:await api.approval_request(identifier,payload,request,user,access);raise AssertionError('Invalid/foreign/stale condition request accepted')
            except HTTPException as e:assert e.status_code==status,str(e)
        assert await db.fetch('select * from tcg.inventory_items where id=any($1::uuid[]) order by id',[raw,other,slab,approved])==before
        # Merely recording a price must not change intent, condition or approval.
        await api.selling_price(raw,api.SellingPrice(version=1,store_price_minor=1200),request,user,access)
        row=await db.fetchrow('select * from tcg.inventory_items where id=$1',raw)
        assert row['sale_intent']=='PERSONAL_COLLECTION' and row['status']=='DRAFT' and row['condition'] is None and row['version']==2
        result=await api.approval_request(raw,api.ListingRequest(version=2,store_price_minor=1200,condition='Near Mint'),request,user,access)
        row=await db.fetchrow('select * from tcg.inventory_items where id=$1',raw)
        assert row['condition']=='Near Mint' and row['store_price_minor']==1200 and row['version']==3
        assert row['status']=='INSPECTION' and row['sale_intent']=='FOR_SALE' and not row['identity_confirmed']
        assert result['item']['status']=='INSPECTION','Selling request was falsely reported published'
        try:await api.approval_request(raw,api.ListingRequest(version=2,store_price_minor=1000,condition='Damaged'),request,user,access);raise AssertionError('Stale update accepted')
        except HTTPException as e:assert e.status_code==409
        assert await db.fetchrow('select * from tcg.inventory_items where id=$1',raw)==row
    assert await db.fetchrow('select * from tcg.inventory_items where id=$1',other)==next(r for r in before if r['id']==other)
    assert await db.fetchrow('select * from tcg.inventory_items where id=$1',slab)==next(r for r in before if r['id']==slab)
    print('PASS: restricted-role explicit selling request records condition/price/intent atomically, keeps review, rejects foreign/slab/approved/stale conflicts; price-only save stays personal. No real publication.')
