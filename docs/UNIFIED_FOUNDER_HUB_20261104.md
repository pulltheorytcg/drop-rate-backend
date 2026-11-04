# Shared Seller Hub and founder Settings

## Problem and behaviour

Founders were routed to a separately maintained dashboard. The daily collector
and seller experience diverged from the current Seller Hub. A verified founder
now opens the same `/owner` HTML, scripts, collection, scan, catalogue, selling,
profile and payout journeys as an ordinary seller. There is no second copy of
those screens to drift.

Settings contains a Founders dashboard. It reuses the existing read-only Business
API and account/stock/activity views, with eight clear links to the existing
privileged controls. `/founders` holds those existing forms; their handlers and
approval policies are unchanged. Shared primary navigation returns to the Hub;
Back returns to Settings > Founders dashboard. Legacy `/app#accounts`, intake,
inventory and review bookmarks are mapped deliberately.

## Access and data

`current_access_context` continues to verify active membership, exactly one
membership and the database founder roster. The personal owner API guard now
accepts rostered business founders as well as ordinary owners. Endpoint owner-ID
filters are retained. No admin permission is granted to sellers. Company APIs
still require the existing founder dependency. UI hiding is only presentation.

The profile function accepts either the current OWNER membership or a rostered
PLATFORM_ADMIN and requires one active membership. It cannot accept a target
owner ID; display name and username remain the only editable fields. The
existing audit and unique-username checks remain; direct table access and public
execution are not granted. The migration changes a function, not account data.

The dashboard fetches company records only when opened. It clears data on
logout, account change and denied access; pending responses cannot repopulate a
cleared view. Errors preserve a retry action and do not silently mutate records.

## Verification

- Existing Python backend, owner API, founder Business and role tests.
- Entire `tests/ui` DOM interaction suite, including `unified-founders.cjs`:
  identical five destinations, Settings-only entry, all eight operational links,
  ordinary-owner denial, safe text rendering, revocation and late-response reset.
- `node tests/shared_founder_profile_pglite.mjs`: executes actual roster and
  profile migrations against disposable PostgreSQL. Three founders and one seller
  can edit only themselves; generic admins and revoked founders are denied;
  duplicate usernames and direct cross-owner writes fail; exact audit recorded.
- GitHub CI runs the same new PostgreSQL and UI checks. Production deployment must
  reach SUCCESS for the merged commit. A signed-in phone/desktop visual smoke is
  recorded separately from DOM tests; no test purchase or inventory write is
  performed as part of this release.

## Deployment and rollback

The tracked `20261104103233_shared_founder_profile.sql` migration was applied and
read back before the app release. The filename matches the actual production
migration-history version. No new security-advisor finding appeared.
Verify migration history and the function definition/permissions. Merge only
after CI passes and confirm Railway deploys the merged commit.

Revert this PR and redeploy its predecessor if personal collection, permission
or navigation checks regress. The backward-compatible profile function can stay
in place during an app rollback; to fully revert it, restore the function body
from `20260930230500_owner_profile_settings.sql` with a new tracked migration.
No data reversal, ownership rewrite, new service or storefront change is needed.

## Current release evidence

- Local Python regression: 9,433 passed, 25 optional skipped.
- Full dashboard interaction suite passed, including shared-founder and existing
  scanner, collection, selling, finance, account and session failure tests.
- Actual PostgreSQL migration/roster/profile/audit regression passed.
- Production profile definition and execution privileges verified; migration
  history version `20261104103233` matches the committed filename.
- Public-repository publication and deployment are explicitly approved. GitHub CI
  and exact-commit Railway SUCCESS remain release gates. The available browser
  is signed out, so signed-in visual acceptance has not been claimed.
