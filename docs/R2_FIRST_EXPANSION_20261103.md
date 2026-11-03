# Direct-to-R2 catalogue expansion — 3 November 2026

## Scope and source of truth

New provider reference catalogues can enter private Cloudflare R2 directly. They
do **not** first pass through `reference_cards`, `reference_sets` or quote tables
in Supabase. Existing Pokémon/One Piece/Dragon Ball/Naruto paths are unchanged.

PostgreSQL remains authoritative for the approved source-generation pointer,
canonical identities selected by people, physical inventory, owners, prices,
orders, fees, settlements and audit. The R2 records are unreviewed reference
facts, not physical ownership, verified printing identity or market values.

Three small private tables hold approved pointers, append-only publication events
and exact on-demand canonical links. One source publication creates no per-card
SQL row. Selecting a reference creates/reuses a minimal stable canonical identity;
adding a physical copy uses the existing owner-bound idempotency receipt engine.

## Storage and retrieval

1. An explicitly approved adapter fetches one bounded public bulk feed outside
   any SQL transaction. It does not fetch on customer search/scans.
2. Closed-schema validation rejects duplicate identities, wrong source scope,
   unexpected personal/price/artwork fields and malformed input. A source cannot
   supply object paths, SQL, credentials or arbitrary downstream URLs.
3. Immutable content-addressed shards are uploaded and read back. The manifest is
   uploaded last and verified too. Partial upload cannot change a live pointer.
4. A cold read reconstructs a bounded, disposable SQLite/FTS index from R2 only.
   A short admin-only compare-and-swap transaction switches the approved pointer
   and records its audit event. Old objects remain available for rollback.
5. Authenticated browsing rechecks the SQL pointer, then queries local indexed
   metadata. Missing/corrupt/cold data returns a clear retryable 503, never a silent
   fallback to nonexistent SQL reference rows or an obsolete approved version.

Bounds: 250,000 records/128 MB raw per partition; 500 records/4 MB per shard;
12 active partitions and 256 MB aggregate source bytes. SQLite+FTS disk is
additional, rebuildable storage—not included in the raw-byte figure. Index
loads are serialized, with an 8 MB SQLite page cache per partition. Requests use a
bounded k-way merge of 100-record source pages; owner predicates precede
pagination. Owner-key filters cap at 10,000; deep browse requires a narrower set.

Only exact canonical links contribute live owner counts. No fuzzy/number-only
price join, unverified zero value, owner change, Shopify publication or image
approval is introduced. Provider IDs remain scoped by provider/system/language.

## Source readiness

| Source | Adapter state | Network activation |
| --- | --- | --- |
| YGOPRODeck / Yu-Gi-Oh! | Metadata-only bulk adapter and tests | Explicit opt-in permitted by documented bulk/local caching guidance |
| LorcanaJSON / Disney Lorcana | Offline normalization and tests | Blocked pending dataset/data-use permission review |
| Scryfall / Magic | Offline normalization and tests | Blocked pending current terms review and larger bounded/streaming bulk support |
| Riftcodex / Riftbound | Descriptor only | Deferred pending bulk/data-use permission review |
| Sports cards / Funko | Storage shape can hold metadata; no feed enabled | Requires a permitted source and exact structured printing/product identity |

Provider access approval is not an artwork licence. All imported images and market
values are intentionally absent in this first path. YGOPRODeck edition, finish
and alternative-art assignment are not inferred from a card's artwork array.
Unknown/review-required identities are never automatically approved for sale.

Primary source evidence: https://ygoprodeck.com/api-guide/ (reviewed 3 November
2026) asks consumers to download/store data locally and documents a two-day cache.
The worker checks at most once per two days and does not retry denied requests.

New systems appear in game→set→product browsing. The legacy global search is not
presented as a complete merge of all new systems; response scope identifies the
separate R2 systems, and the UI offers a query-preserving game-search button.
Metadata-only details explicitly state the artwork/value/printing-review limits.
Explicit saved-key lookups are bounded and include R2 keys.
Metadata imports alone do not constitute new recognition-model support.

## Activation and rollback

Both reader and importer default OFF. After the tracked migration and green
CI/native PostgreSQL security tests:

* `TCG_R2_FIRST_CATALOGUE_ENABLED=true` enables authenticated indexed reads.
* `TCG_R2_FIRST_IMPORT_SOURCES=ygoprodeck` opts only that reviewed source into the
  existing API runtime's separate background worker. Existing configured private
  R2 credentials and the verified maintenance administrator are reused normally.
* Verify terminal Railway SUCCESS, readiness, importer readback receipt, registry
  digest/count, zero SQL reference-table bulk growth, and authenticated UI reads.

To pause imports, clear the source list. To disable the new browse path, turn its
reader flag off; old paths remain. To roll back a published dataset, load an
earlier approved manifest from R2, verify it fully, and call the same publication
function with the current expected generation. It creates a new audit event;
no old source objects, canonical links or physical copies are deleted. Revoked
sources are not silently reactivated by the worker.

## Verification gates

Unit tests cover closed schemas, hash/scope binding, duplicate IDs, invalid URLs,
failed/partial uploads, corrupt/missing objects, source permissions, idempotent
publication, stale-generation conflict, cold reconstruction and bounded search.
Real disposable PostgreSQL tests cover forced RLS/grants, owner/admin separation,
atomic audit, canonical links, stable key hashes and private bookmarks.
Full backend, dashboard and existing R2 regressions remain required. Production
data import and real-device acceptance are separate from synthetic test success.

## Earlier space recovery (separate from this expansion)

On 3 November 2026, the two already-backed-up quote tables were physically
compacted—not emptied. Database size fell from 422,349,971 to 399,101,075 bytes
(23,248,896 bytes recovered). Full-field row digests and counts remained unchanged:

* `reference_market_prices`: 59,693 rows;
  `e1b8f848b89dd1cb3eb54ab8a1f65cab2e4f7971b53d24ae89f4cbc27772ef52`.
* `reference_catalogue_prices`: 27,676 rows;
  `53e8f03574e9db02fe49216734e778f00cf3abd21792b5054198e17d37f47a62`.

This did not offload/delete SQL price source rows, and does not create large
ongoing SQL headroom. At 22:27 UTC the database measured 399,961,235 bytes; ordinary
growth continues. A later pre-release read at 22:39 UTC measured 484,846,739 bytes;
the two quote row counts remained unchanged but their physical relations had grown
again. No R2-first production import had run. The existing maintenance guard is
checked at the start of a pass, not before every stage; compaction is not a durable
replacement for the separately reviewed old-quote offload. New R2 catalogues avoid bulk reference-table growth, but their
small registry, real selected inventory and audit still consume PostgreSQL space.
