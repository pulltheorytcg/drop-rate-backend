# R2-first catalogue expansion — 4 November 2026

## What is being released

This extends the existing Yu-Gi-Oh! reference-catalogue path to reviewed English
Lorcana and Magic metadata, a limited sports checklist, and four individually
reviewed Funko product references. It is catalogue discovery, not artwork,
pricing, physical inventory, scanner-model support or automatic Shopify listing.

Provider snapshots enter private Cloudflare R2 directly. PostgreSQL remains the
authority for the approved manifest pointer, publication audit, selected canonical
identities, physical inventory and ownership, prices, orders and settlements.
There is no bulk insert into SQL reference-card, set or market tables and no new
database migration. The existing source registry and owner-bound intake flows are
reused. Existing Pokémon, One Piece, Dragon Ball and Naruto feeds are unchanged.

## Reviewed sources and measured scope

These are successful local source/codec dry-runs, **not production publication
receipts**. Live availability must be checked after the gated release below.

| Source | Reviewed scope | Verified records | Permission and limitations |
| --- | --- | ---: | --- |
| Lorcast | English Lorcana source printings, 26 sets | 3,505 | Documented public ingestion and local caching. Free factual lookup, attribution, no resale of the dataset/API. No artwork licence is inferred. |
| MTGJSON | English paper printings and explicit finishes | 153,662 | MIT-licensed content; full notice is served in the app. Source back-face rows and non-paper records are excluded. Tokens and other languages are not included. |
| Card Collector Capital | Three selected Bowman checklists | 1,722 | CC BY 4.0 compilation/annotations, with source IDs, evidence URLs, pages and review dates retained. Not all sports cards or all parallel variants. |
| Reviewed figure starter | Four individually checked Funko factual references | 4 | Manually curated facts only. No Funko API or automated website extraction. Existing two Good Smile references remain separate and available. Not a full Funko catalogue. |

The sports source includes 592 rows from 2026 Bowman Baseball, 508 from 2026
Bowman Chrome and 622 from 2025 Bowman Draft. A checklist section is not evidence
of a physical card's parallel or packaging language. These remain blank for the
seller to confirm. Figure edition, release year and language are not guessed.

Primary source review:

- Lorcast: <https://lorcast.com/docs/api>, <https://lorcast.com/docs/api/sets>,
  <https://lorcast.com/docs/api/cards>.
- MTGJSON content licence: <https://mtgjson.com/license/>; fixed source
  <https://mtgjson.com/api/v5/AllPrintings.json.xz> and its `.sha256` companion.
- Card Collector Capital: <https://cardcollectorcapital.com/data>; fixed version
  <https://cardcollectorcapital.com/data/bowman-checklist-lookup-2026-10-27.json>.
- The four figure facts and individually reviewed manufacturer evidence URLs are
  in `backend/data/r2_figure_starter_20261104.json`. The importer reads this
  bounded repository file only and never requests a Funko webpage.
- Public credit, scope and the full MIT notice are in
  `/assets/catalogue-source-notices.txt`, linked from reference details and intake.

The `METADATA_ACCESS_DOCUMENTED` descriptor for `reviewed_figures` refers to the
reviewed internal factual starter, not permission for a Funko bulk feed. It must
not be reused to activate scraping or a third-party database.

Riftbound remains disabled: Riot's documented developer policy requires an
app-specific API approval or written permission, neither verified for Drop Rate.
The alternative Riftcodex, Scryfall and LorcanaJSON downloads are not activated.
Restricted competing-marketplace feeds and the old HobbyDB-derived Funko dump
are not used. Adding an approved source later requires a separate review.

## Identity, UI and failure behaviour

- English is the Lorcana/Magic source-printing partition. Figures use the
  `Not applicable` registry partition but do not present that as a physical-item
  language. Sports checklist text does not fill physical language.
- Source identity remains provider/system/language scoped. Magic uses source UUID
  plus explicit finish, not name/number matching. No duplicate physical copies
  are created by importing a catalogue.
- Existing canonical Sports/Figures products and sets are combined with their
  small R2 starters. The union is bounded to 5,000 candidate rows and requires
  narrower filters beyond that limit; it never silently truncates the result.
- Canonical-only saved keys keep their existing SQL route. Owner predicates,
  visible-page enrichment, slab corroboration and human-review flags remain.
- Partial Sports/Figures references open the existing editable structured intake
  form. Known facts can be prefilled; unknown edition/parallel/language, condition,
  cost and ownership are not inferred. Partial references cannot enter automatic
  TCG canonical materialization.
- Missing artwork and market values stay absent, not zero or a fabricated guide.
  Metadata does not approve physical identity, source media or a Shopify listing.
- Failed or incomplete imports leave the previous approved generation unchanged.
  A provider failure is reported separately and does not prevent independent
  approved sources from being attempted. Denials are not retried in that pass.
- R2 reads fail closed on cold, missing or corrupt snapshots. Owned-only
  Sports/Figures product reads do not require the starter snapshot. Ordinary
  combined browsing requires a prewarmed verified snapshot; do not announce it
  live solely because a publication row exists.

## Resource and integrity bounds

Existing codec limits are unchanged: 250,000 records / 128,000,000 raw bytes per
partition, 500 records per shard, 4 MB per shard, 12 active partitions and 256 MB
aggregate raw source bytes. SQLite search indexes are disposable local caches.

The Magic feed is streamed to private temporary storage, verified against its
provider SHA-256 before parsing, then incrementally decoded off the event loop.
Limits cover compressed and expanded bytes, XZ dictionary memory, JSON tokens,
depth/events, source rows, per-set spool space, output memory and total time.
Only reviewed structured fields can enter identity extraction; literal JSON keys
cannot impersonate nested parser paths. Cancellation stops and joins parsing
before temporary files close.

Measured Magic build `5.3.0+20261103`:

- Compressed bytes: 99,472,096.
- Source SHA-256: `b1089a8cafe68403d58cc2a30325b83fc90156a62427bb9dbde7a6b59cfdf4db`.
- Normalized raw bytes, including licence credit and stored keys: 93,973,955.
- R2-ready shards: 308; complete parse plus preparation: approximately 89 seconds.
- Peak RSS for that dry-run: approximately 265 MiB. Runtime download, upload,
  verification and cache reconstruction are additional work, not included in
  that timing. Live resource and readiness checks remain required.

Lorcast's dry-run source digest is
`b003068c14f0eab01102f0f1be55e4455165b1352307ec91270ea837e20fdbab`.
The fixed sports source digest is
`4103e7999a4c513b48c056b7b1a36a4194a09de6a5b028c370a416fb6ce902f4`.
Lorcast uses a complete set list and bounded sequential requests with a 250 ms
gap. Approved new sources refresh at most weekly; the existing Yu-Gi-Oh! two-day
cache policy is unchanged. Neither search nor scanning triggers a source fetch.

During a rolling deployment, a replacement importer can encounter the old
instance's session lock. That exact lock-busy result makes no provider request
and returns its pool connection before retrying the lock after 30 seconds.
Prewarming is skipped during contention. Once a pass runs, successful, current,
disabled and failed source results all restore the normal two-day worker sleep;
permission, database and prewarm errors do not get the contention retry. Task
cancellation exits without another attempt. This avoids an interrupted initial
import sleeping for two days, without changing the per-source refresh windows or
publication checks. It is not a persisted cross-deployment provider-error cooldown.

## Release gates

1. Run source, codec, importer, owner-isolation and UI regressions, the full
   backend/dashboard suites, and required GitHub CI/native PostgreSQL checks.
2. Merge only the checked commit. Confirm Railway SUCCESS for the resulting
   production commit and verify readiness before enabling new sources.
3. Preserve the existing reader flag and explicitly set the importer source list
   to `ygoprodeck,lorcast,cardcollectorcapital,reviewed_figures,mtgjson` on the
   existing production API service. Use its configured private R2 credentials
   and authorised maintenance actor normally; do not extract secrets.
4. Each source must complete immutable object upload, hash readback, manifest
   verification, cold indexed search and the audited compare-and-swap pointer
   transaction. Observe an individual success receipt; no partial success counts.
5. Check SQL registry count/digest/raw bytes, no bulk reference-table growth,
   prewarm logs, authenticated games/sets/products and existing inventory access.
   Confirm the source notices asset and missing-art/value labels. Real-device
   acceptance is distinct from mocked DOM tests.

Removing a source from `TCG_R2_FIRST_IMPORT_SOURCES` **only pauses its refresh**;
it does not remove its already approved catalogue. To revoke a source, use the
existing administrator-only `publish_verified(..., active=False)` path with the
currently expected generation and fully verified snapshot. To roll back content,
verify the prior immutable manifest and republish it with the expected current
generation. Both use the normal audit and conflict protection. The worker does
not silently reactivate a deactivated source. Do not delete R2 generations,
canonical links, owner inventory or prices to roll back this release.

If the code must be reverted after new publications exist, first pause refresh
and deactivate those newly introduced partitions using the current compatible
code, then deploy the prior checked version. Do not leave an older runtime
trying to validate source partitions whose descriptors it does not know.

## Storage cleanup is separate

This change avoids large new SQL reference datasets. It does not move live
ownership/financial tables into R2 or repair the separate legacy bulk-import
capacity guard. The 4 November read-only baseline was 430,214,291 database bytes,
above the existing 400,000,000-byte bulk-refresh guard. No guard override,
historical-price deletion, compaction or paid capacity change is part of this
release. Those operations require their own verified backup and safety work.
