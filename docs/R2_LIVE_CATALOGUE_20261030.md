# Live catalogue delivery from R2

## 30 October value-sort repair

Generation 121595 uploaded and independently read back 161 parts covering
69,546 card references, 1,456 sets, 3,893 sealed references, 2,055 canonical
products and 2,055 product profiles. Production games, sets, browse, search,
books, sealed and owner checks match; the last value-sort query times out.

Value sorting now uses the already-derived R2 catalogue entries in compact
column arrays. It retains the whole candidate population until PostgreSQL has
applied current prices, identity restrictions, ownership, filters and ordering.
The existing canonical price function is evaluated in the same authorised
snapshot before planner settings for the large array join. Its transient
results are never persisted to shared R2 objects. Both ascending and descending
sorts are compared with the original queries for two owners in native SQL CI.

The full local PGlite suite currently stops on its pre-existing C-collation
game-label difference versus the native production locale. Native PostgreSQL 17
is the release gate; a separate local 70,000-card value-sort fixture checks the
new reader. No production-publication success is claimed before live readback.

The full shared catalogue has a versioned R2 delivery path: games and sets,
card searches, ownership filters, value sorts, watchlists, sealed products and
comic/manga catalogue entries. The existing exact-set input cache remains a
fallback during rollout.

## Storage and authority

The R2 publication contains explicit display/identity columns from
`reference_cards`, `reference_sets`, `reference_sealed_products`,
`catalogue_products` and `catalogue_product_profiles`. It includes book catalogue
identities. Additional book printing/cover validation remains a bounded live
overlay. Reference image URLs are metadata; copying them does not mirror image
bytes or confer storefront approval.

Railway reads the immutable private objects, verifies their SHA-256 and retains
one bounded process copy. It binds this content into the existing catalogue SQL.
Supabase continues to apply current prices, identity mappings, ownership,
inventory, media permissions and book-validation rules. Price expiry still
changes with the clock. No owner response, physical-copy details, Store Prices,
secrets, arbitrary attributes or approval decisions enter the shared objects.

Importers still write the source tables. No source rows or indexes are removed,
so this release does **not** claim to reduce Supabase disk usage. Removing those
copies requires a separate importer/search/recognition migration and verified
restore plan. Existing archival, source permissions, provider budgets and
Shopify automation are unchanged.

## Complete and current publications

Migration `20261030002930_live_catalogue_r2_publication.sql` creates a single
private publication record and statement triggers on the five shared sources.
A source write increments its generation in the same transaction; rollback
rolls the increment back too. The trigger can only invalidate this record and
is not directly executable by application/public roles. Price or ownership
changes need no rebuild because those decisions stay live.

The existing maintenance worker takes an advisory lock, reads a repeatable-read
source snapshot, and writes at most 300 immutable 500-row parts / 64 MB raw.
It verifies each uploaded object, downloads all parts, checks complete counts,
unique identities and closed schemas, then compares eight original/R2-backed
query shapes. It publishes with a compare-and-set only while the source
generation is unchanged. A partial upload, mismatch, corruption or concurrent
source change cannot become the active catalogue.

Every customer request reads the small authorized publication record. A
generation mismatch immediately falls back to current SQL. A cold process
loads R2 in the background with at most four bounded reads concurrently;
requests remain available during loading. Query errors roll back a savepoint
before the ordinary SQL fallback in the same authenticated snapshot.

## Rollout and backout

Both `TCG_R2_LIVE_CATALOGUE_BUILD_ENABLED` and
`TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED` default false.

1. Pass backend and native PostgreSQL 17 CI and apply the matching migration.
2. Enable build on the existing API worker and observe `PUBLISHED`, complete
   committed counts, actual R2 readback and eight matching query results.
3. Review query timings, then enable delivery and verify the deployed API.
4. Disable the old exact-set warmer only after complete publication succeeds.

Backout: set the new delivery flag false to restore ordinary SQL immediately
after configuration rollout; set build false to stop publications. Keep source
tables and immutable objects. The new flags do not change archive/media flags.

## Validation

The local PGlite PostgreSQL 18.6 contract passes two-owner SQL parity across
search/filter/sort, games/sets, sealed and book entries; current price changes;
generation invalidation and rollback; private-column exclusion; nonmember and
ordinary-owner restrictions; failed upload; concurrent source changes; and
unchanged inventory. Unit tests cover corrupt/incomplete manifests, bounds,
private-column rejection, cold-loading races and savepoint fallback.

Native PostgreSQL 17 CI and production receipts are recorded separately after
they complete. A configured schedule or successful deployment is not evidence
that the catalogue was published or served from R2.

The first release head `d3d623d92c787dff02a3928bb0eb586dafec7088` passed
all nine GitHub workflows, including both original and whole-catalogue native
PostgreSQL 17 contracts. All 8,417 local backend tests passed (18 optional SQL
tests skipped). The additive production migration was applied at 00:29 UK
on 30 October. Its canonical filename now matches the recorded Supabase
version `20261030002930`. Readback confirms forced RLS, five source triggers,
generation 1 and no published manifest yet. Security advisories are unchanged.
Delivery remains off pending verified production publication.

The first build-only production deployment reached SUCCESS, but publication
validation hit the existing 15-second SQL limit. The full-size JSON rowsets were
estimated at 100 rows, selecting quadratic nested loops. A 70,000-card disposable
fixture reproduced the timeout. R2 statements now discourage nested loops and
disable JIT inside a savepoint, restoring both settings before any other SQL;
failure rolls them back. Ordinary queries and server timeouts stay unchanged.
The regression fixture includes 4,000 sealed products, 2,000 canonical products
and 50,000 live prices, and compares all eight query shapes with the original SQL.
Extraction, independent R2 readback and each parity case now have separate logs.
Delivery stays disabled until the corrected production publication passes.

The subsequent production attempt verified all 161 R2 parts but the JSONB-backed
games query still exceeded the SQL limit. The final query transport uses compact
column arrays with explicit SQL casts and statement-scoped hash-join preference;
it avoids whole-catalogue JSONB decoding and repeated merge-sort spills. The
publication format and closed projections are unchanged. A read-only production
plan using the same column-array shape and current data completed in 2.71 seconds
(including source extraction); the comparable merge-join plan took 7.31 seconds.
The full-size regression now includes realistic image/source URL widths and
checks restoration of all three planner settings on success and failure.


## Market data and complete reference artwork (30 October)

Price caches now have a separate private R2 publication: reference market
quotes, catalogue guide values, sealed values, and current asking snapshots.
The four source caches currently contain 91,054 rows (overlapping identities;
this is not a count of independently priced products). Closed projections retain
source evidence, GBP amounts and original checked/expiry timestamps. No stock,
owner, asking-for-sale price or payment data is exported. Immutable parts are
uploaded and independently read back before a generation-checked publication.

The existing catalogue maintenance worker republishes after provider jobs.
Statement triggers immediately invalidate changed inputs; no-op updates and
rolled-back changes leave the publication intact. Normal indexed browse pages
can read exact matching price rows from R2, with existing SQL expiry, printing
identity and ownership rules. Cold, missing, invalid or changed publications
use current PostgreSQL. Full-population value sorts and canonical/asking
resolvers retain their existing live SQL decisions.

Feature gates: `TCG_R2_MARKET_BUILD_ENABLED` and
`TCG_R2_MARKET_DELIVERY_ENABLED`, both initially false. This section describes
the implementation, not a claim that production publication has succeeded.

The reference image worker now applies the existing maintenance administrator
on every short source/receipt lease; an unauthenticated lease sees zero source
rows under RLS. The source cache also accepts the existing Naruto archive and
CardTrader Pokémon paths, validated by exact host/path and current source URL.
These remain private reference assets. The current 6,941 records without any
source image cannot be made complete by copying storage. Failed downloads
retain bounded retries and the original display fallback.

Validation includes two-owner SQL parity for complete R2 price inputs, source
expiry and identity checks, incomplete upload and concurrent-update rejection,
all four invalidation triggers, non-admin publication denial, unchanged stock,
and real restricted-role image receipts for the additional hosts.
