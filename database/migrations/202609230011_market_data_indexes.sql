begin;

create index inventory_latest_pricing_snapshot_idx
    on tcg.inventory_items(latest_pricing_snapshot_id)
    where latest_pricing_snapshot_id is not null;

create index pricing_snapshots_catalogue_time_idx
    on tcg.pricing_snapshots(catalogue_id, calculated_at desc);

commit;
