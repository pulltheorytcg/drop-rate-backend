# Verified R2 reference-input delivery

This release adds a private R2-backed input path for normal exact-set card
browsing. Supabase remains authoritative. No catalogue/current-price rows are
removed, and this cache does not reclaim database space.

## Supported requests and privacy

An authenticated request must identify one exact provider, system, language and
set; use an ordinary name/date/card-number sort; request all ownership states;
and contain no search, watchlist or slab-suggestion parameters. The browser's
normal set navigation already supplies this shape. Card-only and default mixed
card/sealed pages are supported; the sealed branch always stays live SQL.

The private snapshot contains only explicit reference-card, set, detailed-price
and catalogue-guide input columns. It excludes owner/user IDs, inventory,
acquisition costs, Store Prices, canonical mapping decisions, media approvals,
signed URLs and account responses. Canonical links and valuation, shared alias
prices, historical guides, ownership and media/rights checks all remain live.

Broad search, owned/not-owned filters, watchlists, family browsing, value sorts,
books and slab suggestions use their existing database path. No UI change or
new provider request is involved.

## Integrity and freshness

PostgreSQL produces canonical `jsonb::text` for the exact shared input scope and
computes SHA-256 over those bytes. Every cache hit obtains a fresh bounded
source fingerprint through the user's normal authorized database transaction.
Source changes, including artwork/quote edits with unchanged timestamps,
therefore select a new immutable object identity.

Objects use `catalogue-reference-inputs/<raw-sha256>.json.gz` in the existing
private bucket. Uploads use deterministic gzip and actual compressed-byte
readback verification. Downloads have separate short network timeouts, bounded
decompression and full raw SHA-256 validation. This path never signs arbitrary
object URLs or widens the existing approved-media signer.

These are raw inputs, not frozen display decisions. The original SQL still
evaluates current dates, seven-day evidence age, price expiry, identity and
source matching. A seven-day transition can remove a current price without any
write or rebuild. The original observation date is never replaced by the cache
creation time.

The source check and live overlays use a read-only repeatable-read transaction.
Fingerprint/cache-query errors roll back a savepoint before ordinary SQL
fallback. Missing, stale, oversized, corrupt or unavailable objects do not make
the normal catalogue unavailable. A bounded process cache retains at most
64 objects / 16 MB and still requires a fresh database fingerprint per request.
At most four R2 reads can run concurrently per process. A three-second request
timeout retains its capacity slot until the underlying read thread finishes;
requests exceeding that capacity immediately keep the live SQL path.

## Building and rollout

- `TCG_R2_CATALOGUE_CACHE_BUILD_ENABLED` defaults false. The existing API
  maintenance worker warms up to four batches of five exact sets per pass,
  after normal pricing/source-archive work. It uses the existing administrator
  actor for read-only source access and performs no SQL writes. Oversized sets
  are skipped; a cursor advances through the reference directory.
- `TCG_R2_CATALOGUE_CACHE_DELIVERY_ENABLED` defaults false. Enable only after
  native PostgreSQL 17 tests, normal deployment and actual R2 readback/query
  parity evidence pass.
- A bounded production probe for the first successful scope deliberately reads
  actual R2 bytes, rechecks the source, and compares at most twenty original and
  cached query rows in one authorized snapshot. Logs contain only counts,
  equality/source-change status and timings; no private row data.

Limits: 1,000 cards per exact set, 4 MB raw, 2 MB compressed. Unsupported scopes
keep normal SQL. Warming is gradual; deployment is not a claim that every set
already has a current cached object. Cache errors and mismatches remain visible
in the `CATALOGUE_R2_REFERENCE_CACHE_*`, `CATALOGUE_R2_QUERY_FALLBACK` and
`CATALOGUE_R2_PARITY_FAILED` runtime events.

## Verification

The focused tests cover private storage bounds/corruption, source mutations,
scope guards, auth, memory limits, fallback and worker receipt validation.
The real SQL suite executes original and cached queries, existing valuation
functions and restricted-role RLS for two owners. It covers sorting/pagination,
mixed sealed overlays, live ownership/membership/rights/mappings/shared-price
changes, absent/corrupt objects, savepoint recovery and clock-only expiry.

Local PGlite 0.5.9 identifies its engine as PostgreSQL 18.6. The dedicated CI job
runs native PostgreSQL 17.6, matching production's major version. Both results
must be recorded separately. Current release/deployment evidence will be added
after verification; these implementation notes alone are not a live receipt.
