# Catalogue search and media latency — 3 November 2026

## Production observation (2 November desktop acceptance test)

- Authenticated `/api/v1/catalogue-browser/products` requests: 11 sampled, median **5,689 ms**, maximum **32,561 ms**, including one cancelled request (499).
- Authenticated `/api/v1/inventory/{inventory_id}/image`: 19 sampled, 11 returned 404. A 404 can mean **no exact eligible source exists**, not permission to substitute a different printing.
- Runtime logs showed `CATALOGUE_R2_INDEXED_BROWSE_FALLBACK type=ValueError`, repeated `CATALOGUE_R2_FILTERED_VALUE_FALLBACK type=ValueError`, and a `CATALOGUE_R2_LIVE_QUERY_FALLBACK type=QueryCanceledError`. They demonstrate expensive fallbacks, but do **not** mean every indexed query failed.
- Current canonical reference-card metadata: 69,697 rows, of which 66,209 have a nonempty `image_url` (3,488 absent). Reference-sealed metadata: 3,893 rows, 3,889 with an image URL. An URL is not itself evidence that its remote object is currently reachable or rights-cleared for storefront publication.

## This change

1. Add one **strictly verified** R2 in-process shortlist for an ASCII, nonnumeric, whitespace-normalised text search within a selected game/family (e.g. Charizard in Pokémon; Luffy in One Piece), newest sort, and offset at most 512. The original SQL query is reconstructed and compared byte-for-byte with the requested query before any pruning. The shortlist keeps **all** matching printings (up to 2,000) and passes them to PostgreSQL **before** price enrichment, ranking, owner checks, and pagination. Numeric/card-number identity searches, additional filters, ownership queries, non-newest sorts, query-template changes, or large candidate sets retain the proven SQL fallback.
2. In Seller/Founder inventory artwork UI, invoke the authenticated assigned-media proxy **only when** the API says the item has an assigned eligible media URL. For reference-only items, use the already-verified exact reference URL or reference endpoint. For items without verified artwork, show unavailability without triggering a doomed `/inventory/{id}/image` request. This never changes the publication/media approval gates.

## Architecture and safety

- PostgreSQL/Supabase remains canonical for inventory identity, ownership, pricing, media approval and RLS; the R2 snapshot is an immutable shared-content hint for selecting candidates.
- No new provider, scraper, schema, SQL mutation, pricing overwrite, RLS change or storefront publication.
- Failure mode: R2 cold/unavailable, malformed query shape, non-ASCII or numeric search, more than 2,000 candidate printings, or unsupported sort/filter → existing live SQL path. This preserves correctness, although those requests can remain slow.
- No guessed substitution for ambiguous/absent artwork; an approved physical-copy listing photo is still required where policy demands it.
- Do not treat this targeted fix as resolving the separate full-population **value-sort** fallback or absent reference images. Those need their own bounded evidence-driven work.

## Verification and rollout gate

- Unit tests cover exact variant/parallel preservation, cross-game suppression, offset-before-SQL protection, 2,000-candidate fail-closed limit, numeric/owned/filter/sort rejection, and live price/RLS SQL retention.
- Mocked DOM tests cover reference-only image routing, no-source zero-request behavior, and assigned-media proxy recovery after a direct URL error.
- Local tests: `PYTHONPATH=backend pytest -q` on six non-database security/R2/static modules and `npm test` for the entire `tests/ui` suite. Database-backed browser tests require the isolated PostgreSQL fixture in CI and cannot complete locally without that fixture.
- Before release, require green backend CI and R2 parity where available; after release compare filtered game-name search latency, 404 volume and error rates on the same live API. Keep ability to revert to SQL fallback by disabling the extended R2 browse flag if the result differs.

## Out of scope

Accurate market-value coverage, graded/sealed recognition, comics listing approval, new catalogue providers, and a full rewrite of the browse query. Those are independent workstreams under existing product milestones.
