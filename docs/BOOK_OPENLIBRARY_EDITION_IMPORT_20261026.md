# Comics and manga factual edition import — 26 October 2026

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

