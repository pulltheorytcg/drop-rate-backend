from pathlib import Path
p=Path('tests/recommendation_summary_postgres.py');s=p.read_text()
old="        async def setup(c): await c.execute('set role tcg_api')"
new="""        # Channel table projections are synthetic; reference/media migrations above
        # are actual production migrations. No external seller or live order exists.
        await db.execute('''alter table tcg.shopify_inventory_links add column id uuid default gen_random_uuid(),
            add column linked_at timestamptz default now(),add column synced_price_minor bigint;
          create table tcg.ebay_inventory_links(id uuid default gen_random_uuid(),inventory_id uuid,owner_id uuid,state text,
            listed_price_minor bigint,last_verified_at timestamptz,last_error_code text,listing_id text,created_at timestamptz default now());
          create table tcg.ebay_seller_connections(id uuid default gen_random_uuid(),owner_id uuid,status text,marketplace_id text,
            connected_at timestamptz default now(),last_verified_at timestamptz,last_error_code text);
          grant select on tcg.ebay_inventory_links,tcg.ebay_seller_connections to tcg_api;
          alter table tcg.ebay_inventory_links enable row level security;
          create policy own_link on tcg.ebay_inventory_links to tcg_api using(owner_id in(select id from tcg.owners));
          alter table tcg.ebay_seller_connections enable row level security;
          create policy own_connection on tcg.ebay_seller_connections to tcg_api using(owner_id in(select id from tcg.owners));''')
        await db.execute("insert into tcg.ebay_seller_connections(owner_id,status,marketplace_id) values($1,'READY','EBAY_GB')",owners[0])
        await db.execute('''insert into tcg.media_assets(owner_id,catalogue_id,scope,source_type,source_reference,public_source_url,
          rights_status,rights_basis,approval_status,alt_text,created_by_user_id,approved_by_user_id,approved_at,rights_tier,
          source_provider,media_language,media_variant,source_status)
          values($1,$2,'CANONICAL_CARD','OFFICIAL_PROVIDER','Synthetic only','https://www.onepiece-cardgame.com/synthetic-reference.png',
          'VERIFIED','Synthetic permission','APPROVED','Fixture',$3,$3,now(),'STOREFRONT_ALLOWED','Fixture','Japanese','Foil','ACTIVE')''',owners[0],products[0],actors[0])
        async def setup(c): await c.execute('set role tcg_api')"""
assert old in s;s=s.replace(old,new)
s=s.replace("shopify_seller_sync_enabled=False,shopify_publish_enabled=False)","shopify_seller_sync_enabled=False,shopify_publish_enabled=False,shopify_shop_domain='',shopify_client_id='',shopify_client_secret='',ebay_seller_sync_enabled=True,ebay_publish_enabled=True,ebay_shared_store_owner_id=str(owners[0]))")
s=s.replace("with patch.object(auth,'get_settings',return_value=settings),patch.object(owner_inventory,'get_settings',return_value=settings):","with patch.object(auth,'get_settings',return_value=settings),patch.object(owner_inventory,'get_settings',return_value=settings),patch.object(owner_portal_api,'get_settings',return_value=settings):")
old="                    assert sum(x['recommended_retail_minor'] for x in response.json()['items'])==14132\n"
new="""                    assert sum(x['recommended_retail_minor'] for x in response.json()['items'])==14132
                    channel_response=await client.get('/api/v1/owner/channels',params={'limit':100},headers=headers(n))
                    assert channel_response.status_code==200,channel_response.text
                    channel_data=channel_response.json()
                    assert channel_data['total']==(99 if n==0 else 6)
                    channel_item=next(x for x in channel_data['items'] if x['inventory_id']==str(ids[n][0]))
                    assert channel_item['reference_value']==item['reference_value']
                    assert channel_item['market_value_minor']==item['market_value_minor']==1200
                    assert channel_item['recommended_retail_minor']==1200 and channel_item['store_value_minor']==1000+n*500
                    assert channel_item['card_image_url']==item['card_image_url']=='https://www.onepiece-cardgame.com/synthetic-reference.png'
                    assert channel_item['channel_sync_blockers']['EBAY']=='Consignor eBay publishing is not enabled yet'
                    assert not next(x for x in channel_data['channels'] if x['code']=='EBAY')['sync_enabled']
                    unpriced=next((x for x in channel_data['items'] if x['inventory_code'].startswith('INV-UNPRICED')),None)
                    if unpriced:assert unpriced['market_value_minor'] is None and unpriced['recommended_retail_minor'] is None and unpriced['store_value_minor'] is None
                    foreign_search=await client.get('/api/v1/owner/channels',params={'search':f'INV-SYN-{1-n}-'},headers=headers(n))
                    assert foreign_search.status_code==200 and foreign_search.json()['items']==[]
                assert (await client.get('/api/v1/owner/channels')).status_code==401
                assert (await client.get('/api/v1/owner/channels',headers=headers(0,True))).status_code==401
"""
assert old in s;s=s.replace(old,new)
s=s.replace("assert (await overview(1))['active_recommended_retail_minor']==14332","assert (await overview(1))['active_recommended_retail_minor']==14332\n                channels=await client.get('/api/v1/owner/channels',headers=headers(1))\n                assert next(x for x in channels.json()['items'] if x['inventory_id']==str(ids[1][0]))['recommended_retail_minor']==1300")
s=s.replace("assert (await client.get('/api/v1/owner/overview',headers=headers(1))).status_code==403","assert (await client.get('/api/v1/owner/overview',headers=headers(1))).status_code==403\n                assert (await client.get('/api/v1/owner/channels',headers=headers(1))).status_code==403")
s=s.replace('list/detail/overview equality','list/detail/overview/channels equality, shared artwork, denied consignor eBay controls');p.write_text(s)
p=Path('tests/test_journey_channel_scope.py');assert not p.exists();p.write_text('''"""One source of truth for the existing eBay publisher scope."""
import pytest
from app.seller_inventory_policy import ebay_listing_scope_blocker

@pytest.mark.parametrize("owner,kind,expected",[
    ("CONSIGNOR","CARD","Consignor eBay publishing is not enabled yet"),
    ("CONSIGNOR","SEALED","Consignor eBay publishing is not enabled yet"),
    ("FOUNDER","SEALED","eBay v1 only supports individual physical cards"),
    ("FOUNDER","COLLECTION","eBay v1 only supports individual physical cards"),
    ("FOUNDER","CARD",None),
])
def test_unchanged_channel_scope(owner,kind,expected):
    assert ebay_listing_scope_blocker(owner,kind)==expected
''')
p=Path('BUILD_STATUS.md');s=p.read_text();i=s.index('\n');s=s[:i+1]+'''
## 12 October 2026 — Existing journey bug-fix QA (release verification in PR)

- Reproduce/fix late-account request replay and response/profile races in both hubs; preserve same-account token refresh and backend authorization.
- Fix stuck reopened imports, stale commit/resume/search completions and session-expiry cleanup without resetting real batches or changing idempotency.
- Use shared exact-profile artwork/market/recommendation reads in Channels as well as inventory; reflect unchanged eBay scope rather than displaying unsupported sync controls.
- Restore untouched retail suggestions after condition round trips; preserve manually chosen prices and collection-first intent.
- Add actual-script Chromium/WebKit race regressions, extend restricted PostgreSQL/signed test HTTP channel consistency checks, run existing Business and shipping/pooling safety suites. No production data/price/ownership/publication writes.
- See `docs/JOURNEY_REGRESSION_QA.md`. Full real-phone/scanner/checkout and signed-in production acceptance are NOT claimed by this pass. Release status requires exact-head CI and Railway/served-source verification recorded in the PR.

'''+s[i+1:];p.write_text(s)
