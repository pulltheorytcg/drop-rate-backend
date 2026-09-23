begin;

-- Acquisition lots are historical cost provenance. The application supports
-- correcting metadata and detaching eligible unsold inventory, but it has no
-- workflow that should physically delete a lot record.
revoke delete on tcg.purchase_lots from tcg_api;

commit;
