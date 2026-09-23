begin;

-- These columns were added after the original column-level inventory UPDATE
-- grant. The backend needs them for deterministic workflows, while ownership,
-- canonical identity and import provenance remain non-editable.
grant update (
    seal_status,
    storage_location_id,
    purchase_lot_id,
    market_value_minor,
    recommended_retail_minor,
    pricing_updated_at,
    latest_pricing_snapshot_id
) on tcg.inventory_items to tcg_api;

commit;
