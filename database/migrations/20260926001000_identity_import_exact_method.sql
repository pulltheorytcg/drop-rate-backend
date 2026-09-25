-- Allow deterministic original-import identity verification without mislabelling it as physical review.
-- IMPORT_EXACT is only used when name, set, collector number, variant/finish
-- and an explicit EN/JP language marker all match the canonical identity.

alter table tcg.identity_verification_events
  drop constraint if exists identity_verification_events_verification_method_check;

alter table tcg.identity_verification_events
  add constraint identity_verification_events_verification_method_check
  check (
    verification_method in (
      'PHYSICAL_REVIEW',
      'IMPORT_EXACT',
      'CORRECTION',
      'SYSTEM_INVALIDATION'
    )
  );
