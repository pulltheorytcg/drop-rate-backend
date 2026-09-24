-- A canonical Drop Rate catalogue product may have only one trusted identity
-- per provider. REVIEW/REJECTED candidates may coexist until a human decides.

create unique index if not exists market_source_mapping_verified_catalogue_source_key
on tcg.market_source_mappings(catalogue_id, source)
where match_status = 'VERIFIED';
