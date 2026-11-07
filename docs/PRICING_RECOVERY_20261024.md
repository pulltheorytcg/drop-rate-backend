# Pricing recovery - 24 October 2026

The founder requested the remaining catalogue-wide pricing fixes. The baseline
was 40,548 of 67,065 physical references with supported dated GBP values or
labelled guides. Recovery is live through PR #699, merge commit
7b22901e0b90ad4d377a00048bbae6d9c30a0159.

## Fixes

- The numbered Fusion matcher now accepts exact two-digit FS starter numbers
  and decodes HTML text once when comparing names. It does not pad collector
  numbers, infer variants or discard unpriced competing products.
- Existing Pokemon CardTrader bridges are revalidated even when a detailed
  quote temporarily covers the same card. Ambiguity still invalidates the
  guide; failed source requests preserve original evidence and dates.
- Failed TCGdex refreshes update retry metadata only on existing cache rows.
  Complete old evidence remains available to the dated display, never as a
  current value. Old-revision failures respect their five-minute cooldown
  without marking old evidence newly validated. Successful empty responses
  still clear unsupported evidence; delayed failures cannot change newer rows.
- Importer revision 23 keeps the weekly cadence and 400,000,000-byte guard.

## Verified production result

A replay against current Cardmarket game-13 exports recovered 80 previously
unpriced, unambiguous references (56 starter cards and 24 in other releases).
Every quote was independently replayed with the saved source files and ECB FX
publication. The data transaction checked admin context, capacity, exact
reference identity/rarity, release eligibility, source dates, quote ranges and
EUR-to-GBP arithmetic. It required exactly 80 writes or rolled back, retained
all new immutable history, and verified the complete inventory fingerprint.
No Store Prices, owners, stock or Shopify listings changed.

The source observation is 2026-10-24 00:46:07 UTC. ECB EUR-to-GBP is 0.83728,
effective 2026-10-23 14:00 UTC. These are explicitly labelled mixed-language
Cardmarket guides, not exact UK sold prices or physical-copy valuations.

- Physical-card coverage: 40,628 / 67,065 (60.58%).
- English Fusion coverage: 1,319 / 4,365 (30.22%).
- Newly priced reference records: 80; matching new history: 80.
- Coverage receipt: 66b0b505-498d-4267-96bf-181300289e09.
- Exact ASCII payload SHA-256:
  88279f9859f4e657bf8b96e7667391754b6f399f2f8258f61126b65b2c49f8dc.
- Guarded SQL SHA-256:
  5bffe2b45a1a9468d8c58aa82e48c115b0ec134cc58ebb2be55a989f6adc7018.

The private recovery package retains source snapshots, replay scripts, original
identities and dated quotes. Unicode was transported through JSON escapes to
preserve the exact provider title; production identities were not rewritten.

## Capacity recovery

All 35,802 prior history rows were exported and restored into disposable
PostgreSQL with complete original-row and quote-digest checks. The private
Drop Rate Drive archive was uploaded, fully downloaded and checked by SHA-256
and ZIP CRC before the existing full-content-guarded helper reclaimed storage.
This is a verified archive, separate from the daily backlog notification.

- Archive ID: drop-rate-reference-history-20261024-172650.
- Package size: 5,799,678 bytes.
- Package SHA-256:
  723926d2d684b10544bfbcca020a5c1411166dc302ded72ccb126b94d45d592f.
- Source content root:
  dbf8c4ec5422781179eef43dd11788ab0128ee8ccc70ebb8302dcd9bdb54946b.
- Reclaimed: 56,606,720 bytes.
- Database after archive and 80-price recovery: 339,471,507 bytes, writable.
- Complete inventory and all three current-price-cache fingerprints were
  identical across archival. The later targeted price backfill preserved
  inventory and created its own 80 history observations.

## Release verification and limitations

All five PR workflows passed, including native PostgreSQL and browser/reference
checks. All local Python tests and 6,307 Railway predeploy tests passed.
Deployment 0b08188e-f4dd-4597-80f6-0510a6773123 reached SUCCESS at
2026-10-24 17:34:07 UTC with the exact merge commit. Public readiness returned
HTTP 200/database connected; Railway reported one running replica and no
failures or active warnings.

The 95% overall target remains unmet: 26,437 physical references remain missing.
Naruto and much of Japanese One Piece/Fusion require a suitable source;
ambiguous promotions/alternate arts need exact printing mappings. Sampled
Pokemon gaps genuinely lack detailed provider pricing. Root-level aggregates
are not silently accepted as exact finish evidence. No paid feed was added.
The capacity guard still needs ongoing verified archival; this recovery does
not prove unattended archival is operating.

Code rollback is a normal revert of PR #699. Do not discard archived history,
remove the capacity guard, relabel old evidence as current or remove legitimate
new quote history to reverse a release.
