"""Execute the application's cost rollups on mixed known/unknown consignment costs."""
import ast
from pathlib import Path
from uuid import uuid4


async def verify_cost_rollups(db, owner, inventory):
    await db.execute('''
      alter table tcg.order_items add column order_id uuid, add column sold_at timestamptz default now();
      create table tcg.orders(id uuid,source text,source_reference text,order_number text,status text,currency text,placed_at timestamptz default now());
      create table tcg.refund_events(order_item_id uuid,return_to_stock bool);
      create table tcg.order_item_reconciliations(order_item_id uuid,fees_reconciled_at timestamptz,shipping_cost_reconciled_at timestamptz);
      create table tcg.financial_ledger_entries(owner_id uuid,order_id uuid,order_item_id uuid,entry_type text,amount_minor bigint,funds_status text);
    ''')
    order = uuid4()
    await db.execute("insert into tcg.orders(id,source,currency) values($1,'SHOPIFY','GBP')", order)
    await db.execute('update tcg.order_items set order_id=$1 where owner_id=$2',order,owner)
    await db.execute('insert into tcg.order_items(owner_id,inventory_id,order_id,cost_basis_minor) values($1,$2,$3,800)',owner,inventory,order)
    await db.execute("insert into tcg.financial_ledger_entries(owner_id,order_id,entry_type,amount_minor) values($1,$2,'SALE_REVENUE',2000)",owner,order)
    tree=ast.parse((Path(__file__).parents[1]/'backend/app/finance.py').read_text())
    queries={}
    for function in tree.body:
        if not isinstance(function,ast.AsyncFunctionDef):continue
        for node in ast.walk(function):
            if not isinstance(node,ast.Constant) or not isinstance(node.value,str):continue
            sql=node.value
            if function.name=='finance_summary' and 'count(*) filter(where oi.cost_basis_minor is null)' in sql:queries['cost']=sql
            if function.name=='finance_sales_analytics' and 'with scoped_items' in sql:
                queries['series' if 'date_trunc' in sql else 'analytics']=sql
            if function.name=='finance_settlements' and 'with item_rollup' in sql:queries['settlements']=sql
    assert set(queries)=={'cost','analytics','series','settlements'}
    async def rollups(expected):
        assert await db.fetchval(queries['cost'],owner)==expected
        assert (await db.fetchrow(queries['analytics'],owner,None,None))['cost_of_goods_minor']==expected
        assert (await db.fetchrow(queries['settlements'],owner,50,0))['effective_cogs_minor']==expected
        series=await db.fetch(queries['series'],owner,None,None,'day')
        assert len(series)==1 and series[0]['profit_minor']==(None if expected is None else 2000-expected)
    await rollups(None)
    assert await db.fetchval(queries['cost'],uuid4())==0
    await db.execute('insert into tcg.refund_events select id,true from tcg.order_items where owner_id=$1 and cost_basis_minor is null',owner)
    await rollups(800)
