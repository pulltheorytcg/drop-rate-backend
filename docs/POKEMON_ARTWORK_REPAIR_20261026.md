# TCGdex missing-reference artwork repair

The catalogue contains Pokémon records whose exact TCGdex asset exists but whose
API response has no image field. This repair targets only reviewed provider
reports, verifies actual bytes and fills blank reference-image URLs. It does not
approve canonical media, create inventory, change prices or copy images into R2.

## Source basis

- [Asset URL and image-display documentation](https://tcgdex.dev/assets):
  the provider documents language/series/set/local-ID paths and WebP/PNG qualities.
- [Provider FAQ](https://tcgdex.dev/faq): no API key is required; bulk users should
  be considerate. Missing images may genuinely be unavailable.
- [Japanese manifest omissions, issue 2477](https://github.com/tcgdex/cards-database/issues/2477):
  fixed affected sets and independently observed assets.
- [English promo manifest omissions, issue 2362](https://github.com/tcgdex/cards-database/issues/2362).
- [Misnumbered Japanese M1S assets, issue 2395](https://github.com/tcgdex/cards-database/issues/2395):
  the entire set is excluded from this repair.

These are reference URLs on the existing provider origin, consistent with its
documented display interface. Software licensing does not grant artwork rights.
This operation grants no broader redistribution, marketing, R2 caching or Shopify
media approval permission. Existing provider attribution and source links remain.

## Safety contract

The affected-set allowlist is fixed in code. The existing database row must match
provider, game, language, set, exact zero-padded local ID, provider ID, card number
and API source URL. No fuzzy name matching, language substitution or set aliasing
is used. Future releases and existing image URLs are excluded.

At most four requests run concurrently, with spacing between batches. The probe
has a 120-second default wall-clock budget (configurable from 1 to 240 seconds)
and at most three image requests per selected row. In-flight requests are cancelled
when the time budget expires; verified earlier results can be applied with an
explicit PARTIAL_TIME_BUDGET report and durable INCOMPLETE receipt. Each GET
must return a decoded card-shaped raster within byte/pixel bounds; redirects,
HTML and malformed responses fail. After a 404 only, the same card's documented
low WebP or high PNG sibling is tried. Duplicate image bytes across candidates
are rejected to avoid installing a generic placeholder.

Updates recheck identity, source/local ID, release eligibility and blank old URL.
Only image_url and image_reference provenance change. The provenance records the
original source, actual returned URL, SHA-256, dimensions, byte count, timestamp,
actor and run ID. The existing sparse-sync contract preserves the repair while
the same exact identity still lacks provider imagery. A changed identity cannot
inherit the previous image.

## Run and inspect

Dry-run is the default. In the authenticated API runtime:

```sh
PYTHONPATH=backend python backend/scripts/repair_pokemon_artwork.py --from-settings --limit 20
PYTHONPATH=backend python backend/scripts/repair_pokemon_artwork.py --from-settings --limit 5000
```

For deployment pre-checks, prefer --limit 500 --max-seconds 120. The report returns
next_cursor when work remains. Continue using --after LANGUAGE SET_ID PROVIDER_ID
with those exact three values, so persistent early failures do not block later
rows. Keep the same input cursor when switching a reviewed dry-run batch to apply;
advance only after that batch is applied or deliberately skipped.

Only after reviewing dry-run evidence, append --apply to perform the conditional
writes. The configured maintenance actor must be an existing platform admin.
Do not print or export service credentials.

A read-only CI/network probe can use a bounded JSON array of the existing public
reference rows, without database credentials:

```sh
PYTHONPATH=backend python backend/scripts/repair_pokemon_artwork.py --rows-json snapshot.json --report-file report.json
```

That mode refuses --apply and database identity options. Verified rows in its
report are evidence only; they cannot be applied through this input path.

Inspect requested, candidates, verified, failed, skipped, updated and per-set
counts. Successful apply runs persist a reference_sync_runs receipt with source
tcgdex_artwork_repair. HTTP 404 gaps remain visibly missing; they are not replaced
with other printings or counted as successful artwork. An interrupted run records
its partial result and leaves existing verified updates auditable and idempotent.

## Verification

Unit checks cover malformed identity, missing source evidence, URL mutation,
redirect refusal, HTML, MIME/format mismatch, size bounds, wrong dimensions,
duplicate placeholders, format fallback, permission checks and dry-run behavior.
The disposable PostgreSQL 17 job checks exact conditional writes, concurrent
identity edits, release-date changes, retries, rollback, sparse-sync preservation
and unchanged inventory/current prices. Production counts and receipts must be
read back separately before claiming any artwork recovered.
