# Reference price recovery: offline archive classification

This stage reuses the existing `reference_quote_source_backup` manifest and row contract. It classifies a locally downloaded, content-addressed R2 backup before planning fresh evidence ingestion. It does not refresh prices, approve sources, write D1/Supabase/R2, reclaim storage, change UI or call a provider. The 400 MB safeguard remains unchanged.

## Run against an existing verified download

Use Python 3.12 and the manifest digest from the independently recorded storage receipt. Do not derive the trusted digest from an unverified manifest merely to satisfy the argument.

```sh
PYTHONPATH=backend python tools/reference_price_recovery_audit.py \
  --manifest /private/path/source.manifest.json \
  --archive /private/path/source.ndjson.gz \
  --manifest-sha256 TRUSTED_MANIFEST_SHA256 \
  --as-of 2026-11-07T20:00:00+00:00
```

Output is aggregate JSON on stdout, only after complete verification. Keep actual source downloads and business coverage results outside the public repository. Identifiers, quote payloads and unknown source labels are not emitted. Record the explicit evaluation clock with each result; rerunning the same inputs and clock is deterministic.

## Integrity and meaning

The tool verifies manifest bytes, compressed bytes/size, bounded decompression, exact typed row schema, unique ordered identities, row count, uncompressed digest and row-content digest. It supports the existing full `reference_market_prices` archive only. Corruption, duplicate identities, malformed timestamps or changed shape fail without a partial result.

Freshness and evidence are separate dimensions:

- `EXPIRED`: cache expiry is at or before the evaluation time.
- `UNEXPIRED_CACHE_ONLY`: expiry has not passed; this is not proof of eligible evidence.
- `TIMESTAMP_REVIEW`: a checked, pricing or observation timestamp is in the future.
- `GUIDE_ONLY`: every quote names one of the three existing Cardmarket guide feeds.
- `MISSING_EVIDENCE`: empty quote list.
- `REVIEW_REQUIRED`: all other or mixed source payloads, including claimed sold evidence. This phase cannot verify source entitlement, exact sold identity or publication rights.

Legacy `physical_valuation_eligible` flags and stored monetary amounts never grant Market Value eligibility. All rows remain archive retention candidates and require permitted sold-evidence review before any Market Value promotion. These are overlapping dimensions, not additive unique-record counts. Quote occurrence counts can exceed row counts.

`current_sql_parity=NOT_VERIFIED` is deliberate: authentic historical archive bytes do not establish parity with today's SQL. `typed_restore_this_run=false` distinguishes byte/row verification from the existing PostgreSQL temporary-table restoration workflow. This tool cannot authorise deletion or prove live rollback.

## Validation and next gate

85 targeted local tests pass across recovery classification, existing quote backup, R2 market cache and sold-evidence archive. Tests cover digest corruption, incorrect bounds, duplicate/out-of-order identities, malformed/future timestamps, exact expiry boundary, mixed/unknown quotes, reproducibility and no partial CLI output. Simulated fixtures are separate from real archive readback evidence.

Next: use the existing authorised export path to reconcile a current snapshot, retaining its independent receipt and typed restoration proof. Prioritise owned-stock exact identities through the existing permission boundary. Validate permitted fresh sold evidence and immutable R2 receipts before calculating in FastAPI and staging a D1 projection. The existing market schema needs read-time freshness and approved-generation gates before any production reader is enabled. Cutover, deletion and plan changes require approval.

Rollback for this offline stage is simply to stop using the tool or revert its isolated commit; no production routing or data changed. Keep PRs #991/#992 and the separate MTGJSON repair independent.
