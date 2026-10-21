# Comic and manga catalogue import runbook

Status: prepared for the storage upgrade. **No bulk production import is enabled
or scheduled.** The existing 46 publisher editions (36 manga, 10 comics) remain
the live database baseline; there are 48 book products including seller entries.
This work does not claim that thousands of editions or covers have been loaded.

The initial read-only preflight found **402,304,147 bytes** in Postgres, above the
existing **400,000,000-byte** bulk-refresh guard. These are decimal MB. The
500,000,000-byte Free quota and all existing refresh guards remain unchanged.
The user asked to prepare everything and defer the large load until more storage
is available. No storage purchase, capacity setting change, production row write,
new schedule, or provider subscription is part of this release.

## Coverage and source access

| Input | Comics | Manga | Artwork | Access still needed |
| --- | --- | --- | --- | --- |
| GCD API snapshots | Issues, runs and named variants | Volumes in explicitly classified series | GCD scans excluded; metadata licence does not license covers | Authorised GCD account/export; reviewed series classification file |
| PRH Title API snapshots | Numbered physical collections with comic subjects | Volumes/omnibuses with manga subjects | Exact ISBN publisher references, after byte validation | Activated PRH API key and actual comics/manga category IDs |
| Publisher JSONL | Explicit issue/variant/printing facts | Explicit volume, edition and language facts | Current approved publisher/CDN pairs only | Authorised publisher data with provenance |

This is not a promise of universal coverage. PRH only covers its supplied
catalogue. GCD classification is per series, not an assumption that every
Japanese comic is manga. Unsupported languages, absent issue/volume numbers,
ambiguous identifiers, future publications, ebooks/boxed sets, unsupported cover
hosts and conflicting source records remain in the review queue. New source
adapters or classification rules require actual feed evidence. No Comic Vine
commercial feed is enabled, and no restricted site is bypassed.

Primary source contracts reviewed for this implementation:

- [GCD API](https://github.com/GrandComicsDatabase/gcd-django/wiki/API) and
  [current serializers](https://github.com/GrandComicsDatabase/gcd-django/blob/beta/apps/api/serializers.py).
- [GCD](https://www.comics.org/) metadata attribution and
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- [PRH Title](https://developer.penguinrandomhouse.com/docs/read/enhanced_prh_api/resources/Title),
  [paging/filters](https://developer.penguinrandomhouse.com/docs/read/enhanced_prh_api/resources/Common_Parameters),
  [series numbers](https://developer.penguinrandomhouse.com/docs/read/enhanced_prh_api/concepts/Series_numbers),
  [cover images](https://developer.penguinrandomhouse.com/docs/read/enhanced_prh_api/concepts/Images),
  and [developer access](https://developer.penguinrandomhouse.com/).

Source adapters are tested against these documented shapes and synthetic HTTP
responses. Real authenticated GCD/PRH downloads have **not** been acceptance
tested: credentials were not configured, and anonymous GCD access returned 403.
Schema changes stop a download instead of silently creating incorrect products.

## What is ready

`backend/scripts/fetch_book_catalogue.py` downloads to durable SQLite checkpoints.
It bounds response sizes, request counts and page sizes, uses fixed provider
origins, never follows authentication redirects, and stops on denial/rate limits.
Repeat the same command to continue at the last committed cursor. Respect any
reported Retry-After before an explicit retry. Credentials come from environment
variables, are not written to checkpoint configuration, and are not printed in
exceptions. PRH pages that echo the key are rejected. Run one downloader per
checkpoint; keep separate checkpoints for different categories/rule sets.

`backend/scripts/import_book_catalogue.py` stages an immutable UTF-8 JSONL file
with bounded memory, input SHA-256 binding and every-200-line checkpoints. It
normalises ISBN-10 to ISBN-13, retains full comic UPC add-ons and separates
language, run, binding/edition, cover variant and explicit printing facts. It uses
the same canonical identity as seller intake. Conflicting records are held for
review, not overwritten. Duplicate records do not create duplicate products.

Cover validation downloads only approved publisher image paths, validates raster
bytes and dimensions, and saves a SHA-256/edition-bound receipt. Failures leave
artwork pending while other covers continue. Importing metadata alone never
approves a cover. Imported publisher receipts work through existing private
catalogue thumbnails, scan research and saved-book Choose cover. Shared catalogue
copies use the same reference. GCD records display source/CC BY-SA attribution
and carry the licence and adaptation notice in their stored provenance.

The apply step checks capacity and read-only mode before each 1–100-row transaction
(default 50). Each committed record has an indexed, stable source mapping in
the existing `tcg.provider_catalogue_mappings` table. A lost local checkpoint is
safe to replay. Changed source identities and barcode conflicts require review.
Existing exact products are reused without changing their verification status
or artwork. Newly inserted book profiles remain `STRUCTURED`, mappings `REVIEW`,
and cover rights `PENDING`. No schema migration is required.

The importer does not create physical stock, approve identity, price books, copy
MSRP into market values, change ownership, approve listing media or publish to a
sales channel. Existing inventory and financial records are outside its writes.
It does not infer first printing from an ISBN, date or default publisher cover.

## Prepare source snapshots

Run commands from the repository with its installed Python dependencies. Store
the download/checkpoint/export files on a durable operator volume outside git.
The variables below are paths/credentials supplied by the operator, not literal
values to copy. Do not commit credentials or downloaded publisher databases.

For PRH, set `PRH_API_KEY` in the operator environment after account activation.
Use an actual category ID from PRH's category API; do not invent an ID from a
category name. Use separate snapshots for relevant comics and manga categories.

```bash
PYTHONPATH=backend python -m scripts.fetch_book_catalogue --state "$PRH_DOWNLOAD_STATE" prh --category-id "$PRH_CATEGORY_ID" --max-pages 5
PYTHONPATH=backend python -m scripts.fetch_book_catalogue --state "$PRH_DOWNLOAD_STATE" report
PYTHONPATH=backend python -m scripts.fetch_book_catalogue --state "$PRH_DOWNLOAD_STATE" export --output "$PRH_SNAPSHOT"
```

Repeat the download until `complete: true`; an empty terminal page proves
completion. This is offset paging over a live source, not a guaranteed provider
snapshot. Reconcile totals and take a new snapshot later to detect additions or
source changes; source mappings make overlaps safe. PRH source records are JSONL
objects with `title` (the complete Title object) and `observed_on` (ISO date).

For GCD, set `GCD_USERNAME` and `GCD_PASSWORD`. Supply a JSON array with real
reviewed `series_id`, `system_code` and `book_format` values. Supported systems are
`MARVEL_COMICS`, `DC_COMICS`, `OTHER_COMICS`, `MANGA`; manga requires `MANGA` format.
Other physical formats are `SINGLE_ISSUE`, `TRADE_PAPERBACK`, `HARDCOVER`.
One series rule expands to all its active issues; it is not one rule per issue.

```bash
PYTHONPATH=backend python -m scripts.fetch_book_catalogue --state "$GCD_DOWNLOAD_STATE" gcd --rules "$GCD_SERIES_RULES" --max-requests 50
PYTHONPATH=backend python -m scripts.fetch_book_catalogue --state "$GCD_DOWNLOAD_STATE" report
PYTHONPATH=backend python -m scripts.fetch_book_catalogue --state "$GCD_DOWNLOAD_STATE" export --output "$GCD_SNAPSHOT"
```

An authorised equivalent GCD JSONL export can bypass the downloader. Each line
contains joined `issue`, `series`, `publisher` API objects, `classification`
(the series rule), and `observed_on`. Relations must agree. Do not execute a
downloaded SQL dump against the application database. A SQL-only GCD export
needs a separately reviewed offline conversion to this documented shape.

Publisher JSONL uses `record_id`, `source_url`, `observed_on`, `release_date`,
`language`, `book` (the existing `ComicPrintingCreate` fields), optional
`image_url`, and `evidence_url` when printing/variant/artist facts are specified.
Evidence must be the exact approved source record. A publisher snapshot may use
all four book systems; no hard-coded 40-record starter limit applies. Source
records and licences must be retained when redistributing adapted GCD metadata.

## Stage and check without touching production

```bash
PYTHONPATH=backend python -m scripts.import_book_catalogue --state "$BOOK_STAGE" stage --provider PRH --input "$PRH_SNAPSHOT"
PYTHONPATH=backend python -m scripts.import_book_catalogue --state "$BOOK_STAGE" report
PYTHONPATH=backend python -m scripts.import_book_catalogue --state "$BOOK_STAGE" review --limit 100
PYTHONPATH=backend python -m scripts.import_book_catalogue --state "$BOOK_STAGE" covers --limit 100
```

Choose `GCD` or `PUBLISHER` for those snapshots. One staging file belongs to one
immutable input and provider. Use a new stage after correcting source rows, then
replay against the same source mappings. `covers --retry-failed` explicitly retries
previous failures; normal cover passes continue past failed images. Complete
cover checks before applying: apply does not overwrite an existing product or
attach a newly checked image to an already imported product. Such enrichment is
a separate reviewed update, not implicit in re-importing a source.

Reports give READY/REVIEW/DUPLICATE/IMPORTED/EXISTING counts, review reasons, ready
counts by comic/manga system, checked/pending/unavailable artwork and a conservative
storage reserve. The reserve includes JSON/index/page overhead, not downloaded
images, but is an estimate rather than measured production growth.

## Activation after the storage upgrade

1. Verify the actual **Postgres database quota**, not object storage capacity.
   Record its decimal-byte value as `BOOK_IMPORT_DATABASE_LIMIT_BYTES`. The
   importer will retain 20% / at least 100 MB headroom. Nothing here buys storage
   or changes the platform's quota. With no override it still pauses at 400 MB.
2. Confirm source access/terms, completed snapshot totals, classifications and
   review counts for **both comics and manga**. Decide the first bounded batch
   from the available source coverage, not a claim to contain every publication.
3. Confirm the release is deployed and normal database backups are available.
   Set the existing authorised operator connection in `BOOK_IMPORT_DATABASE_URL`.
   It must use the catalogue administrator role; never give this DSN to a seller.
4. Run the read-only plan with the verified quota, then a single 50-row pilot.

```bash
PYTHONPATH=backend python -m scripts.import_book_catalogue --state "$BOOK_STAGE" plan --database-limit-bytes "$BOOK_IMPORT_DATABASE_LIMIT_BYTES"
PYTHONPATH=backend python -m scripts.import_book_catalogue --state "$BOOK_STAGE" apply --database-limit-bytes "$BOOK_IMPORT_DATABASE_LIMIT_BYTES" --batch-size 50 --max-batches 1
```

5. Re-run `plan`; compare measured Postgres growth with the reserve. Check comics
   and manga counts, checked cover counts, duplicate/source conflicts and the
   reviewed source mapping. Confirm two seller accounts can browse the same
   editions, see correct covers and add independent copies. Compare the original
   inventory digest/row count and verify prices/listing permissions did not change.
6. Continue bounded runs (default at most 1,000 records per invocation) while
   monitoring capacity. No cron has been installed. Repeat the same apply command
   after an interruption; do not delete or rewrite checkpoints to force a replay.

The quota override applies only to this explicit book import job. Other catalogue
maintenance jobs keep their existing capacity guard until separately updated
after the upgrade is verified. Read-only mode always wins, even with a larger quota.

## Release verification and rollback

Unit tests cover both adapters/categories, 2,500-row disk staging, interruption and
input binding, edition/language/variant separation, image validation, source URL
and credential boundaries, rate-limit cursor replay and default/upgraded capacity.
`tests/book_bulk_import_fixture.py` runs against actual PostgreSQL in the collection
CI job: insert/replay, source changes, barcode collisions, transactional rollback,
read-only mode, seller write denial, shared attribution/artwork and unchanged stock.
The existing browser suite checks the seller workflows; Node tests exercise GCD
attribution, PRH links and rejection of lookalike domains.

Deployment remains separate from implementation. The earlier artwork release was
blocked by Railway's 21 October build pause; see
[the earlier release record](BOOK_CATALOGUE_LIBRARY_20261021.md). Do not claim new
artwork is live until deployment and live asset/readiness checks succeed.

Rollback: stop the operator process. Uncommitted chunks roll back; already
committed shared identities are retained for review, especially if copies refer
to them. Use the batch/source mappings to investigate, never delete catalogue
rows blindly. Revoking source/cover status removes an imported cover from private
reference reads. Reverting the code disables dynamic bulk references without
changing inventory or financial records. Source and staging files are retained
for reproducible review; provider credentials are not part of those files.
