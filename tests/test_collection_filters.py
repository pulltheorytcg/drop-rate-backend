"""Meaningful query-contract checks for collection filtering and group ordering."""
import asyncio
from uuid import uuid4

from app.inventory_collection_filters import (
    append_collection_filters, collection_facets, collection_order_sql, collection_state_counts,
)
from app.inventory_display_groups import inventory_group_page


def test_filter_values_are_bound_after_the_owner_scope():
    owner=uuid4();params=[owner];filters=["i.owner_id=$1"]
    malicious="One Piece' OR true --"
    append_collection_filters(filters,params,category="TCG",game=malicious,
        language="Japanese",grading="GRADED",format="CARD",listing_state="READY",prepare_selling=True)
    sql=" and ".join(filters)
    assert filters[0]=="i.owner_id=$1"
    assert malicious not in sql
    assert params==[owner,"TCG",malicious,"Japanese","APPROVED"]
    assert "p.game=$3" in sql and "i.status=$5" in sql
    assert "i.status in ('DRAFT','INSPECTION','APPROVED')" in sql
    assert "sl.owner_id=i.owner_id" in sql and "not sl.test_mode" in sql
    assert "not exists(select 1 from tcg.shopify_inventory_links" in sql
    assert "certificate_number" in sql
    assert "cs.system_kind='SPORTS_CARD'" in sql


def test_personal_and_published_are_separate_filters():
    filters=[];params=[]
    append_collection_filters(filters,params,listing_state="PERSONAL",grading="RAW",format="SEALED")
    assert "i.sale_intent='PERSONAL_COLLECTION'" in " ".join(filters)
    assert "p.product_type in ('SEALED','COLLECTION')" in filters
    assert any(value.startswith("not (") for value in filters)
    filters=[]
    append_collection_filters(filters,[],listing_state="LISTED")
    assert "sl.sync_state='PUBLISHED'" in filters[0]
    assert "sl.owner_id=i.owner_id" in filters[0]
    filters=[]
    append_collection_filters(filters,[],listing_state="ALL_FOR_SALE")
    assert "i.sale_intent='FOR_SALE'" in filters[0] and "'RESERVED'" in filters[0]
    assert "'SOLD'" not in filters[0] and "'WITHDRAWN'" not in filters[0]


def test_ordering_is_allowlisted_and_does_not_sort_unenriched_prices():
    for grouped in [False,True]:
        default=collection_order_sql("updated",grouped=grouped)
        assert collection_order_sql("name; drop table tcg.inventory_items",grouped=grouped)==default
        assert collection_order_sql("value_desc",grouped=grouped)==default
        assert "market_value" not in collection_order_sql("newest",grouped=grouped)
    assert collection_order_sql("name",grouped=True)=="sort_name,first_code"
    assert collection_order_sql("oldest")=="i.created_at,i.inventory_code"


def test_group_sort_precedes_pagination_and_keeps_full_group_ids():
    class Connection:
        async def fetchrow(self,sql,*params):
            self.sql,self.params=sql,params
            return {"total":4,"copy_total":62,"ids":["first-copy","second-copy"]}
    conn=Connection();owner=uuid4()
    result=asyncio.run(inventory_group_page(conn,"i.owner_id=$1 and p.game=$2",[owner,"One Piece"],1,2,sort="name"))
    assert result==(4,62,["first-copy","second-copy"])
    assert conn.params==(owner,"One Piece",1,2)
    assert "where i.owner_id=$1 and p.game=$2" in conn.sql
    assert "order by sort_name,first_code" in conn.sql
    assert conn.sql.index("order by sort_name,first_code")<conn.sql.index("limit $3 offset $4")
    assert "array(select unnest(ids) from page)" in conn.sql
    assert "named_sealed.attributes->>'display_name_en'" in conn.sql
    assert "named_sealed.catalogue_id=p.id" in conn.sql


def test_facets_come_from_all_owned_records_not_the_current_page():
    class Connection:
        async def fetch(self,sql,*params):
            self.sql,self.params=sql,params
            return [{"category":"TCG","game":"Pokemon","language":"Japanese"},
                    {"category":"TCG","game":"One Piece","language":"English"},
                    {"category":"MANGA","game":"Manga","language":"English"}]
    conn=Connection();owner=uuid4();result=asyncio.run(collection_facets(conn,owner))
    assert conn.params==(owner,)
    assert "where i.owner_id=$1" in conn.sql
    assert " limit " not in conn.sql.lower() and " offset " not in conn.sql.lower()
    assert result["games"]==["Manga","One Piece","Pokemon"]
    assert result["languages"]==["English","Japanese"]
    assert result["categories"]==["MANGA","TCG"]


def test_actionable_counts_reuse_sale_intent_and_published_exclusions():
    class Connection:
        async def fetchrow(self,sql,*params):
            self.sql,self.params=sql,params
            return {"personal":3,"for_sale":5,"preparing":1,"review":1,"ready":1,"listed":2}
    conn=Connection();owner=uuid4();result=asyncio.run(collection_state_counts(conn,owner))
    assert conn.params==(owner,"DRAFT","INSPECTION","APPROVED")
    assert "where i.owner_id=$1" in conn.sql
    assert "i.sale_intent='FOR_SALE'" in conn.sql and "i.sale_intent='PERSONAL_COLLECTION'" in conn.sql
    assert conn.sql.count("not exists(select 1 from tcg.shopify_inventory_links")==3
    assert result=={"personal":3,"for_sale":5,"preparing":1,"review":1,"ready":1,"listed":2}
