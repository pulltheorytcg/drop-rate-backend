# Topps Heritage source review — 4 November 2026

## Scope and permission

This is an additive **100-reference** sports catalogue source. It is not full
Topps/Panini coverage, a physical-stock import, a price feed or artwork approval.

Primary sources inspected:

- [Card Collector Capital data hub](https://cardcollectorcapital.com/data):
  explicitly permits copying, analysis and republication of its compilation and
  original annotations under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  Preserve credit, evidence links, evidence states and reviewed dates. The
  permission does not relicense third-party documents, trademarks or artwork.
- [2026 Topps Heritage JSON export](https://cardcollectorcapital.com/data/2026-topps-heritage-short-prints.json):
  reviewed dataset date **2026-09-30**, 100 unique numbered starred-base entries.
  This JSON export, not the linked manufacturer PDF, is the only network target.
- [Topps UK terms](https://uk.topps.com/pages/terms-of-use) and
  [Topps US terms](https://www.topps.com/pages/terms-of-use): direct bulk scraping
  is not an approved fallback. No Topps page, PDF or artwork is fetched by the
  adapter.
- [Panini checklist page](https://www.paniniamerica.net/checklist): public
  collector access is not a verified third-party bulk redistribution licence.
  No Panini bulk adapter is enabled by this change.

The inspected Heritage response was **19,956 bytes**, SHA-256:

`cb37f288a573533e6be0ebb8229dcf34d6d78f419018044447ed52aedcc226bd`

Its manufacturer-evidence digest (a value recorded in the source JSON, not an
independent PDF download by this importer) is:

`4ad60fa68d1429519f9ceeee11188663d9b3c64b2a5e387112f1bb857d967c8a`

| Checklist category | Numbered references |
| --- | ---: |
| Base Cards | 76 |
| World Series Highlights | 3 |
| Turn Back The Clock | 5 |
| Quad Rookies | 16 |
| Total | 100 |

The sixteen four-player entries remain sixteen cards, not sixty-four cards.
Every supplied source page is retained. #360's source warning distinguishes
its Back Variation designation from Owen Caissie #88; it remains `source_note`
evidence and does not fill an approved physical parallel. No print run is
inferred from the starred checklist designation.

## Integration and safety

- New independent provider/source ID: `cardcollectorcapital_heritage`.
- Registry scope: `SPORTS_CARDS` / catalogue language `English`. The catalogue
  language does not establish a physical card's language.
- Add this source to the existing `TCG_R2_FIRST_IMPORT_SOURCES` list only after
  tests, reviewed deployment and explicit activation. Do not replace the list.
- Existing `cardcollectorcapital` Bowman descriptors, reference keys, immutable
  generations and published pointers are unchanged. The registry already accepts
  the new provider ID; no SQL schema, grants, RLS or role changes are required.
- One credential-free GET, 65,536-byte maximum, pinned reviewed source digest,
  exact metadata/header checks and 100 unique numbers. Redirects, HTTP denials,
  throttling and altered exports fail closed without retry or fallback. Changed
  bytes require another source review; a failed import keeps the good generation.
- Normal weekly refresh and existing `CURRENT`/compare-and-swap publication
  idempotency apply. Source facts and attribution are stored in private R2;
  PostgreSQL retains only the approved publication pointer/audit and on-demand
  canonical links. Existing partition/aggregate-byte limits remain unchanged.
- No inventory, ownership, images, market prices, physical-language/parallel
  approvals, marketplace publishing or settlement writes are performed here.

## Other sports data reviewed, not imported

The same hub's [54-row product library](https://cardcollectorcapital.com/data/product-library-2026-08-18.json)
is CC BY 4.0 and reviewed 2026-08-18: 34 Topps, 10 Panini and 10 Upper Deck rows.
These are **product/set-level** facts, not individual cards or exact sealed SKUs.
They must not be counted as card coverage or converted to invented printings.
Its "Football" and "Soccer" labels also need explicit sport normalization for
a UK-facing directory. No access to a complete licensed Panini catalogue or a
paid data subscription is implied by this release.

## Verification and rollout gates

Synthetic tests cover header/licence/provenance failures, duplicate and malformed
identities, multi-player cards, #360's note, public-client isolation, byte/row
bounds, changed exports, denied/redirected responses, independent source
configuration, weekly `CURRENT` handling and in-memory R2 cold reconstruction.
The app view must expose CC BY attribution and retain unknown physical identity,
artwork and pricing. Full CI, exact deployed commit, verified R2 upload/readback,
SQL pointer readback and authenticated app browse remain separate release gates;
the adapter's existence does not claim that activation has occurred.

Local verification on 4 November 2026: **277 focused tests passed** across the
Heritage, existing sports, generic source and importer suites. A credential-free
read of the reviewed JSON passed the pinned digest and schema, then an in-memory
upload/readback/cold-search roundtrip produced 100 references in one set,
104,647 normalized raw bytes, sixteen multi-player cards and one #360 warning.
That check performed **zero production writes** and did not fetch the source PDF.
