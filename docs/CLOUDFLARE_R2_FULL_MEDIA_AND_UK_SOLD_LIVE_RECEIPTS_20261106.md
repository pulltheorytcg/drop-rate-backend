# Live Cloudflare R2 full artwork-byte and vetted sold-source receipts — 6 Nov 2026

**VERIFIED private source checkpoints. NO customer-facing cutover, NO new Market Values published.**

## A. Actual private R2 artwork byte integrity: 66,619/66,619

The one-shot Railway worker finished at **21:19:15 UTC** in deployment `bed6c419-5a15-47b2-895b-ade96a38ae4f`, running reviewed main commit `791473f14afde0325b245b277924df2fed43ec03`. The worker returned `PRIVATE_R2_ALL_QUALIFIED_REFERENCE_BYTES_VERIFIED` after downloading and SHA256+size+WebP verifying:

| Independently byte-verified R2 object scope | Files | Recorded bytes |
|---|---:|---:|
| ALL source-`VERIFIED` reference image mirrors | 66,218 | 5,738,634,354 |
| ALL `tcg.media_object_mirrors` objects (canonical/provider media) | 401 | 47,085,306 |
| **Total** | **66,619** | **5,785,719,660** |

- **Missing/corrupt in checked scope:** 0; `actual_object_reads=66619`, `byte_verified=66619`, `byte_failed=0`, `full_reference_byte_coverage=true`.
- Reference metadata source fingerprint SHA256: `2e09b161f7a41d2daed61a5dcb4c894586dd74dfde74ad8d8f557518d24dbab3`.
- Private immutable, readback-verified R2 report SHA256: `86613aef6139432bfd069b20eb83c240f59ec17ab2ea0f48dabc0bbfd118a0e2`, 766 bytes.
- Source SQL writes **0**, D1 writes **0**, prices changed **0**; no Shopify or identity cutover, no media rights granted.
- Four `RETRY` reference records were not part of the `VERIFIED` set: do not mark those four images as healthy.
- This proves **bytes** and R2 object identity for the 66,619 selected metadata entries. It does NOT independently establish rights to reproduce images, correct language/grade/printing/subject, image relevance or approval for storefront publication. Those need separate deterministic identity and licence checks.

**Important physical-photo gap (read-only live source confirmed 21:27 UTC):** 621 inventoried physical copies, including 12 graded. Only 43 distinct inventory IDs have any linked media asset. **0/621** inventory IDs (and **0/12** graded items) have an inventory-linked `media_object_mirrors` record. The 401 objects above are *canonical/provider image mirrors*, not 401 photos of unique physical cards. Some images may be available in Shopify, but this R2 audit does not certify them. Do not substitute raw card art for a slab image. First-party upload/association and product media approval remain release blockers.

## B. Lossless private R2 UK sold-observation export: 1,083/1,083

The separate one-shot Railway worker finished at **21:22:04 UTC**, deployment `5be5b623-19ea-4439-ac7b-1b1c09365d32`, returning `PRIVATE_R2_UK_SOLD_SOURCE_ROWS_VERIFIED` with `r2_uploaded=true`, **1,083 original `SOLD` source observations** and verified gzip/SHA256 R2 byte download + exact per-record roundtrip.

- Source data SHA256 `baf6cbdf8a3ac4080cd47433c3522c36f7ea12b323a3d7f999afd85a62c8c7fe`.
- Compressed archive SHA256 `18a82e39b8f89e2403ab1a6251870560535cb7c195c906472158d6c45099c27d`; **121,250 bytes**.
- Private R2 verification report SHA256 `6946342d6e1ebadbcbeca3350d047fb46610efc85b341e8f65102bca7b8d714f`.
- The export uses a **closed 20-column whitelist**, excluding source free-text `metadata`, provider URLs/titles, customer records and credential-like JSON. PostgreSQL was read using a repeatable-read, read-only transaction. Source writes **0**, D1 writes **0**.
- These are **source-classified sold observations awaiting independent usage-rights, exact comparables and sale provenance checks**; `sample_size_eligible_for_market_value=false`, `prices_published=0`. No Cardmarket `PRICE_GUIDE` observations were promoted. No eBay Browse active listing/RRP/guide/asking price was accepted as sold-market value.

## C. Relationship to operational exit

- Previously **1,184** real owner/inventory/order/ledger/media-metadata source rows were staged and hash-checked in an *isolated* operational D1 generation. Production pointer remains absent.
- Previously **67,801** original source rows across 10/11 approved operational relations were archived in private R2. `owner_memberships` **6 rows** were excluded in their entirety from *that R2 archive* due to maintenance-account RLS, though all 6 were separately captured and verified in D1 via a protected privileged **read-only** source snapshot. Do not claim R2 11/11.
- A 148-relation Supabase exit, Auth replacement, source delta replay, one-database D1 transactional owner-finance parity, rights/scanner correctness, inventory photo handoff, complete eligible Market Values, rollback tests and final protected switch are **not complete**.

**Release rule:** Fail closed. Leave Supabase as live PostgreSQL/identity, Shopify as existing storefront, and D1/R2 shadows private until all independent data, photo, identity, money, idempotency and rollback gates pass. Do not delete originals or approve a paid quota upgrade implicitly.
