begin;
create index recognition_reference_fingerprints_created_by_idx
    on tcg.recognition_reference_fingerprints(created_by_user_id);
commit;
