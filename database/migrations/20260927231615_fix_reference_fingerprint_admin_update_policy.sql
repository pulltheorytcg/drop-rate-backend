begin;
drop policy api_update on tcg.recognition_reference_fingerprints;
create policy api_update on tcg.recognition_reference_fingerprints
    for update to tcg_api
    using (tcg.is_platform_admin())
    with check (tcg.is_platform_admin());
commit;
