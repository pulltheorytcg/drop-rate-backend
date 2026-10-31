# Japanese artwork recovery — 31 October 2026

The reviewed manifest supplies 3,065 missing Japanese Pokémon reference images.
It does not approve listing photography, change card identity, alter stock, or
replace an existing image. The application serves these through its existing
authenticated reference-image route and private R2 reference cache.

## Source and checks

- Metadata: `https://github.com/type-null/PTCG-database`, commit
  `18e0de2feb7a35ebe4296ede0ba6cc768961489b` (MIT metadata; card artwork is separate).
- Assets: the exact `www.pokemon-card.com/assets/images/card_images/large/` URL
  in that record, whose numeric filename agrees with the official detail page ID.
- Match: Japanese set code, printed number and total, and Japanese name.
  TCGdex source URL and provider/local ID must also agree. Explicit promo codes
  may stand in place of a numeric printed total. No set-name aliases are guessed.
- Multiple official images for the same identity are held for review.
- Each saved asset was fetched successfully, size bounded to 2 MB, decoded,
  checked for single-card dimensions, and hashed. Requests use four concurrent
  downloads, a ten-second timeout, and stop on HTTP 429.
- Of 5,972 blank Japanese references, 3,068 were unique matches. All fetched;
  three combined two-card stadium images failed the single-card dimension check.
  The other gaps include 2,744 unmatched identities and 160 ambiguous images.

`backend/data/pokemon_official_artwork_20261031.json.gz` contains factual identity
fields, source URLs, hashes, verification timestamps and the three rejected IDs.
SHA-256: `91b991dd1b23027e3215c4aabc4592d5b4867c4fce6f35af569c02c491a8bca6`.
It contains neither image bytes nor card rules/flavour text.

## Reproduce and apply

Export the current blank Japanese TCGdex references with `provider_id`, `set_id`,
`name`, `card_number`, `source_url`, and `evidence->>'provider_local_id' AS local_id`.
Check out the pinned metadata commit and run:

```sh
PYTHONPATH=backend python scripts/verify_pokemon_official_artwork.py \
  --source /path/to/PTCG-database --refs /path/to/refs.json \
  --output /path/to/verified.json
```

The script verifies assets and writes a resumable manifest; it never accesses a
database. Deploy the official asset allowlist before attaching URLs. Apply
reviewed entries in bounded batches using `pokemon_official_artwork.WRITE_SQL`
with a JSON array parameter. The statement checks every original identity field
and a still-blank image at write time. Replaying it writes nothing. It preserves
existing evidence and adds a `REFERENCE_ONLY_NOT_APPROVED_MEDIA` receipt.

## Pricing correction in the same release

CardTrader expansion asking guides now retain positive prices below £1. They
still require three independent sellers, the exact unambiguous printing, Near
Mint English raw singles, one finish signature, and the existing spread limit.
The £1 selling minimum remains in the store-pricing rules. This fix does not
declare the 89% catalogue coverage goal complete.
