# Drop Rate catalogue implementation — 26 October 2026

This run implements and verifies the existing integrations. Supabase remains authoritative for live identity, current prices, ownership and inventory. R2 stores approved artwork and verified historical evidence.

## Verified artwork and R2 delivery

- All 398 pending approved images were copied and independently read back, bringing verified mirrors to 401. The worker-eligible backlog is zero. Provider breakdown: TCGdex 175, Punk Records 214, Bandai Official 6, Bandai One Piece Official 6.
- Four bounded passes completed with zero image failures: 5, 155, 165 and 73. Each write checks rights and current source identity again after the network operation.
- A real catalogue-product query was processed through the live signing helper. The resulting private R2 image returned HTTP 200 as WebP and matched the stored SHA-256/size. Raw object keys were removed and the original-source fallback remained present. Delivery is enabled.
- URL fetching now rejects redirects, limits source bytes and total transfer time, and decodes to vetted WebP before upload.
- The broad reference-image cache is still zero: approval for the 401 canonical assets does not grant redistribution rights over the entire reference catalogue.
- 3,331 previously blank TCGdex artwork links were restored only after exact identity and decoded image-byte checks. 62,512 of 69,545 reference cards now have an image URL; 7,033 remain blank (English Pokémon 1,181, Japanese Pokémon 5,852). Existing nonblank URLs were not all remotely loaded in this run.
- The full 4,001 repair allowlist was traversed: 3,331 successful images and 670 upstream 404s. An additional 75 Japanese and 15 English canonical-path samples all returned 404. No other-language or guessed artwork substitution was made.
- The inactive DR94 workflow export now routes failures to DR90. Actual recurring n8n execution and controlled failure-routing proof remain outstanding; the recurring workflow was not activated.

## Books

The live comic/manga edition count rose from 48 to 95: 32 reviewed pilot rows and 15 reviewed expansion rows. The expansion contains seven manga, four Marvel and four other comic editions. Exact ISBN/source conflicts are rejected, and questionable classifications and a conflicting Bleach omnibus are held.

The source is a bounded Open Library monthly-dump adapter, not API bulk harvesting. It preserves attribution and edition identifiers. These are factual metadata imports; no cover-distribution approval or market prices are inferred. Full comic/manga coverage, covers and market values remain incomplete.

## Price and display safeguards

Empty provider quotes retain existing dated evidence without pretending it was refreshed. PokéWallet guides retain their source, regional and currency provenance. Existing bounded hourly price batches run before the long bulk pass. Raw catalogue/inventory displays can show validated guides; a guide does not become an owned-copy valuation.

Legacy Unlimited Pikachu 58 resolves only to the matching unlimited printing. Legacy Dragon Ball Super records require an explicit Masters profile and one of six reviewed exact release aliases. Finish, rarity, language, source and currency checks remain in place; ambiguous leaders, prerelease and Normal-labelled intrinsic foils are excluded.

All repairs leave ownership, acquisition cost, inventory valuations, Store Prices and Shopify untouched. Inventory readback remains 616 rows with canonical full-row checksum `07764a89893ce22080b0659ea63a4def`.

## Scope and remaining source gaps

The physical-card coverage denominator is 67,065. The 2,480 Pokémon Pocket digital records are identified by their documented release identities and excluded consistently. Coverage includes explicitly labelled marketplace guides; it is not a count of condition-specific UK sold comparables.

Naruto alone contributes 7,166 records without a connected permitted pricing feed. Even complete coverage of every other physical card would reach only 89.32%. Other remaining gaps include exact print/variant mapping, unavailable Japanese sources and missing upstream quotes. The 90% target cannot be truthfully declared achieved by changing the denominator, substituting alternate printings or creating values.

## Operational evidence

The database history archive copies, restores and verifies every row before guarded cleanup. The current-price and inventory tables remain live in Supabase. R2 remains private with public access and completed-object expiration disabled.

Key deployments:
- R2 155-image pass: `e6cbba74-1cd7-429c-812a-7dd2d74f7fe3`.
- R2 165-image pass, 15-book expansion and actual delivery proof: `f5abfef8-94c5-47b5-bd97-581bea48991b`.
- Final 73-image pass and bounded source probes: `15aec4d1-fd8f-4678-8310-bbbce3ef94d7`.
- Generations source preview: `16dbc833-de4e-4397-a05f-6846063b55b4`.

Approved changes are reviewed and merged through GitHub PRs 734–747, with the latest applicable backend, PostgreSQL, dashboard/browser and n8n checks passing. Failed intermediate fixture runs were corrected and rechecked before merge. Final receipts and active deployment are recorded below.

### Generations and display verification

Deployment `496835f0-81f8-4c1d-8b71-98d37b18efa1` reached SUCCESS. The Radiant Collection operator committed all 32 exact guides at 23:28 UTC, covering seven previously unpriced records. Database readback confirmed all 32 were checked by this run; their original source observation date was preserved. The other 85 Generations catalogue-price rows retained full-row fingerprint `d9c85dbc52b978c9fcaed0122c987e24`.

The shared Masters display probe found 16 available guides across 28 canonical legacy records. Its 31 active inventory rows resolved to 17 physical references, one additional display guide and 13 unavailable records. This was a read-only check with zero provider calls or database writes. A separate review found no further confirmed missing-value renderer defect; portfolio totals deliberately exclude display-only guides.

OP-16 preview checked the full catalogue and source group in three requests. Of 28 missing base printings, only Koby OP16-064 had an admissible current guide. Other records remained excluded for ambiguous printings or unmatched names; no inferred variant values were introduced.

OP-16 apply completed in deployment `645f9d10-1600-4d33-8d78-d7cfc4cd7d3a` (SUCCESS). Durable receipt `4059fd5a-6e40-42ba-ad21-602fb6b58952` records one quote written and independently read back, with zero provider failures. Operation UUID: `facaa7aa-fa08-49e1-9806-7df5bd499c73`.

### Fusion implementation

PR746 adds only the two reviewed releases (official SB01 583201/source24335 and ST01 583301/source24680). A source record must independently prove a V1 base product; all competitors must prove labelled alternate status. Source IDs, titles, numbers, rarity, names and release URL paths must agree. Unknown or contradictory competitors veto a match. TCGplayer fallback is disabled for this mapping because Cardmarket V1 proof does not prove a merged TCGplayer variant. SB02 remains excluded because the observed source records are misfiled.

Each operator run is capped at eight provider requests and 90 seconds, respects existing quota protection, requires the configured administrator and global maintenance lock, and checks database capacity. It persists operation UUID/scope before network calls, reads committed rows by that UUID and records incomplete/interrupted outcomes accurately. Two independent reviews cleared the final fixes. Final-head CI passed 6,855 backend tests, dashboard checks and the n8n image build.

No SB01/ST01 canonical products or inventory copies currently exist in the owned-product catalogue, so there was no eligible owner-display scope to expand. These imports provide reference-catalogue guides.

Fusion previews completed in deployment `0f53f02c-f9d1-4ad5-8f7a-951575ddf12c` (SUCCESS, readiness HTTP 200): SB01 produced one eligible guide from 17 exact matches in six requests; ST01 produced 37 eligible guides from 67 exact matches in eight requests. No provider failures or unattempted queries were reported. Matched identities without a usable quote remain missing rather than borrowing alternate-product prices.

Fusion normal-guide apply completed with verified committed readback: SB01 one row, receipt `e9aa8404-94a8-4828-93fc-f847a919ac50`; ST01 37 rows, receipt `078003b4-03ea-4482-9627-685ab01d6ef7`. Both reported COMPLETE, zero provider failures and a finalized durable receipt. Deployment: `f9f7b112-1b82-4693-8e59-d5ddef48bba4`.

### Explicit foil availability

PR747 corrects one additional omission for the same reviewed V1 products: an
unusable normal trend no longer hides a sole positive foil trend. Duplicate or
unknown finish records reject the product before either finish is chosen.
Accepted foil guides remain labelled Holofoil and retain their Cardmarket
product, EUR evidence and validated GBP conversion. No alternate product or
TCGplayer quote is substituted. The final patch passed 6,880 backend tests,
dashboard checks, the n8n image build and independent review. Preview reports
now include finish counts and precise no-quote reasons.

The foil preview deployment `1c3ee303-3e6f-463d-ab8d-a5128a5c3cbf` succeeded. It
confirmed **46 additional positive Holofoil guides** on the already-proved V1
products: 16 SB01 and 30 ST01. All target shards were examined with zero provider
failures; no ambiguous finish or missing positive quote remained among those
46 verified identities. Remaining identity conflicts stayed excluded.

### Independent R2 closeout

At 23:42:17 UTC an independent read-only query reproduced the exact worker
eligibility filters and confirmed 401 mirrors with zero pending candidates.
All metadata passed SHA-256 format, exact content-addressed key, WebP type,
1–10,000,000-byte size and verification-timestamp checks. Stored sizes range
from 37,504 to 259,426 bytes. This supplements the actual upload/read-back and
signed-delivery proofs above; it is not a new blanket load test of external
reference URLs.

The foil apply committed and read back **36** of those 46 guides: ST01 30
(receipt `e7765a11-7ff3-4f84-8954-fd8220af583f`, COMPLETE) and SB01 six
(receipt `95c0b162-8f64-4e72-9036-89954ddd02ae`, INCOMPLETE). The second run
stopped on the existing `SHARED_QUOTA_LOW` reserve. It did not bypass the
provider limit. Both receipts finalized and the committed outcome is known.

Operator deployment `fd723860-0ba3-4607-89d0-aa5b78b8bd68` therefore correctly
failed its predeploy gate after the partial batch; the previously healthy
deployment continued serving. A fresh normal deployment was requested after
restoring the original predeploy checks. This operational failure must not be
reported as either a full 46-row apply or an application outage.

Ten previewed SB01 guides remain unapplied until a permitted later refresh:
`583201:SB01-036`, `583201:SB01-030`, `583201:SB01-033`, `583201:SB01-057`, `583201:SB01-050`, `583201:SB01-051`, `583201:SB01-018`, `583201:SB01-019`, `583201:SB01-045`, `583201:SB01-049`.
The new mapping/finish rules are part of the regular refresh path; no quota
increase or new paid feed was configured. These ten known records do not
explain or close the much larger 90% coverage gap.

## Final verified checkpoint

Pricing/edition/artwork counts were measured at **23:44:45 UTC**; archive/storage
readback was refreshed at **23:45:35 UTC** on 26 October 2026.

| Area | Session baseline | Verified result | Remaining |
|---|---:|---:|---|
| Physical-card values or labelled guides | 42,482 / 67,065 (63.34%) | **42,962 / 67,065 (64.06%)** | 24,103 unpriced; 17,397 more required for 90% |
| Sealed-product guides | — | **2,740 / 3,890 (70.44%)** | 1,150 without a current guide |
| Reference artwork URL presence | 59,181 / 69,545 | **62,512 / 69,545 (89.89%)** | 7,033 blank URLs; not all nonblank external URLs load-tested |
| Approved private R2 media | 3 mirrored | **401 mirrored; zero eligible backlog** | Broad reference caching and recurring DR94 proof remain open |
| Comic/manga edition metadata | 48 | **95** | Comprehensive catalogue, covers and market values remain incomplete |

Card pricing increased by **480 supported values/guides**. English physical
Pokémon references have 20,765 / 21,290 supported values/guides (97.53%); the
global denominator and 90% target have not been narrowed to that subset.

R2 now holds **39,045 historical rows across nine verified archives**. Database
size is **356,215,955 bytes**, below the unchanged 400,000,000-byte refresh guard.
Inventory still contains 616 rows with unchanged full-row checksum
`07764a89893ce22080b0659ea63a4def`; the untouched 85 Generations base rows retain
`d9c85dbc52b978c9fcaed0122c987e24`.

Normal deployment `cef03cbd-f59b-4815-abbc-22b9cc19abf6` reached **SUCCESS** with
readiness **HTTP 200**. It ran all **6,880 backend tests**, restored the original
compile/test/Stripe sandbox/social probe predeploy sequence, and contains no
one-off price-import command. Desired configuration matches that sequence and
has no staged changes. The last-hour HTTP audit showed 67 requests and zero
5xx responses at its observation time.

The shared-quota stop above is the immediate reason the last ten verified foil
candidates were not imported. The broader coverage target needs permitted
pricing sources and additional exact printing mappings. Missing provider image
bytes and incomplete edition sources are separate data gaps. No invented
values, alternate-art substitution, inferred media rights or denominator change
was used to declare completion.

Machine-readable checkpoint:
[CATALOGUE_COMPLETION_COUNTS_20261026.json](CATALOGUE_COMPLETION_COUNTS_20261026.json).

## Resume order

1. After the provider quota permits, run the existing dry-run-default SB01
   operator, inspect its exact Holofoil preview, then apply the ten remaining
   identities with committed readback. Keep the current quota reserve intact.
2. Add a permitted Naruto pricing feed and continue exact release/printing
   mapping for other missing references; Naruto's 7,166 uncovered references
   prevent 90% even if every non-Naruto physical reference is priced.
3. Obtain verified replacement sources for the 7,033 blank artwork records.
   Approved canonical-media transfer is complete; broader reference mirroring
   still requires source-distribution permission.
4. Extend reviewed factual comic/manga edition imports and source their covers
   and market evidence independently. Do not equate the 95-edition metadata
   catalogue with full coverage.
5. Verify the installed DR94/DR90 workflow definitions, actual n8n execution
   and controlled failure routing before enabling recurring image mirroring.
