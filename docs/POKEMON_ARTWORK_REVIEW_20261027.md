# Individually reviewed M1S reference artwork — 27 October 2026

## Verified recovery scope

Exactly **92 existing Japanese M1S references** have individually reviewed source
artwork: 56 directly numbered files plus 36 explicitly corrected file assignments.
Each exact `high.webp` file returned HTTP 200 from
`assets.tcgdex.net`, decoded as a 600 × 825 WebP, and has a distinct SHA-256.
All 92 Japanese names, the printed M1S set mark, and the printed collector numbers
001/063–092/063 were individually checked in twelve contact sheets. Their names
and exact provider IDs also match the current TCGdex set response and the live
missing-artwork reference snapshot supplied for this repair.

## Confirmed production application

The reviewed 92-row correction completed in production at
**2026-10-27T11:11:25Z**. Durable `tcg.reference_sync_runs` receipt
**`7cae446f-9f7b-4c22-ad42-037b53e60275`** has status **COMPLETE** and records
**92 actual changed rows**.

An independent readback at **2026-10-27T11:11:47Z** matched all **92 target IDs,
image URLs and raster hashes** to the reviewed payload. **Zero M1S references
remained without an image URL.** Physical inventory remained at **616 rows**;
its before/after MD5 remained **`9ce22ee09a38670d505253da278d1b68`**.

The applied payload SHA-256 is
`440a730a77941ac31dc102d805e61f6279f20ca29f5d1e7dbfb99e214807c4f7`.
Its two review manifests are unchanged:

| Reviewed scope | Manifest SHA-256 |
| --- | --- |
| M1S 001–056 | `b9b4155be39e71acc6c9985060f501906a463161f3ec35b0c45b3cfd4d8b8a1d` |
| Explicit M1S 057–092 assignments | `040d59d5c8b992cc8ea5e4fbd85b3e16f5a328151f236c4e33be45184398b99d` |

This confirms the database artwork correction. Deployment of the accompanying
API repair and refresh-persistence code is a separate release step and is not
claimed here.

The first 56 committed review entries are in
`backend/data/pokemon_artwork_m1s_20261027.json`. It records each exact identity,
URL, actual byte hash, byte length, dimensions, observed printed number, source
check time and visual review page hash. It also records the set response hash
and source links. Original images and contact sheets are review intermediates;
the application continues to use the existing provider URLs.

## Why only this part of M1S

[TCGdex issue 2395](https://github.com/tcgdex/cards-database/issues/2395) explicitly
reports that 001–056 are correctly numbered and that files from 057 onward are
shifted. A new direct check of `/ja/M/M1S/057/high.webp` confirmed the problem:
the file visibly shows Japanese ツボツボ **064/063**, while API identity M1S-057
is あやしい時計. The 057–092 range remains ineligible for the ordinary repair
matcher. No offset, adjacent card, other language, or alternate printing is
substituted by that matcher.

The app binds every eligible reference to the exact manifest name, local ID,
provider ID, card number and URL, then fetches and decodes that URL again. Its
SHA-256 must match the reviewed raster. A different valid image, re-encoding,
low-resolution sibling or PNG cannot silently pass. Changed bytes require a new
review. The existing conditional update still checks the current database
identity, blank image URL and released set before writing.

## Separate explicit corrections for 057–092

`backend/data/pokemon_artwork_m1s_overrides_20261027.json` records 36 separately
reviewed assignments, one for each remaining target identity. Every assignment
was checked against the actual printed number and Japanese name visible on its
own decoded image. Each records both the target local ID and the source file's
different local ID, plus its immutable byte hash. These are reviewed rows for an
explicit conditional database write; they are not an automatic offset rule and
do not expand the normal repair matcher.

The prior upstream report described source file 073 as missing. A direct GET on
27 October returned a valid image showing メガガルーラex **080/063**. That file
was independently reviewed and binds only to target M1S-080. None of the 92
reviewed rasters shares a SHA-256 with another reviewed target.

For example, target **M1S-057** あやしい時計 uses the reviewed **078/high.webp**,
whose visible number is **057/063**. The provider source URL remains the card's
identity URL `/v2/ja/cards/M1S-057`; the source image URL remains the precise
reviewed asset URL. This distinction is recorded, rather than hidden by
renumbering either provider identity.

The source is the existing TCGdex display interface:

- [Documented asset URL structure and formats](https://tcgdex.dev/assets).
- [Provider FAQ and considerate bulk access](https://tcgdex.dev/faq).
- [Exact Japanese M1S set metadata](https://api.tcgdex.net/v2/ja/sets/M1S), released
  1 August 2025 according to the provider response.

These remain reference images. The repair does not approve canonical commerce
media, resolve physical foil/finish variants, copy images into R2, or grant
broader artwork redistribution rights.

## Other gaps checked

The larger missing releases MC and M2a do not yet provide a verified recovery
path. Their sampled card-detail API responses omit `image`; exact CDN probes
for MC-001, MC-193, M2a-001, M2a-193 and M2a-200 returned 404. These samples prove
those five files are absent at the checked paths, not that every asset in the
releases is unavailable. No repair was claimed for them.

The older fixed manifest-omission pass had already examined 4,001 candidates,
restored 3,331 and found 670 missing files, as recorded in
`CATALOGUE_COMPLETION_RUN_20261026.md`. Repeating that exhausted allowlist does
not by itself establish additional recovery.

## Refresh persistence

`save_reference_set` already preserves a repaired URL and its `image_reference`
when a provider sends a null image for the same exact set, name, number, source
URL and provider local ID. A concrete edge remained: an empty or whitespace-only
string was non-null and could erase both. The upsert input now normalizes those
spellings to null. Exact-identity changes still discard old artwork and proof.
This is a preventive fix; no claim is made that the current TCGdex feed caused
the historical gaps through this edge.

For these reviewed M1S corrections, an additional narrow guard preserves an
intact reviewed image and proof on unchanged identity even if a later provider
refresh offers a nonblank nominal URL. Otherwise a regenerated manifest could
replace a correct explicit assignment with the known shifted file. The guard
requires TCGdex, Pokémon, Japanese, M1S, the recognized review verification type
paired with its exact committed manifest SHA-256, matching proof/source/image
URLs, reference-only scope and a full image-byte hash. It does not freeze
ordinary provider images; identity changes still invalidate old proof.

This preservation rule trusts provenance written by the administrator-only
reviewed repair. It does not authenticate an arbitrary submitted proof object or
revalidate the complete manifest on every normal set upsert. Ordinary source
feeds construct fixed metadata and do not import an `image_reference` supplied
by a provider. An explicit repair writer must validate the exact target,
source URL and raster hash against the reviewed manifest before writing proof;
the consolidated 92-row payload was checked on those fields.

## Narrow operator run

The existing administrator-only operator can select the reviewed range without
requesting other sets. In the authenticated API runtime, first inspect:

```sh
PYTHONPATH=backend python backend/scripts/repair_pokemon_artwork.py \
  --from-settings --after Japanese M1S M1S-000 --limit 56 --max-seconds 120
```

For the reviewed snapshot, the expected result is 56 verified and zero failed.
Apply the same batch with `--apply`, then read back exact provider IDs, URLs,
byte hashes and receipt counts. The cursor is ordered over existing blank
references: if another process has already filled any of these rows, later rows
may enter the 56-row selection and be skipped by the strict manifest guard.
Never claim 56 updates solely from the dry run or the selected-row count.

Run receipts use the existing `tcgdex_artwork_repair` source and actual changed
row counts. Reapplying cannot overwrite a nonblank URL. Image provenance includes
the immutable review manifest hash and each source raster hash, in addition to
the normal actor, run ID and source timestamps.

The separately reviewed 36 overrides must use the explicit reviewed write
payload and the same `WRITE_SQL` identity/release/blank-URL conditions. They must
not be passed through the ordinary probe or inferred from an arithmetic offset.
For one atomic 92-row application, combine both exact reviewed payloads in one
transaction, attach the administrator/run IDs, store the actual returned-row
count in the durable receipt, and read back all 92 target identities and hashes.

## Verification

Targeted tests cover the complete manifest range, exact names/numbers/language,
the boundary at 056/057, changed valid rasters, refusal of unreviewed encoding
fallbacks, and rechecking identity after candidate construction. Sparse-image
tests exercise the actual upsert input for null/empty/whitespace values. The
disposable PostgreSQL artwork workflow additionally checks that all three
spellings retain both the old URL and proof for unchanged identity, while an
identity change with a blank image removes the old art.
Additional PostgreSQL regressions verify that later wrong nonblank M1S URLs
cannot overwrite intact reviewed corrections, while identity changes and
incomplete or unrecognized proof do not retain an artwork pin.
