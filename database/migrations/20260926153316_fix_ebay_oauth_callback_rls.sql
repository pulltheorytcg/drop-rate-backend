drop policy ebay_seller_connections_api_read on tcg.ebay_seller_connections;
drop policy ebay_seller_connections_api_insert on tcg.ebay_seller_connections;
drop policy ebay_seller_connections_api_update on tcg.ebay_seller_connections;

create policy ebay_seller_connections_api_read
    on tcg.ebay_seller_connections for select to tcg_api
    using (true);
create policy ebay_seller_connections_api_insert
    on tcg.ebay_seller_connections for insert to tcg_api
    with check (true);
create policy ebay_seller_connections_api_update
    on tcg.ebay_seller_connections for update to tcg_api
    using (true) with check (true);

revoke all on table tcg.ebay_seller_connections from anon, authenticated;
grant select,insert,update on table tcg.ebay_seller_connections to tcg_api;
revoke delete on table tcg.ebay_seller_connections from tcg_api;
