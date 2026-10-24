# Pricing recovery — 24 October 2026

The founder requested the remaining catalogue-wide pricing fixes. The read-only
baseline is 40,548 of 67,065 physical card references with a supported dated GBP
value or a labelled guide (60.46%). Source-access gaps are not code errors:
Naruto and much of Japanese One Piece/Fusion still lack a suitable connected
source. Promo and alternate-art ambiguity remains fail-closed.

## Changes

- Fusion starter numbers in the existing Cardmarket export use two digits.
  The numbered recovery matcher now accepts those exact FS numbers and decodes
  HTML text once when comparing names. It does not pad collector numbers,
  infer variants, select the cheapest quote, or ignore competing products.
  The original reference identity and current Cardmarket/ECB evidence stay in
  each quote; these mixed-language guides cannot price physical stock.
- Existing Pokémon CardTrader bridges are revalidated even when a detailed
  quote temporarily covers their card. A skipped request is no longer treated
  as evidence that the independent guide vanished. Ambiguity still invalidates
  the guide and provider outages preserve the original dated evidence.
- Failed TCGdex refreshes update only retry metadata on an existing cache row.
  Older quotes survive for the explicitly historical display; they do not
  become current values. First failures create an empty retry entry. Successful
  empty responses still clear unsupported evidence. The concurrency guard
  prevents an older failed request changing a newer completed refresh.
- Reference importer revision becomes 23. The existing weekly cadence and
  strict 400,000,000-byte capacity guard remain unchanged.

## Verification and operations

Regression tests cover exact two-/three-digit numbers, leading-zero mismatches,
parallel/cross-release collisions, HTML names, cache outage/initial failure,
retry backoff, fresh replacement and source identity revalidation. The existing
PostgreSQL CI job tests the real upsert, immutable history, restricted app role,
dated display and delayed-failure race. Deployment requires green CI and a
terminal Railway SUCCESS, followed by health/readback checks.

Before targeted production backfill, archive the existing 35,802 history records
using the established private Drop Rate Drive procedure. Export, typed restore,
full content digest, uploaded package download and SHA-256 must all verify before
the existing guarded archival function can reclaim storage. Neither an archive
schedule nor an export alone is a completed archive.

At this commit, implementation validation and live recovery remain in progress.
Do not interpret candidate replay counts as a committed production backfill.
No owner, stock, Store Price, Shopify listing, source credential or paid plan changes.
