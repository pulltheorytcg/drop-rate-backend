-- Evaluate the request identity once per query (Postgres InitPlan) instead of
-- invoking current_setting for each candidate row in owner-scoped RLS.
-- The membership predicate, canonical-card visibility, roles, and separate
-- USING / WITH CHECK protections are otherwise unchanged.
-- Do not loosen these policies to relieve database capacity pressure.

alter policy own_action_required_access on tcg.action_required_items
    using (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id = (select nullif(current_setting('tcg.user_id', true), '')::uuid)
              and om.active
        )
    )
    with check (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id = (select nullif(current_setting('tcg.user_id', true), '')::uuid)
              and om.active
        )
    );

alter policy own_enrichment_access on tcg.import_enrichment_items
    using (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id = (select nullif(current_setting('tcg.user_id', true), '')::uuid)
              and om.active
        )
    )
    with check (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id = (select nullif(current_setting('tcg.user_id', true), '')::uuid)
              and om.active
        )
    );

alter policy own_asset_writes on tcg.media_assets
    using (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id = (select nullif(current_setting('tcg.user_id', true), '')::uuid)
              and om.active
        )
    )
    with check (
        owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id = (select nullif(current_setting('tcg.user_id', true), '')::uuid)
              and om.active
        )
    );

alter policy readable_assets on tcg.media_assets
    using (
        scope = 'CANONICAL_CARD'
        or owner_id in (
            select om.owner_id
            from tcg.owner_memberships om
            where om.user_id = (select nullif(current_setting('tcg.user_id', true), '')::uuid)
              and om.active
        )
    );
