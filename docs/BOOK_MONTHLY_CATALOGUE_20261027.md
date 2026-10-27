# Monthly book catalogue recovery — 27 October 2026

## Scope and evidence

The book catalogue started this recovery with 95 edition records: 37 comics and
58 manga. Those counts are imported records, not a denominator for every comic
or manga published. The catalogue had no supported book market snapshots and no
book identity marked as a verified exact physical printing.

The reviewed initial cohort of **1,495 new editions is now committed in
production**, with a separate successful readback for every one of the 30
batches. This brings the catalogue to 1,590 edition records: 785 comics and 805
manga under the stored source-derived categories. The new identities remain
`STRUCTURED`; this import adds no cover artwork, prices or verified physical
printings. Another 909 novel candidates remain staged for later review and
application.

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

## Imported cohort and remaining candidates

The complete source pass read 56,827,250 edition records. A second local pass
recovered the original subject taxonomy for all 2,537 provisional candidates in
216.87 seconds; 2,482 selected rows gained previously pruned short subjects,
with every normalized identity and source record digest unchanged.

| Checkpoint | Edition records |
| --- | ---: |
| Provisional candidates after source identity gates | 2,537 |
| Additional export-quality review holds | 117 |
| Full accepted factual snapshot | 2,420 |
| Already-present accepted ISBNs excluded | 16 |
| Novel records staged before production application | 2,404 |
| Independently reviewed initial cohort now IMPORTED | 1,495 |
| Further novel records remaining READY for later review/application | 909 |

The completed first import consists of the exact ordered survivors of the independently
reviewed 1,500-record cohort after five further holds, with **no refill**. Its
source-derived category counts are 747 manga, 94 DC comics, 122 Marvel comics and
532 other comics; languages are 1,450 English and 45 Spanish. These labels are
not certified genre classifications or physical-printing approval.

The immutable initial source JSONL is
`book_openlibrary_initial_reviewed_20261027.jsonl`, SHA256
`dc10814daac57325fa766b730c92567b4da5454487e67ef8fe5cdf9802d5def3`.
The normalized 1,495-entry cohort SHA256 is
`d2829f0d62ff504ef30885aed87a20067e3ac1fd218053eb904f3b80104ba54d`.
Its selection receipt binds the full source, original-subject audit, current
57-entry exact reviewed-holds registry, parent cohort hash, five removed IDs,
retained record digests and no-refill order. Every one of the 57 held ISBNs and
source IDs is absent from the initial cohort.

The connector application committed 30 transactions: 29 batches of 50 and one
of 45. Before application, its estimated database reserve was 18,898,656 bytes,
projecting 376,949,619 bytes from the later 358,050,963-byte read-only preflight.
The completed production checkpoint measured **370,617,491 bytes**, below the
unchanged 400,000,000-byte guard.

Production receipt `fb47fea2-ff75-4e46-b468-468288d6de17` is `COMPLETE`, finished
at **2026-10-27 11:41:20.147372 UTC**. All 1,495 receipt rows report `IMPORTED`.
The 30 independent readbacks confirm 1,495 matching source digests and 1,495
`STRUCTURED` identities, with zero missing records, source conflicts or invented
printing fields. Inventory remained at 616 rows with unchanged content MD5
`9ce22ee09a38670d505253da278d1b68`.

The public [production evidence](evidence/book-openlibrary-production-import-20261027.json)
preserves every batch receipt, actual catalogue ID, execution SQL hash and
separate readback, alongside the immutable source and selection hashes. Its
input receipt bundle SHA256 is
`6c695a5f9ebbfe0ee99dce15632e753fc2872d0aace6bd6538bd4c8081326641`.
The local initial staging database now has 1,495 `IMPORTED` rows; the full novel
staging database has the same 1,495 `IMPORTED` rows and 909 `READY` rows. Local
reconciliation matched source ID, normalized record digest and the actual
production catalogue ID before changing a status. All normalized entries and
immutable factual snapshots were preserved.

The selection receipts and import plan remain immutable records of preparation.
Their export-time `production_applied: false` fields describe that earlier
checkpoint; the separate production evidence above records the completed
application. The remaining 909 candidates have not been applied or promoted by
this reconciliation.

The review report also lists 56 existing catalogue ISBNs touched by the stricter
Open Library ambiguity rules. This does **not** establish that 56 existing
records are wrong: some have stronger independent publisher evidence. Existing
identities were preserved, and these are review pointers only.

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

`book_openlibrary_review_holds.json` stores exact ISBN/source-ID review decisions
with original title, publisher, subjects, source JSON hash and proof notes/URLs.
An updated registry invalidates an earlier export-quality/connector receipt.
Audience placeholders such as `Adult` or `Children` are held as missing publisher
evidence; the worker never guesses a publisher or silently reclassifies a title.

The future selector retains all short subject taxonomy strings, including
standalone negative form subjects. The initial complete scan began before that
projection change; its selected rows therefore receive a second local full-source
subject audit before export. That supplement records the exact original edition
JSON hashes and all source subjects. Restored subjects must leave normalized
book facts and record digests identical. The selector checkpoint version is not
changed; a separate complete-subject receipt records the additional evidence.

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

One separate existing-record reconciliation attached the exact publisher cover
for **Boys Over Flowers, volume 22**, ISBN 9781421509853, on 27 October. The
publisher physical edition and stored release date both identify 13 February
2007; the declared cover decoded at 300 × 450 pixels. Production receipt
`0a14df93-ddb0-4120-b5b7-220d4fe9fb34` completed at 11:34:07.678293 UTC, and a
separate 11:34:31 UTC readback confirmed the actual `book_cover_reference` reader
accepts it. Both identity statuses remain `STRUCTURED`; the new publisher mapping
remains `REVIEW` at confidence zero. The entire prior Open Library attributes
remain in `source_history`, with the original mapping digest unchanged. This
added no market value, approved canonical media or inventory changes, and it
does not approve R2 reproduction or a physical printing. The evidence and
receipt are in `book_publisher_cover_review_20261027.json`.

The existing eBay pathway can support an owner-independent catalogue reference
once an exact printing is verified and five matching UK sold comparisons supply
an explicit condition/grade, language and variant. Sales must be within 90 days
and provider evidence checked within seven days. The resulting reference basis
does not approve an owner's physical copy. ISBN-only edition records and
publisher retail prices cannot become guessed market values. The bulk worker
adds no book prices and does not relax the existing free-feed quota or matching
rules.

## Validation

The targeted existing and new book suites pass 128 cases locally, including real
PostgreSQL execution of connector transactions through pinned PGlite 0.5.12.
The Open Library workflow has a mandatory offline connector SQL job using Node
24 and the same pinned package; it does not download the complete dump in CI.
Cases cover restart/EOF/hash/CRC, late conflicts and both-order qualifier holds,
quality holds, full-receipt gating, capacity-limited export, idempotent replay,
source and identity conflicts, ISBN aliases across languages, transaction
rollback, read-only mode, capacity reserve and injection-shaped source titles.
The isolated PostgreSQL fixture does not substitute for reviewing production
RLS, role permissions or auditing. The completed initial import is substantiated
by the separate production receipts and readbacks linked above. All 30 payload
hashes and ordered source-ID lists were also reconciled against the reviewed
export manifests before the two local stages were marked `IMPORTED`.

## Recovered release safeguards

The final code, workflow, tests and data were recovered after the interrupted
workspace and matched their saved hashes. The continuation adds an offline
integrity gate over both complete snapshots, original subject audit, the exact
initial cohort and all 30 committed receipts. Review holds now match either an
ISBN or source edition ID, so a changed source ISBN cannot clear an existing
hold. Cached quality checks without that policy marker are rerun, and connector
SQL generation independently checks the current exact registry.

The original 57-entry registry and historical snapshots are unchanged. The
[deferred cohort review](evidence/book-deferred-review-20261027.json) records six
further conservative form-review findings among the 909 unapplied records. No
record in that deferred cohort is approved for application by this release.
