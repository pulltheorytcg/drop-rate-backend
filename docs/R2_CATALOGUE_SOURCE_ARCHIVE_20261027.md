# Private archival of recovered book source evidence

`catalogue_source_archives.archive_reviewed_openlibrary_sources()` copies the
fixed 27 October 2026 recovery checkpoint to private R2 through the existing
verified `exports` uploader. This is source evidence storage. Supabase remains
the live catalogue, ownership and price authority.

The 14 inputs total **6,228,589 bytes**. Their committed paths, SHA-256 hashes and
sizes are pinned in the module to main commit
`51a32083990202b9d6c91f5424e03f3459d5b427`. They include the full 2,420-record
factual selection, the 2,404 novel records, the reviewed 1,495-record initial
cohort, selection/import-plan receipts, original subjects, the unchanged
57-record hold registry, production import receipts, the six conservative
deferred findings, the original dump manifest and recovery integrity evidence.

The manifest labels the 1,495 imports as **historical receipt evidence**, dated
at the recorded completion time. The other **909 records remain held pending
review**. Earlier dry-run flags inside immutable input receipts are preserved;
their later production receipts are archived alongside them. Archiving does not
replay imports, verify physical printings, add values, change holds or approve
artwork. The complete 12.6 GB dump and cover bytes are not copied.

The licensing reference remains
<https://openlibrary.org/developers/licensing>. This is not a blanket CC0 claim,
and storing these factual records grants no new publication or cover rights.

## Operation

From the repository root, offline validation needs no credentials:

```bash
PYTHONPATH=backend python backend/scripts/archive_catalogue_source_snapshot.py
```

The same fixed operation with `--apply` uses the existing enabled private object
store configuration. There is no arbitrary path, URL, provider or file-list CLI
option. The async function accepts an injected storage client and test source
root for offline verification; maintenance jobs can use its returned report.

All inputs and cohort bindings are checked before any upload. Deterministic
gzip copies retain the exact original bytes; the manifest records both source
and gzip hashes. Every object is uploaded through `put_verified_file()` and its
actual remote bytes are read back. Only after every data object succeeds is the
manifest uploaded and verified. A `BYTES_VERIFIED` result contains its private
object receipt and all file receipts; it does not claim a database restore.

An interrupted run may leave a verified prefix of content-addressed objects.
Retrying the unchanged checkpoint verifies and reuses those objects. A changed
input, corrupt existing object or failed readback aborts without a completed
manifest receipt. No objects are overwritten or deleted by this worker.

## Verification

`tests/test_catalogue_source_archives.py` exercises real storage verification
against an in-memory S3 client: exact byte round trips, unchanged retries,
interrupted retries, altered/truncated/oversized/missing/symlink inputs,
corrupted remote bytes, mismatched receipts and preserved deferred status.
The existing recovered-snapshot integrity tests continue to verify the import
normalization and historical receipt details independently.

## Maintenance integration

`TCG_CATALOGUE_SOURCE_ARCHIVE_ENABLED=true` enables this fixed evidence copy in
the existing API catalogue maintenance worker. It runs after the normal pricing
pass, at most daily after success and at most hourly after failure. It makes no
provider requests and adds no database job type or schema. The Shopify worker
does not run it. The default is disabled until the release and storage readback
are verified.

`CATALOGUE_R2_SOURCE_ARCHIVE` logs a compact completion receipt with the archive
identity, file count, source bytes and verified manifest object. Failure logs
contain only the exception type. The full file manifest remains in private R2.
Any container enabling this must include the three pinned `docs/evidence/`
files as well as `backend/app/data/`; the normal API source build includes them.

This source archive does not add live R2 catalogue cache delivery or a weekly
Drive copy. Those are separate steps in the current completion plan.
