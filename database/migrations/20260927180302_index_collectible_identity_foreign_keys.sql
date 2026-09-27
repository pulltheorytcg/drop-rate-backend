begin;

create index if not exists catalogue_taxonomy_assignment_taxonomy_fk_idx
    on tcg.catalogue_taxonomy_assignments(
        system_code,scope_kind,dimension_code,value_code
    );

create index if not exists catalogue_taxonomy_assignment_verified_by_user_idx
    on tcg.catalogue_taxonomy_assignments(verified_by_user_id)
    where verified_by_user_id is not null;

create index if not exists provider_catalogue_mapping_system_idx
    on tcg.provider_catalogue_mappings(system_code);

create index if not exists provider_catalogue_mapping_verified_by_user_idx
    on tcg.provider_catalogue_mappings(verified_by_user_id)
    where verified_by_user_id is not null;

commit;
