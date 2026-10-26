# Comics and manga factual edition import - 26 October 2026

The live starting catalogue has 48 book products: 36 structured manga editions,
10 structured Marvel/DC editions, and 2 seller-entered books. PRH/GCD provider
credentials are not configured. This release adds a permitted alternative for
factual edition metadata. It does not claim a complete comics/manga catalogue.

## Source and boundaries

Open Library explicitly directs bulk users to its monthly dumps rather than its
live APIs. The pilot reads only the official editions dump:
https://archive.org/download/ol_dump_2026-09-30/ol_dump_editions_2026-09-30.txt.gz

The selector stops at 200 accepted records, 64 MiB compressed, 256 MiB uncompressed or
240 seconds, whichever occurs first. CI enforces an additional 250-second process
timeout. It does not download the entire multi-gigabyte archive. Its report
separates scanned, accepted, rejected and stop reasons, and records the selected
snapshot and consumed compressed-prefix hashes. A bounded prefix is not a full
archive integrity check or proof of comprehensive coverage.

Authoritative source contracts:
- https://openlibrary.org/developers/api
- https://openlibrary.org/developers/dumps
- https://openlibrary.org/developers/licensing

The licensing page does not grant a blanket CC0 licence; no such claim is stored.
Only factual bibliographic fields are retained. Descriptions, author biographies,
covers and prices are excluded. Commercial cover permission is not inferred.

## Edition identity and import

An accepted record must be a specific OL edition with one checksum-valid ISBN
(normalising equivalent ISBN-10/ISBN-13), explicit language, one publisher, supported
physical binding, an unambiguous volume/issue number and an established release
year. Manga needs explicit manga subjects or an exact match to one of the six
already-reviewed English VIZ series and its publisher. Country and author
nationality never classify manga. Edition/omnibus title wording and binding remain
part of identity; printing numbers and cover variants are never invented.

Conflicting ISBNs inside the selected prefix exclude both candidate records.
Existing canonical/ISBN conflicts are held for review by the existing bulk importer,
which preserves owners, physical copies and current market prices. Database capacity
is checked before every bounded transaction. The normal 500 MB quota / 400 MB pause
guard is unchanged. Source mappings make retries idempotent.

Run the read-only selector, then the existing staging/import workflow:

```sh
PYTHONPATH=backend python -m scripts.select_openlibrary_books --source https://archive.org/download/ol_dump_2026-09-30/ol_dump_editions_2026-09-30.txt.gz --output openlibrary-pilot.jsonl --report openlibrary-pilot-report.json
PYTHONPATH=backend python -m scripts.import_book_catalogue --state openlibrary-stage.sqlite stage --provider OPEN_LIBRARY --input openlibrary-pilot.jsonl
PYTHONPATH=backend python -m scripts.import_book_catalogue --state openlibrary-stage.sqlite report
PYTHONPATH=backend python -m scripts.import_book_catalogue --state openlibrary-stage.sqlite plan
```

After reviewing actual accepted records/counts and measured capacity, the existing
authorised operator can apply one 50-row pilot using the standard apply command.
No scheduler, source subscription or production write is installed by CI. New
records remain STRUCTURED with source OPEN_LIBRARY_CATALOGUE and a REVIEW source
mapping; they do not become verified physical printings or publisher-authorised art.
Source links identify Open Library, not an official publisher.

## Validation

Pure tests cover exact edition/ISBN/language/binding/volume rules, ambiguous facts,
duplicate/conflicting ISBNs, secret-free provenance, rejection of bulk-API inputs,
redirect boundaries, byte limits and accepted-record caps. Real PostgreSQL tests
exercise insertion/replay, current-edition conflicts, truthful shared attribution,
no implicit cover/market value, and unchanged physical inventory.

CI produces the actual selected snapshot and report for review. Deployment and
production application must be verified independently; code completion alone does
not mean any new editions or covers have been added.


## Measured pilot and reviewed input

PR 736 CI run 40404355523 completed the read-only pilot successfully. It scanned
246,645 edition records, structurally accepted 39, and rejected 246,606. It stopped
at the 256 MiB uncompressed ceiling after reading 54,403,072 compressed bytes.
All 39 accepted records passed the canonical normalizer again. The estimated
database footprint for that full candidate set was 494,652 bytes.

The original candidate snapshot SHA256 is
9d92b11cc2f754b0fa00d6073f0b9653549bca8d8abae3a0000ec0e9bfff306d.
The CI artifact preserves the original snapshot and selector report:
https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/40404355523

Review held 7 candidates with unresolved classification, format or edition facts.
For example, the Spanish Savage Dragon record has an inconsistent manga subject;
the Transformers ISBN identifies a limited edition on Titan's own catalogue whose
edition wording and release year differ from the dump. Walking Dead release dates
also conflict across the dump, publisher and distributor. These records were
excluded without silently replacing their source facts.

The committed reviewed input is
backend/app/data/book_openlibrary_pilot_20261026.jsonl. Its adjacent review manifest
records every held OL ID/reason and the evidence links. The remaining 32 records
comprise 15 manga, 4 Marvel, 2 DC and 11 other comics; 30 are English and 2 Spanish.
They remain bibliographic records attributed to Open Library, not independently
verified printings or market/cover approvals. No field values were changed during
selection. The reviewed input SHA256 is
66fee0a07e5c43b3cf957f36f54e9382be4eaed2a1b8eb6fc3bc239235653b03.

## Existing-runtime operator commands

An authorised operator can reuse the deployed runtime's existing application
settings explicitly. This does not request, print, copy or modify a secret:

```sh
PYTHONPATH=backend python -m scripts.import_book_catalogue --state /tmp/ol-20261026.sqlite stage --provider OPEN_LIBRARY --input backend/app/data/book_openlibrary_pilot_20261026.jsonl
PYTHONPATH=backend python -m scripts.import_book_catalogue --state /tmp/ol-20261026.sqlite report
PYTHONPATH=backend python -m scripts.import_book_catalogue --state /tmp/ol-20261026.sqlite plan --from-settings
```

Plan returns the current database role, insert-grant booleans and whether the role
bypasses RLS, alongside capacity. It never returns a DSN. Table grants do not
override RLS; a restricted application role can correctly refuse trusted catalogue
inserts. Do not broaden grants to force the pilot through. Without --from-settings,
the existing dedicated BOOK_IMPORT_DATABASE_URL behavior is unchanged.

Only after reviewing the exact snapshot, plan, runtime role and capacity:

```sh
PYTHONPATH=backend python -m scripts.import_book_catalogue --state /tmp/ol-20261026.sqlite apply --from-settings --batch-size 50 --max-batches 1
PYTHONPATH=backend python -m scripts.import_book_catalogue --state /tmp/ol-20261026.sqlite report
```

The source mapping/digest makes replay idempotent. A conflicting existing edition
must remain REVIEW; success is measured from actual imported/existing/review counts,
then a separate database readback. No production import is claimed in this document.

