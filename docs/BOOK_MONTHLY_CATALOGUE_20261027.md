# Monthly book catalogue recovery — 27 October 2026

## Scope and evidence

The book catalogue started this recovery with 95 edition records: 37 comics and
58 manga. Those counts are imported records, not a denominator for every comic
or manga published. The catalogue had no supported book market snapshots and no
book identity marked as a verified exact physical printing.

The new worker reads one **complete official Open Library monthly editions
dump**, replacing the prefix-only pilot as the source of bulk candidates. The
pilot remains bounded and unchanged. Open Library explicitly directs bulk users
to its [monthly dumps](https://openlibrary.org/developers/dumps), rather than
bulk individual API calls; its [metadata licensing page](https://openlibrary.org/developers/licensing)
does not grant rights to reuse cover artwork.

Source: `ol_dump_editions_2026-09-30.txt.gz`, 12,617,475,043 compressed bytes,
official SHA1 `c2b534d524ba7de1b7161574da00b3ffb51d2d69`. The exact source URL and
manifest URL are recorded in
`backend/app/data/book_openlibrary_dump_20260930_manifest.json`. The full local
download matched both the manifest size and hash. A scan is not exportable
until it also reaches gzip EOF and passes gzip CRC validation.

The selected factual JSONL, full selection receipt and detailed review holds are
the durable handoff artifacts. The full compressed dump is a reproducible local
cache; the worker never expands the entire dump onto disk. Selected source
facts and receipts can also be stored in R2 through an authorised, credentialled
uploader. Source facts never enter the database as a raw dump.

## What the worker guarantees

`app.book_openlibrary_bulk` binds resumable SQLite state to source URL, full
source hash/size, observation date and parser version. It retains only candidate
edition facts, source identities and quarantine records. A resumed gzip scan
replays the compressed prefix locally; it does not download it again. The work
budget starts after that replay so a late checkpoint always makes progress.

Every candidate must pass the existing Open Library adapter and full catalogue
schema: an exact edition ID, one canonical checksum-valid ISBN, one explicit
language and publisher, explicit issue/volume number, recognised physical
binding, established publication year and an explicit comics/manga subject or
the existing narrow reviewed-series rule. No first printing, cover variant,
condition, grade, image or market value is inferred.

Conflicting accepted ISBN/source identities are quarantined even when discovered
late. Unrepresented subtitle/edition qualifiers, the known omitted 3-in-1
edition and records with multiple distinct valid ISBNs block **every** applicable
ISBN and source identity before other missing-field checks. This works in either
scan order and across restarts. It is not a claim that every external source
record is correct or that worldwide editions are collision-free.

Before export, a separate auditable quality pass holds explicit criticism,
study/teaching and reference subjects, art/instruction-book titles, provisional
titles and reviewed form ambiguities. A deterministic stratified review of 40
provisional candidates found art-book and provisional-title false positives;
those findings became export-time holds. The hold table retains the original
selected row and reason. Genre labels remain source-derived and unverified.

## Operator cadence

Run once per newly published monthly dump, with the exact dated URL. Reuse the
same local cache/state paths when a run is interrupted. Each download invocation
requests at most one bounded HTTP range, allows only official HTTPS archive
redirects, validates the exact Content-Range and preserves a local disk reserve.
There is no automatic retry or individual-book API harvesting.

```sh
PYTHONPATH=backend python -m scripts.import_openlibrary_monthly manifest \
  --source "$BOOK_DUMP_SOURCE" --manifest "$BOOK_MANIFEST"
PYTHONPATH=backend python -m scripts.import_openlibrary_monthly download \
  --manifest "$BOOK_MANIFEST" --dump "$BOOK_DUMP_CACHE"
PYTHONPATH=backend python -m scripts.import_openlibrary_monthly select \
  --manifest "$BOOK_MANIFEST" --dump "$BOOK_DUMP_CACHE" \
  --state "$BOOK_SELECTION_STATE" --max-seconds 900
PYTHONPATH=backend python -m scripts.import_openlibrary_monthly report \
  --manifest "$BOOK_MANIFEST" --state "$BOOK_SELECTION_STATE"
```

Repeat bounded download/select invocations until their receipts report complete.
An incomplete selection cannot be exported. Preserve the final JSON report from
`export` alongside the exact JSONL bytes; it binds the reviewed subset hash to the
full source and quality receipt. Export can exclude the current canonical ISBNs.
Its deterministic order alternates comics and manga before applying an optional
row cap, rather than selecting only one ISBN prefix/category.

Stage the exported JSONL through the existing `import_book_catalogue.py` operator.
For a reviewed database connector application, use:

```sh
PYTHONPATH=backend python -m scripts.export_book_connector_batches \
  --state "$BOOK_IMPORT_STAGE" --snapshot-sha256 "$BOOK_SNAPSHOT_SHA256" \
  --selection-report "$BOOK_SELECTION_RECEIPT" \
  --database-bytes "$BOOK_CURRENT_DATABASE_BYTES" --output "$BOOK_SQL_OUTPUT" \
  --batch-size 50 --max-records 1500
```

The exporter requires complete staging and a matching full-source/CRC/quality
receipt. It caps the initial batch plan by the current capacity preflight. The
27 October preflight was 358,042,771 bytes against the unchanged 400,000,000-byte
pause threshold. Estimates include row/index/provenance overhead; they are a
planning reserve, not a promise of actual database growth.

Each generated SQL batch contains a hash-bound UTF-8 JSON payload transported as
base64, a transaction, the existing book-import advisory lock, 5-second lock and
30-second statement timeouts, both read-only checks and the unchanged capacity
guard. Source digests allow replay; changed source facts, incompatible existing
identities and cross-language ISBN10/ISBN13 aliases are held without modifying
the existing identity. A late error rolls back the entire batch. New identities
remain `STRUCTURED`; mappings remain `REVIEW` with confidence zero.

The exporter creates no permanent SQL functions, grants, privileged routes or
deployment hooks. An authorised operator reviews and executes each bounded SQL
file, saves its receipt only after successful commit, then runs its separate
readback SQL. Stop on a failed batch or unexpected source/identity conflict.
Existing provenance mappings store immutable source digests and batch IDs for
independent reconciliation; uncommitted receipts are not completion evidence.

## Covers and market values

Open Library metadata does not establish artwork permission, and its covers are
not imported. The current book artwork reader also requires exact publisher
reference evidence; adding a cover URL to an Open Library record would not make
it display. A publisher enrichment must reconcile the exact ISBN, binding,
language, volume and edition and preserve the original metadata provenance.
Digital-only publisher pages cannot donate a physical edition's identity/cover.
Seller-entered `NEEDS_REVIEW` rows remain held.

The existing eBay pathway can support an owner-independent catalogue reference
once an exact printing is verified and five matching UK sold comparisons supply
an explicit condition/grade, language and variant. Sales must be within 90 days
and provider evidence checked within seven days. The resulting reference basis
does not approve an owner's physical copy. ISBN-only edition records and
publisher retail prices cannot become guessed market values. The bulk worker
adds no book prices and does not relax the existing free-feed quota or matching
rules.

## Validation

The targeted existing and new book suites pass 119 cases locally, including real
PostgreSQL execution of connector transactions through pinned PGlite 0.5.12.
The Open Library workflow has a mandatory offline connector SQL job using Node
24 and the same pinned package; it does not download the complete dump in CI.
Cases cover restart/EOF/hash/CRC, late conflicts and both-order qualifier holds,
quality holds, full-receipt gating, capacity-limited export, idempotent replay,
source and identity conflicts, ISBN aliases across languages, transaction
rollback, read-only mode, capacity reserve and injection-shaped source titles.
The isolated PostgreSQL fixture does not substitute for reviewing production
RLS, role permissions or auditing; no production application is claimed here.
