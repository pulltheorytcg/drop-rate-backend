# Book reference-cover audit — 27 October 2026

All **46 cover references accepted by the existing edition/identity guards loaded
and decoded** in the 11:02:34 UTC source check. This is a check of those imported
references, not worldwide catalogue coverage or physical-copy verification.

| Result | Count |
| --- | ---: |
| Current raw SHA-256 equals the historical recorded hash | 41 |
| Historical hash exactly reproduced by the existing app thumbnail transform | 1 |
| Current cover visually matches; historical bytes were not reproduced | 4 |
| Source metadata page redirects to 404 while its exact cover URL returns 200 | 1, included in the four above |

No runtime, database, edition metadata, historical hash, or storefront-media
approval was changed by this audit. No downloaded rasters are committed.

## Five raw-hash differences

| Reference | Current image | Finding |
| --- | --- | --- |
| Absolute Batman #1 | 540 × 830; AVIF with app Accept, JPEG with JPEG Accept | Current official issue page links the same cover asset. Visible title and issue match. Neither representation nor the app thumbnail reproduces the historical hash. |
| Absolute Batman #2 | 540 × 830; same format negotiation | Current official page and visible issue match. Historical byte-change mechanism remains unproved. |
| Absolute Superman #1 | 540 × 830; same format negotiation | Current official page and visible issue match. Historical byte-change mechanism remains unproved. |
| Batman #463 | Raw AVIF 1073 × 1650 | Passing these current bytes through the unchanged app thumbnail function exactly reproduces the historical **351 × 540 WebP** hash. This is a raw-versus-rendered comparison, not evidence of changed cover art. |
| Deadpool / Batman #1, recorded Ryan Stegman second printing | JPEG 293 × 450; identical under app/JPEG Accept | The exact barcode cover shows the expected “Introducing Logo” artwork, consistent with the recorded variant. Old bytes were not reproduced. The PRH metadata page now redirects to its 404 page. |

Batman #463's reproduced thumbnail SHA-256 is
`c2ef1e3e87f5ec744af4be243e0d43d7942f2fb3ba9e9241a31976128dda83f7`.
That same hash and thumbnail dimensions are recorded in the older
[publisher-thumbnail evidence](evidence/book-queue-publisher-thumbnails-20261018.json).

The current follow-up downloads at 11:13:59–11:14:56 UTC reproduced all five raw
hashes from the earlier live check. CDN format negotiation is directly observed,
but the original rasters for the other four differences are unavailable. A
current visual match does not establish an encoding-only historical change.

## Publisher sources

- [Absolute Batman #1](https://www.dc.com/comics/absolute-batman-2024/absolute-batman-1)
  and its [exact cover](https://static.dc.com/2024-09/ABS_BM_Cv1_00111_DIGITAL.jpg?w=540).
- [Absolute Batman #2](https://www.dc.com/comics/absolute-batman-2024/absolute-batman-2)
  and its [exact cover](https://static.dc.com/2024-11/ABS_BM_Cv2_00211_DIGITAL.jpg?w=540).
- [Absolute Superman #1](https://www.dc.com/comics/absolute-superman-2024/absolute-superman-1)
  and its [exact cover](https://static.dc.com/2024-10/ABS_SM_Cv1_00111_DIGITAL.jpg?w=540).
- [Batman (1940-) #463](https://www.dcuniverseinfinite.com/comics/book/batman-1940-463/cd396b6b-50f5-4741-99df-16c0f1f26fa9).
- Deadpool/Batman exact barcode **75960621349800112**:
  [historical PRH metadata URL](https://prhcomics.com/book/?isbn=75960621349800112)
  redirects to `https://prhcomics.com/404`; the
  [exact barcode cover](https://images.penguinrandomhouse.com/cover/75960621349800112)
  still returns HTTP 200.

An additional official-source search from **11:19:58 to 11:20:31 UTC**, within a
two-minute limit, found no verified replacement page for that exact second
printing. The equivalent Penguin Random House Retail book URL also redirects to
its 404 page. Marvel's available main issue record identifies barcode
**75960621349800111**, so it cannot replace the exact second-printing source.
No substitute source or new verification status was installed.

## Static receipt and reproduction

[book-cover-audit-20261027.json](evidence/book-cover-audit-20261027.json) records
all 46 IDs/URLs/raw hashes, the five representation comparisons, timestamps,
thumbnail recipe, source-page checks, and SHA-256 values of its static inputs.
The historical reference definitions remain in:

- `backend/data/book_reference_covers_20261017.json`
- `backend/data/book_catalogue_starter_20261016.json`
- `backend/data/book_catalogue_expansion_20261021.json`
- `docs/evidence/book-queue-publisher-thumbnails-20261018.json`

From the repository root with its dependencies installed, this read-only probe
repeats the 46 bounded source reads and compares raw and rendered hashes:

```sh
PYTHONPATH=backend python - <<'PY'
import asyncio, hashlib, json
from pathlib import Path
from app.catalogue_artwork import thumbnail
from app.recognition_images import reference_image_bytes, close_reference_http_client

receipt = json.loads(Path('docs/evidence/book-cover-audit-20261027.json').read_text())
assert len(receipt['entries']) == 46

async def main():
    try:
        for entry in receipt['entries']:
            payload = await reference_image_bytes(entry['image_url'])
            raw = hashlib.sha256(payload.data).hexdigest() if payload else None
            rendered = hashlib.sha256(thumbnail(payload).data).hexdigest() if payload else None
            print(entry['catalogue_id'], 'loaded=', payload is not None,
                  'raw_matches_audit=', raw == entry['live_raw_sha256'],
                  'raw_matches_history=', raw == entry['observed_historical_sha256'],
                  'thumbnail_matches_history=', rendered == entry['observed_historical_sha256'])
    finally:
        await close_reference_http_client()

asyncio.run(main())
PY
```

Source bytes may change after this dated audit. Hash comparisons must identify
the representation: raw source format/header choices and rendered thumbnails
are different artifacts. None of these observations verifies ownership,
physical condition, exact physical printing or permission to reuse covers as
storefront product media.
